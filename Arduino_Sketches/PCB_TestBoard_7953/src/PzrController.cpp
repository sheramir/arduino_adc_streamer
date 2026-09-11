#include "PzrController.h"

#include <math.h>
#include <string.h>

#include "../ConfigurableParameters.h"
#include "ApiProtocol.h"

namespace {
static uint16_t g_pzr_samples[testboard_config::kMaxBlockSamples];
static uint8_t g_pzr_wire[
    4 + testboard_config::kMaxBlockSamples * sizeof(uint16_t) + api_protocol::kTrailerBytes];
static constexpr float kLn2 = 0.69314718056f;
}

PzrController::PzrController(UsbSerialController &usb) : usb_(usb) {}

void PzrController::begin() {
  channel_count_ = testboard_config::kDefaultChannelCount;
  memcpy(channels_, testboard_config::kDefaultChannels, channel_count_);
  rb_ohm_ = testboard_config::kDefaultRbOhm;
  rk_ohm_ = testboard_config::kDefaultRkOhm;
  cf_f_ = testboard_config::kDefaultCfF;
  rx_max_ohm_ = testboard_config::kDefaultRxMaxOhm;
  if (!available()) return;

  pinMode(testboard_config::kPzrInputPin, INPUT);
  pinMode(testboard_config::kPzrMuxA0Pin, OUTPUT);
  pinMode(testboard_config::kPzrMuxA1Pin, OUTPUT);
  pinMode(testboard_config::kPzrMuxA2Pin, OUTPUT);
  pinMode(testboard_config::kPzrMuxA3Pin, OUTPUT);
  if (testboard_config::kPzrMuxEnablePin >= 0) {
    pinMode(testboard_config::kPzrMuxEnablePin, OUTPUT);
    digitalWrite(
        testboard_config::kPzrMuxEnablePin,
        testboard_config::kPzrMuxEnableActiveHigh ? HIGH : LOW);
  }
}

bool PzrController::available() const {
  return testboard_config::kEnablePzrHardware &&
         testboard_config::kPzrInputPin >= 0 &&
         testboard_config::kPzrMuxA0Pin >= 0 &&
         testboard_config::kPzrMuxA1Pin >= 0 &&
         testboard_config::kPzrMuxA2Pin >= 0 &&
         testboard_config::kPzrMuxA3Pin >= 0;
}

bool PzrController::setChannels(const String &arguments) {
  uint8_t count = 0;
  int start = 0;
  while (start < static_cast<int>(arguments.length())) {
    const int comma = arguments.indexOf(',', start);
    String token = arguments.substring(start, comma < 0 ? arguments.length() : comma);
    token.trim();
    for (uint16_t i = 0; i < token.length(); ++i) {
      if (!isDigit(token.charAt(i))) return false;
    }
    const int value = token.toInt();
    if (!token.length() || value < 0 || value > 15 || count >= sizeof(channels_)) return false;
    channels_[count++] = static_cast<uint8_t>(value);
    if (comma < 0) break;
    start = comma + 1;
  }
  if (!count) return false;
  channel_count_ = count;
  return true;
}

bool PzrController::setPositiveFloat(const String &arguments, float &target, bool capacitance) {
  double value = 0.0;
  if (!api_protocol::parseScaledValue(arguments, value, capacitance) || value <= 0.0) return false;
  target = static_cast<float>(value);
  return true;
}

bool PzrController::handleCommand(const String &command, const String &arguments) {
  if (!available() || running_) return false;
  if (command == "channels") return setChannels(arguments);
  if (command == "repeat") {
    const int value = arguments.toInt();
    if (value < 1 || value > 255) return false;
    const uint8_t previous = repeat_;
    repeat_ = static_cast<uint8_t>(value);
    if (static_cast<uint32_t>(channel_count_) * repeat_ * buffer_sweeps_ >
        testboard_config::kMaxBlockSamples) {
      repeat_ = previous;
      return false;
    }
    return true;
  }
  if (command == "buffer") {
    const int value = arguments.toInt();
    if (value < 1 || value > 255) return false;
    const uint8_t previous = buffer_sweeps_;
    buffer_sweeps_ = static_cast<uint8_t>(value);
    if (static_cast<uint32_t>(channel_count_) * repeat_ * buffer_sweeps_ >
        testboard_config::kMaxBlockSamples) {
      buffer_sweeps_ = previous;
      return false;
    }
    return true;
  }
  if (command == "rb") return setPositiveFloat(arguments, rb_ohm_, false);
  if (command == "rk") return setPositiveFloat(arguments, rk_ohm_, false);
  if (command == "cf") return setPositiveFloat(arguments, cf_f_, true);
  if (command == "rxmax") return setPositiveFloat(arguments, rx_max_ohm_, false);
  if (command == "ascii") {
    String value = arguments; value.toLowerCase();
    ascii_ = value == "1" || value == "true" || value == "on";
    return value == "0" || value == "false" || value == "off" || ascii_;
  }
  if (command == "run") {
    const uint32_t samples = static_cast<uint32_t>(channel_count_) * repeat_ * buffer_sweeps_;
    if (!samples || samples > testboard_config::kMaxBlockSamples) return false;
    timed_run_ = arguments.length() > 0;
    run_duration_ms_ = timed_run_ ? static_cast<uint32_t>(arguments.toInt()) : 0;
    if (timed_run_ && !run_duration_ms_) return false;
    run_started_ms_ = millis();
    running_ = true;
    return true;
  }
  return false;
}

