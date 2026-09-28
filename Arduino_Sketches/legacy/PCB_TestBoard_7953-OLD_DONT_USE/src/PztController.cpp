#include "PztController.h"

#include <string.h>

#include "../ConfigurableParameters.h"
#include "ApiProtocol.h"

namespace {
DMAMEM static uint16_t g_samples[testboard_config::kMaxAdcRoutes];
DMAMEM static uint8_t g_wire_block[
    4 + testboard_config::kMaxAdcRoutes * sizeof(uint16_t) + api_protocol::kTrailerBytes];

bool isUnsignedNumber(const String &value) {
  if (!value.length()) return false;
  for (uint16_t index = 0; index < value.length(); ++index) {
    if (!isDigit(value.charAt(index))) return false;
  }
  return true;
}
}  // namespace

PztController::PztController(AdcDevice **adcs, uint8_t adc_count, UsbSerialController &usb)
    : adcs_(adcs), adc_count_(adc_count), usb_(usb) {}

void PztController::begin() {
  vmid_channel_ = testboard_config::kDefaultVmidChannel;
  vmid_park_enabled_ = testboard_config::kDefaultVmidParkEnabled;
  array_selection_ = ARRAY_BOTH;
  scan_order_ = SCAN_INTERLEAVED;
  for (uint8_t index = 0; index < adc_count_; ++index) {
    adcs_[index]->begin();
  }
}

bool PztController::adcSelected(uint8_t adc) const {
  if (adc >= adc_count_) return false;
  if (array_selection_ == ARRAY_BOTH) return true;
  if (array_selection_ == ARRAY_1) return adc < 2;
  return adc >= 2;
}

bool PztController::setAdcChannels(const String &arguments) {
  if (running_) return false;
  AdcRoute parsed[testboard_config::kMaxAdcRoutes];
  uint8_t parsed_count = 0;
  int start = 0;

  while (start < static_cast<int>(arguments.length())) {
    const int comma = arguments.indexOf(',', start);
    String token = arguments.substring(start, comma < 0 ? arguments.length() : comma);
    token.trim();
    const int colon = token.indexOf(':');
    if (colon <= 0 || colon >= static_cast<int>(token.length()) - 1) return false;
    String adc_text = token.substring(0, colon);
    String channel_text = token.substring(colon + 1);
    adc_text.trim();
    channel_text.trim();
    if (!isUnsignedNumber(adc_text) || !isUnsignedNumber(channel_text)) return false;

    const int adc_number = adc_text.toInt();
    const int channel = channel_text.toInt();
    if (adc_number < 1 || adc_number > adc_count_ ||
        channel < 0 || channel >= testboard_config::kAdcChannels ||
        !adcSelected(static_cast<uint8_t>(adc_number - 1))) {
      return false;
    }

    const AdcRoute route = {
        static_cast<uint8_t>(adc_number - 1),
        static_cast<uint8_t>(channel),
    };
    bool duplicate_route = false;
    for (uint8_t index = 0; index < parsed_count; ++index) {
      if (parsed[index].adc == route.adc && parsed[index].channel == route.channel) {
        duplicate_route = true;
      }
    }
    if (!duplicate_route) {
      if (parsed_count >= testboard_config::kMaxAdcRoutes) return false;
      parsed[parsed_count++] = route;
    }

    if (comma < 0) break;
    start = comma + 1;
  }

  if (parsed_count == 0) return false;
  memcpy(routes_, parsed, parsed_count * sizeof(AdcRoute));
  route_count_ = parsed_count;
  return true;
}

bool PztController::setArraySelection(const String &arguments) {
  if (running_) return false;
  String value = arguments;
  value.trim();
  value.toLowerCase();
  ArraySelection selection;
  if (value == "1" || value == "array1" || value == "array 1") {
    selection = ARRAY_1;
  } else if (value == "2" || value == "array2" || value == "array 2") {
    selection = ARRAY_2;
  } else if (value == "both") {
    selection = ARRAY_BOTH;
  } else {
    return false;
  }
  array_selection_ = selection;
  uint8_t kept = 0;
  for (uint8_t index = 0; index < route_count_; ++index) {
    if (adcSelected(routes_[index].adc)) routes_[kept++] = routes_[index];
  }
  route_count_ = kept;
  // A following adcchannels command may replace all routes.  Accept an empty
  // intermediate selection so switching directly from array 1 to array 2 is
  // possible without first restoring "both".
  return true;
}

