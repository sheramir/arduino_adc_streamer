#include "PztController.h"

#include <string.h>

#include "../ConfigurableParameters.h"
#include "ApiProtocol.h"

namespace {
DMAMEM static uint16_t g_samples[testboard_config::kMaxBlockSamples];
DMAMEM static uint8_t g_wire_block[
    4 + testboard_config::kMaxBlockSamples * sizeof(uint16_t) + api_protocol::kTrailerBytes];
}

PztController::PztController(AdcDevice **adcs, uint8_t adc_count, UsbSerialController &usb)
    : adcs_(adcs), adc_count_(adc_count), usb_(usb) {}

void PztController::begin() {
  channel_count_ = testboard_config::kDefaultChannelCount;
  memcpy(channels_, testboard_config::kDefaultChannels, channel_count_);
  repeat_ = testboard_config::kDefaultRepeat;
  buffer_sweeps_ = testboard_config::kDefaultBufferSweeps;
  ground_channel_ = testboard_config::kDefaultGroundChannel;
  ground_enabled_ = testboard_config::kDefaultGroundEnabled;
  for (uint8_t index = 0; index < adc_count_; ++index) {
    adcs_[index]->begin();
  }
}

bool PztController::setChannels(const String &arguments) {
  if (running_) return false;
  uint8_t parsed[testboard_config::kMaxChannelSequence];
  uint8_t count = 0;
  int start = 0;
  while (start < static_cast<int>(arguments.length())) {
    const int comma = arguments.indexOf(',', start);
    String token = arguments.substring(start, comma < 0 ? arguments.length() : comma);
    token.trim();
    for (uint16_t index = 0; index < token.length(); ++index) {
      if (!isDigit(token.charAt(index))) return false;
    }
    const int value = token.toInt();
    if (!token.length() || value < 0 || value >= testboard_config::kAdcChannels ||
        count >= testboard_config::kMaxChannelSequence) {
      return false;
    }
    parsed[count++] = static_cast<uint8_t>(value);
    if (comma < 0) break;
    start = comma + 1;
  }
  if (count == 0) return false;
  const uint32_t proposed_samples = static_cast<uint32_t>(count) * repeat_ *
                                    buffer_sweeps_ * adc_count_;
  if (proposed_samples > testboard_config::kMaxBlockSamples) return false;
  memcpy(channels_, parsed, count);
  channel_count_ = count;
  return true;
}

bool PztController::setRepeat(const String &arguments) {
  if (running_) return false;
  const int value = arguments.toInt();
  if (value < 1 || value > 255) return false;
  const uint8_t old = repeat_;
  repeat_ = static_cast<uint8_t>(value);
  if (!blockFits()) {
    repeat_ = old;
    return false;
  }
  return true;
}

bool PztController::setBuffer(const String &arguments) {
  if (running_) return false;
  const int value = arguments.toInt();
  if (value < 1 || value > 255) return false;
  const uint8_t old = buffer_sweeps_;
  buffer_sweeps_ = static_cast<uint8_t>(value);
  if (!blockFits()) {
    buffer_sweeps_ = old;
    return false;
  }
  return true;
}

bool PztController::setGround(const String &arguments) {
  if (running_) return false;
  String value = arguments;
  value.toLowerCase();
  if (value == "true") {
    ground_enabled_ = true;
    return true;
  }
  if (value == "false") {
    ground_enabled_ = false;
    return true;
  }
  const int channel = value.toInt();
  if (channel < 0 || channel >= testboard_config::kAdcChannels) return false;
  ground_channel_ = static_cast<uint8_t>(channel);
  ground_enabled_ = true;
  return true;
}

bool PztController::blockFits() const {
  const uint32_t total = static_cast<uint32_t>(channel_count_) * repeat_ *
                         buffer_sweeps_ * adc_count_;
  return total > 0 && total <= testboard_config::kMaxBlockSamples;
}