void PzrController::selectMux(uint8_t channel) {
  digitalWriteFast(testboard_config::kPzrMuxA0Pin, (channel >> 0) & 0x01);
  digitalWriteFast(testboard_config::kPzrMuxA1Pin, (channel >> 1) & 0x01);
  digitalWriteFast(testboard_config::kPzrMuxA2Pin, (channel >> 2) & 0x01);
  digitalWriteFast(testboard_config::kPzrMuxA3Pin, (channel >> 3) & 0x01);
  delayMicroseconds(testboard_config::kPzrMuxSettleUs);
}

uint32_t PzrController::timeoutUs() const {
  const double ra = static_cast<double>(rx_max_ohm_ + rk_ohm_);
  double timeout = kLn2 * static_cast<double>(cf_f_) *
                   (ra + 2.0 * static_cast<double>(rb_ohm_)) * 1e6 * 3.0 + 20000.0;
  timeout = max(50000.0, min(timeout, 5000000.0));
  return static_cast<uint32_t>(timeout);
}

bool PzrController::measureResistance(uint8_t channel, uint16_t &sample) {
  selectMux(channel);
  const uint32_t timeout = timeoutUs();
  (void)pulseInLong(testboard_config::kPzrInputPin, HIGH, timeout);  // discard after switch
  const uint32_t high_us = pulseInLong(testboard_config::kPzrInputPin, HIGH, timeout);
  const uint32_t low_us = pulseInLong(testboard_config::kPzrInputPin, LOW, timeout);
  if (!high_us || !low_us) {
    sample = 0;
    return false;
  }
  // Astable 555: tH=ln(2)*C*(Ra+Rb), tL=ln(2)*C*Rb.
  const float ra = rb_ohm_ * (static_cast<float>(high_us) - low_us) / low_us;
  sample = static_cast<uint16_t>(constrain(lroundf(ra), 0L, 65535L));
  return true;
}

bool PzrController::emitBlock() {
  const uint32_t started = micros();
  uint16_t index = 0;
  for (uint8_t sweep = 0; sweep < buffer_sweeps_; ++sweep) {
    for (uint8_t channel = 0; channel < channel_count_; ++channel) {
      for (uint8_t repeat = 0; repeat < repeat_; ++repeat) {
        measureResistance(channels_[channel], g_pzr_samples[index]);
        ++index;
      }
    }
  }
  const uint32_t ended = micros();
  if (ascii_) {
    for (uint16_t i = 0; i < index; ++i) {
      if (i) Serial.print(',');
      Serial.print(g_pzr_samples[i]);
    }
    Serial.println();
    return true;
  }
  const uint16_t average = index
      ? static_cast<uint16_t>(min((ended - started + index / 2u) / index, 65535u))
      : 0;
  const uint32_t bytes = api_protocol::encodeBinaryBlock(
      g_pzr_wire, sizeof(g_pzr_wire), g_pzr_samples, index, average, started, ended);
  if (!bytes) return false;
  usb_.writeBinaryBlock(g_pzr_wire, bytes);
  return true;
}

void PzrController::service() {
  if (!running_) return;
  if (timed_run_ && millis() - run_started_ms_ >= run_duration_ms_) {
    stop();
    return;
  }
  if (!emitBlock()) stop();
}

void PzrController::stop() {
  running_ = false;
  timed_run_ = false;
}

bool PzrController::isRunning() const { return running_; }

void PzrController::printStatus() const {
  Serial.println(F("# -------- STATUS (PZR/555) --------"));
  Serial.print(F("# hardware=")); Serial.println(available() ? F("enabled") : F("not fitted"));
  Serial.print(F("# rb_ohm=")); Serial.println(rb_ohm_, 3);
  Serial.print(F("# rk_ohm=")); Serial.println(rk_ohm_, 3);
  Serial.print(F("# cf_f=")); Serial.println(cf_f_, 12);
  Serial.print(F("# rxmax_ohm=")); Serial.println(rx_max_ohm_, 3);
  Serial.print(F("# running=")); Serial.println(running_ ? F("true") : F("false"));
  Serial.println(F("# ----------------------------------"));
}