bool PztController::setScanOrder(const String &arguments) {
  if (running_) return false;
  String value = arguments;
  value.trim();
  value.toLowerCase();
  if (value == "interleaved") scan_order_ = SCAN_INTERLEAVED;
  else if (value == "array") scan_order_ = SCAN_ARRAY;
  else if (value == "adc") scan_order_ = SCAN_ADC;
  else return false;
  return true;
}

bool PztController::setVmid(const String &arguments) {
  if (running_) return false;
  String value = arguments;
  value.trim();
  value.toLowerCase();
  if (value == "true") {
    vmid_park_enabled_ = true;
    return true;
  }
  if (value == "false") {
    vmid_park_enabled_ = false;
    return true;
  }
  if (!isUnsignedNumber(value)) return false;
  const int channel = value.toInt();
  if (channel < 0 || channel >= testboard_config::kAdcChannels) return false;
  for (uint8_t index = 0; index < route_count_; ++index) {
    if (routes_[index].channel == channel) return false;
  }
  vmid_channel_ = static_cast<uint8_t>(channel);
  vmid_park_enabled_ = true;
  parkSelectedAdcs();
  return true;
}

bool PztController::routesValid() const {
  return route_count_ > 0 && route_count_ <= testboard_config::kMaxAdcRoutes;
}

bool PztController::startRun(const String &arguments) {
  if (!routesValid()) return false;
  running_ = true;
  timed_run_ = arguments.length() > 0;
  run_duration_ms_ = timed_run_ ? static_cast<uint32_t>(arguments.toInt()) : 0;
  if (timed_run_ && run_duration_ms_ == 0) {
    running_ = false;
    return false;
  }
  parkSelectedAdcs();
  run_started_ms_ = millis();
  return true;
}