bool PztController::startRun(const String &arguments) {
  if (!blockFits()) return false;
  running_ = true;
  timed_run_ = arguments.length() > 0;
  run_duration_ms_ = timed_run_ ? static_cast<uint32_t>(arguments.toInt()) : 0;
  if (timed_run_ && run_duration_ms_ == 0) {
    running_ = false;
    return false;
  }
  run_started_ms_ = millis();
  return true;
}

bool PztController::handleCommand(const String &command, const String &arguments) {
  if (command == "channels") return setChannels(arguments);
  if (command == "repeat") return setRepeat(arguments);
  if (command == "buffer") return setBuffer(arguments);
  if (command == "ground") return setGround(arguments);
  if (command == "run") return startRun(arguments);
  // Compatibility controls used by existing array configuration. ADS7953 has
  // fixed 12-bit conversion and an external reference; these are accepted as
  // no-ops so the host protocol does not need a special configuration path.
  if (command == "ref" || command == "osr" || command == "gain" ||
      command == "conv" || command == "samp" || command == "rate") {
    return !running_;
  }
  return false;
}

bool PztController::captureBlock() {
  const uint32_t started = micros();
  uint16_t sample_index = 0;
  for (uint8_t sweep = 0; sweep < buffer_sweeps_; ++sweep) {
    for (uint8_t channel_index = 0; channel_index < channel_count_; ++channel_index) {
      const uint8_t channel = channels_[channel_index];
      if (ground_enabled_) {
        uint16_t discarded = 0;
        for (uint8_t adc = 0; adc < adc_count_; ++adc) {
          adcs_[adc]->readChannel(ground_channel_, discarded);
        }
      }
      for (uint8_t repeat_index = 0; repeat_index < repeat_; ++repeat_index) {
        // Wire order is channel -> repeat -> ADC1,ADC2,ADC3,ADC4.
        for (uint8_t adc = 0; adc < adc_count_; ++adc) {
          uint16_t sample = 0;
          adcs_[adc]->readChannel(channel, sample);
          g_samples[sample_index++] = sample;
        }
      }
    }
  }

  const uint32_t ended = micros();
  const uint16_t average = sample_index
      ? static_cast<uint16_t>(min((ended - started + sample_index / 2u) / sample_index, 65535u))
      : 0;
  const uint32_t bytes = api_protocol::encodeBinaryBlock(
      g_wire_block, sizeof(g_wire_block), g_samples, sample_index, average, started, ended);
  if (!bytes) return false;
  usb_.writeBinaryBlock(g_wire_block, bytes);
  return true;
}

void PztController::service() {
  if (!running_) return;
  if (timed_run_ && millis() - run_started_ms_ >= run_duration_ms_) {
    stop();
    return;
  }
  if (!captureBlock()) stop();
}

void PztController::stop() {
  running_ = false;
  timed_run_ = false;
}

bool PztController::isRunning() const {
  return running_;
}

void PztController::printStatus() const {
  Serial.println(F("# -------- STATUS (PZT/ADS7953) --------"));
  Serial.print(F("# channels="));
  for (uint8_t index = 0; index < channel_count_; ++index) {
    if (index) Serial.print(',');
    Serial.print(channels_[index]);
  }
  Serial.println();
  Serial.print(F("# repeat=")); Serial.println(repeat_);
  Serial.print(F("# buffer=")); Serial.println(buffer_sweeps_);
  Serial.print(F("# adc_lanes=")); Serial.println(adc_count_);
  Serial.print(F("# sample_order=channel,repeat,adc_lane")); Serial.println();
  Serial.print(F("# ground=")); Serial.println(ground_enabled_ ? F("true") : F("false"));
  Serial.print(F("# ground_channel=")); Serial.println(ground_channel_);
  for (uint8_t adc = 0; adc < adc_count_; ++adc) {
    Serial.print(F("# adc")); Serial.print(adc + 1);
    Serial.print(F("_errors=")); Serial.println(adcs_[adc]->errorCount());
  }
  Serial.print(F("# running=")); Serial.println(running_ ? F("true") : F("false"));
  Serial.println(F("# --------------------------------------"));
}