bool PztController::handleCommand(const String &command, const String &arguments) {
  if (command == "adcchannels") return setAdcChannels(arguments);
  if (command == "array") return setArraySelection(arguments);
  if (command == "scanorder") return setScanOrder(arguments);
  if (command == "vmid" || command == "ground") return setVmid(arguments);
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

uint8_t PztController::buildScanPlan(AdcRoute *destination) const {
  uint8_t output_count = 0;
  if (scan_order_ == SCAN_ADC) {
    for (uint8_t adc = 0; adc < adc_count_; ++adc) {
      for (uint8_t index = 0; index < route_count_; ++index) {
        if (routes_[index].adc == adc) destination[output_count++] = routes_[index];
      }
    }
    return output_count;
  }

  const uint8_t pair_count = scan_order_ == SCAN_ARRAY ? 2 : 1;
  for (uint8_t pair = 0; pair < pair_count; ++pair) {
    const uint8_t first_adc = scan_order_ == SCAN_ARRAY ? pair * 2 : 0;
    const uint8_t last_adc = scan_order_ == SCAN_ARRAY ? first_adc + 2 : adc_count_;
    for (uint8_t depth = 0; depth < route_count_; ++depth) {
      bool added = false;
      for (uint8_t adc = first_adc; adc < last_adc; ++adc) {
        uint8_t lane_depth = 0;
        for (uint8_t index = 0; index < route_count_; ++index) {
          if (routes_[index].adc != adc) continue;
          if (lane_depth++ == depth) {
            destination[output_count++] = routes_[index];
            added = true;
            break;
          }
        }
      }
      if (!added) break;
    }
  }
  return output_count;
}

void PztController::parkAdc(uint8_t adc) {
  if (!vmid_park_enabled_ || adc >= adc_count_) return;
  uint16_t discarded = 0;
  adcs_[adc]->readChannel(vmid_channel_, discarded);
}

void PztController::parkSelectedAdcs() {
  if (!vmid_park_enabled_) return;
  for (uint8_t adc = 0; adc < adc_count_; ++adc) {
    bool routed = false;
    for (uint8_t route = 0; route < route_count_; ++route) {
      if (routes_[route].adc == adc) routed = true;
    }
    if (routed) parkAdc(adc);
  }
}

bool PztController::captureBufferedBlock(const AdcRoute *plan, uint8_t plan_count) {
  const uint32_t started = micros();
  uint16_t sample_index = 0;
  for (uint8_t route_index = 0; route_index < plan_count; ++route_index) {
    const AdcRoute &route = plan[route_index];
    uint16_t sample = 0;
    if (!adcs_[route.adc]->readChannel(route.channel, sample)) sample = 0;
    g_samples[sample_index++] = sample;
    // The just-read PZT must not remain connected to the ADC input while
    // another ADC or route is sampled.
    parkAdc(route.adc);
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

bool PztController::captureArrayStreamedBlock(const AdcRoute *plan, uint8_t plan_count) {
  const uint16_t total_samples = plan_count;
  if (!total_samples) return false;

  usb_.beginBinaryBlock(total_samples);
  const uint32_t started = micros();
  uint16_t emitted_samples = 0;
  for (uint8_t array_number = 0; array_number < 2; ++array_number) {
    uint16_t chunk_count = 0;
    const uint8_t first_adc = array_number * 2;
    const uint8_t last_adc = first_adc + 2;
    for (uint8_t route_index = 0; route_index < plan_count; ++route_index) {
      const AdcRoute &route = plan[route_index];
      if (route.adc < first_adc || route.adc >= last_adc) continue;
      uint16_t sample = 0;
      if (!adcs_[route.adc]->readChannel(route.channel, sample)) sample = 0;
      g_samples[chunk_count++] = sample;
      parkAdc(route.adc);
    }
    if (chunk_count) {
      usb_.writeBinarySamples(g_samples, chunk_count);
      emitted_samples += chunk_count;
    }
  }

  const uint32_t ended = micros();
  if (emitted_samples != total_samples) return false;
  const uint16_t average = static_cast<uint16_t>(
      min((ended - started + emitted_samples / 2u) / emitted_samples, 65535u));
  usb_.endBinaryBlock(average, started, ended);
  return true;
}

bool PztController::captureBlock() {
  AdcRoute plan[testboard_config::kMaxAdcRoutes];
  const uint8_t plan_count = buildScanPlan(plan);
  if (plan_count != route_count_) return false;
  if (scan_order_ == SCAN_ARRAY) {
    return captureArrayStreamedBlock(plan, plan_count);
  }
  return captureBufferedBlock(plan, plan_count);
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
  if (running_) parkSelectedAdcs();
  running_ = false;
  timed_run_ = false;
}

bool PztController::isRunning() const {
  return running_;
}

const __FlashStringHelper *PztController::arraySelectionName() const {
  if (array_selection_ == ARRAY_1) return F("1");
  if (array_selection_ == ARRAY_2) return F("2");
  return F("both");
}

const __FlashStringHelper *PztController::scanOrderName() const {
  if (scan_order_ == SCAN_ARRAY) return F("array");
  if (scan_order_ == SCAN_ADC) return F("adc");
  return F("interleaved");
}

void PztController::printStatus() const {
  Serial.println(F("# -------- STATUS (PZT/ADS7953) --------"));
  Serial.print(F("# adcchannels="));
  for (uint8_t index = 0; index < route_count_; ++index) {
    if (index) Serial.print(',');
    Serial.print(routes_[index].adc + 1);
    Serial.print(':');
    Serial.print(routes_[index].channel);
  }
  Serial.println();
  Serial.print(F("# array=")); Serial.println(arraySelectionName());
  Serial.print(F("# scanorder=")); Serial.println(scanOrderName());
  Serial.print(F("# route_count=")); Serial.println(route_count_);
  Serial.print(F("# vmid_park=")); Serial.println(vmid_park_enabled_ ? F("true") : F("false"));
  Serial.print(F("# vmid_channel=")); Serial.println(vmid_channel_);
  for (uint8_t adc = 0; adc < adc_count_; ++adc) {
    Serial.print(F("# adc")); Serial.print(adc + 1);
    Serial.print(F("_errors=")); Serial.println(adcs_[adc]->errorCount());
  }
  Serial.print(F("# running=")); Serial.println(running_ ? F("true") : F("false"));
  Serial.println(F("# --------------------------------------"));
}
