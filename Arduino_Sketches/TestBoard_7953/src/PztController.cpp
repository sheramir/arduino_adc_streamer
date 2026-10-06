#include "PztController.h"

#include <string.h>

#include "ApiProtocol.h"
#include "ConfigurableParameters.h"

namespace {
// Restore ordinary SPI state on every exit, including acquisition failures.
class LpspiSession {
 public:
  bool begin(SpiController *spi) {
    if (spi == nullptr) return true;
    if (!spi->beginLpspiSession()) return false;
    spi_ = spi;
    return true;
  }
  void close() {
    if (spi_ != nullptr) spi_->endLpspiSession();
    spi_ = nullptr;
  }
  ~LpspiSession() { close(); }
 private:
  SpiController *spi_ = nullptr;
};

DMAMEM static uint16_t g_samples[testboard_config::kMaxAdcRoutes];
DMAMEM static uint8_t g_wire_block[
    4 + testboard_config::kMaxAdcRoutes * sizeof(uint16_t) +
    api_protocol::kTrailerBytes];

bool isUnsignedNumber(const String &value) {
  if (!value.length()) return false;
  for (uint16_t index = 0; index < value.length(); ++index) {
    if (!isDigit(value.charAt(index))) return false;
  }
  return true;
}
}  // namespace

PztController::PztController(
    Ads7953Adc **adcs, uint8_t adc_count, UsbSerialController &usb)
    : adcs_(adcs), adc_count_(adc_count), usb_(usb) {}

void PztController::begin() {
  array_selection_ = ARRAY_BOTH;
  scan_order_ = SCAN_INTERLEAVED;
  adc_sequence_ = ADC_SEQUENCE_MANUAL;
  spi_engine_ = SPI_ENGINE_BLOCKING;
  spi_clock_hz_ = testboard_config::kDefaultSpiClockHz;
  channel_repeat_ = testboard_config::kDefaultChannelRepeat;
  vmid_between_channels_ = testboard_config::kDefaultVmidBetweenChannels;
  vref_range_2x_ = testboard_config::kAds7953Range2xVref;
  for (uint8_t index = 0; index < adc_count_; ++index) {
    adcs_[index]->begin();
  }
  applyVrefRange();
}

bool PztController::adcSelected(uint8_t adc) const {
  if (adc >= adc_count_) return false;
  if (array_selection_ == ARRAY_BOTH) return true;
  if (array_selection_ == ARRAY_1) return adc < 2;
  return adc >= 2;
}

bool PztController::adcHasRoutes(uint8_t adc) const {
  for (uint8_t index = 0; index < route_count_; ++index) {
    if (routes_[index].adc == adc) return true;
  }
  return false;
}

uint8_t PztController::activeAdcsOnBus(uint8_t bus) const {
  const uint8_t first_adc = bus * 2;
  uint8_t count = 0;
  if (first_adc < adc_count_ && adcHasRoutes(first_adc)) ++count;
  if (first_adc + 1 < adc_count_ && adcHasRoutes(first_adc + 1)) ++count;
  return count;
}

bool PztController::setAdcChannels(const String &arguments) {
  if (running_) return false;
  AdcRoute parsed[testboard_config::kMaxAdcRoutes];
  uint8_t parsed_count = 0;
  int start = 0;

  while (start < static_cast<int>(arguments.length())) {
    const int comma = arguments.indexOf(',', start);
    String token = arguments.substring(
        start, comma < 0 ? arguments.length() : comma);
    token.trim();
    const int colon = token.indexOf(':');
    if (colon <= 0 || colon >= static_cast<int>(token.length()) - 1) {
      return false;
    }
    String adc_text = token.substring(0, colon);
    String channel_text = token.substring(colon + 1);
    adc_text.trim();
    channel_text.trim();
    if (!isUnsignedNumber(adc_text) || !isUnsignedNumber(channel_text)) {
      return false;
    }

    const int adc_number = adc_text.toInt();
    const int channel = channel_text.toInt();
    if (adc_number < 1 || adc_number > adc_count_ || channel < 0 ||
        channel >= testboard_config::kAdcChannels ||
        channel == testboard_config::kDefaultVmidChannel ||
        !adcSelected(static_cast<uint8_t>(adc_number - 1))) {
      return false;
    }

    const AdcRoute route = {
        static_cast<uint8_t>(adc_number - 1),
        static_cast<uint8_t>(channel),
    };
    bool duplicate_route = false;
    for (uint8_t index = 0; index < parsed_count; ++index) {
      if (parsed[index].adc == route.adc &&
          parsed[index].channel == route.channel) {
        duplicate_route = true;
        break;
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

bool PztController::setAdcSequence(const String &arguments) {
  if (running_) return false;
  String value = arguments;
  value.trim();
  value.toLowerCase();
  if (value == "manual") adc_sequence_ = ADC_SEQUENCE_MANUAL;
  else if (value == "auto1" || value == "auto-1") {
    adc_sequence_ = ADC_SEQUENCE_AUTO1;
  } else {
    return false;
  }
  return true;
}

bool PztController::setSpiEngine(const String &arguments) {
  if (running_) return false;
  String value = arguments;
  value.trim();
  value.toLowerCase();
  if (value == "blocking") spi_engine_ = SPI_ENGINE_BLOCKING;
  else if (value == "dma") spi_engine_ = SPI_ENGINE_DMA;
  else if (value == "lpspi") spi_engine_ = SPI_ENGINE_LPSPI;
  else return false;
  return true;
}

bool PztController::setSpiClock(const String &arguments) {
  if (running_) return false;
  String value = arguments;
  value.trim();
  if (!isUnsignedNumber(value)) return false;
  const uint32_t clock_hz = static_cast<uint32_t>(value.toInt());
  if (clock_hz < testboard_config::kMinSpiClockHz ||
      clock_hz > testboard_config::kMaxSpiClockHz) {
    return false;
  }
  for (uint8_t index = 0; index < adc_count_; ++index) {
    if (!adcs_[index]->spiController().setClockHz(clock_hz)) return false;
  }
  spi_clock_hz_ = clock_hz;
  return true;
}

bool PztController::setChannelRepeat(const String &arguments) {
  if (running_) return false;
  String value = arguments;
  value.trim();
  if (!isUnsignedNumber(value)) return false;
  const int repeat = value.toInt();
  if (repeat < 1 || repeat > 3) return false;
  channel_repeat_ = static_cast<uint8_t>(repeat);
  return true;
}

bool PztController::setVmid(const String &arguments) {
  if (running_) return false;
  String value = arguments;
  value.trim();
  value.toLowerCase();
  if (value == "true") {
    vmid_between_channels_ = true;
    return true;
  }
  if (value == "false") {
    vmid_between_channels_ = false;
    return true;
  }
  if (!isUnsignedNumber(value) ||
      value.toInt() != testboard_config::kDefaultVmidChannel) {
    return false;
  }
  vmid_between_channels_ = true;
  return parkActiveAdcs();
}

bool PztController::routesValid() const {
  return route_count_ > 0 &&
         route_count_ <= testboard_config::kMaxAdcRoutes;
}

bool PztController::setVrefRange(const String &arguments) {
  if (running_) return false;
  String value = arguments;
  value.trim();
  value.toLowerCase();
  bool range_2x;
  if (value == "2.5" || value == "2.5v" || value == "1x" ||
      value == "1xvref") {
    range_2x = false;
  } else if (value == "5" || value == "5.0" || value == "5v" ||
             value == "2x" || value == "2xvref") {
    range_2x = true;
  } else {
    return false;
  }
  vref_range_2x_ = range_2x;
  applyVrefRange();
  return true;
}

void PztController::applyVrefRange() {
  for (uint8_t index = 0; index < adc_count_; ++index) {
    adcs_[index]->setRange2xVref(vref_range_2x_);
  }
}

bool PztController::startRun(const String &arguments) {
  if (!routesValid()) return false;
  const bool timed = arguments.length() > 0;
  const uint32_t duration = timed
      ? static_cast<uint32_t>(arguments.toInt())
      : 0;
  if (timed && duration == 0) return false;
  if (!parkActiveAdcs()) return false;
  if (!prepareRun()) return false;
  timed_run_ = timed;
  run_duration_ms_ = duration;
  run_started_ms_ = millis();
  running_ = true;
  return true;
}

bool PztController::handleCommand(
    const String &command, const String &arguments) {
  if (command == "adcchannels") return setAdcChannels(arguments);
  if (command == "array") return setArraySelection(arguments);
  if (command == "scanorder") return setScanOrder(arguments);
  if (command == "adcseq") return setAdcSequence(arguments);
  if (command == "spiengine") return setSpiEngine(arguments);
  if (command == "spiclock") return setSpiClock(arguments);
  if (command == "channelrepeat") return setChannelRepeat(arguments);
  if (command == "vmid" || command == "ground") return setVmid(arguments);
  if (command == "run") return startRun(arguments);
  if (command == "ref") return setVrefRange(arguments);
  if (command == "osr" || command == "gain" || command == "conv" ||
      command == "samp" || command == "rate") {
    return !running_;
  }
  return false;
}

uint8_t PztController::buildScanPlan(AdcRoute *destination) const {
  uint8_t output_count = 0;
  if (scan_order_ == SCAN_ADC) {
    for (uint8_t adc = 0; adc < adc_count_; ++adc) {
      for (uint8_t index = 0; index < route_count_; ++index) {
        if (routes_[index].adc == adc) {
          destination[output_count++] = routes_[index];
        }
      }
    }
    return output_count;
  }

  const uint8_t pair_count = scan_order_ == SCAN_ARRAY ? 2 : 1;
  for (uint8_t pair = 0; pair < pair_count; ++pair) {
    const uint8_t first_adc = scan_order_ == SCAN_ARRAY ? pair * 2 : 0;
    const uint8_t last_adc = scan_order_ == SCAN_ARRAY
        ? min(static_cast<uint8_t>(first_adc + 2), adc_count_)
        : adc_count_;
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

bool PztController::prepareRun() {
  if (buildScanPlan(scan_plan_) != route_count_) return false;
  memset(adc_route_counts_, 0, sizeof(adc_route_counts_));
  memset(adc_destinations_, 0xFF, sizeof(adc_destinations_));
  active_buses_[0] = active_buses_[1] = nullptr;
  for (uint8_t adc = 0; adc < adc_count_; ++adc) {
    adc_channel_masks_[adc] = 1u << testboard_config::kDefaultVmidChannel;
  }
  for (uint8_t index = 0; index < route_count_; ++index) {
    const AdcRoute &route = scan_plan_[index];
    ++adc_route_counts_[route.adc];
    adc_destinations_[route.adc][route.channel] = index;
    adc_channel_masks_[route.adc] |= static_cast<uint16_t>(1u << route.channel);
    active_buses_[route.adc / 2] = &adcs_[route.adc]->spiController();
  }
  if (adc_sequence_ == ADC_SEQUENCE_MANUAL) {
    for (uint8_t adc = 0; adc < adc_count_; ++adc) {
      if (!adc_route_counts_[adc]) continue;
      if (!buildManualStream(streams_[adc], adc, scan_plan_, route_count_,
                             activeAdcsOnBus(adc / 2) > 1)) return false;
    }
  }
  return true;
}

bool PztController::prepareSweepStream(uint8_t adc) {
  FrameStream &stream = streams_[adc];
  if (adc_sequence_ == ADC_SEQUENCE_AUTO1) return buildAuto1Stream(stream, adc);
  // Rewind only pipeline progress; preserve the precompiled manual operations.
  stream.cursor = 0;
  memset(stream.pending, 0, sizeof(stream.pending));
  return true;
}

void PztController::resetStream(FrameStream &stream, uint8_t adc) {
  // Operations beyond count are never executed. Do not clear the large op array.
  stream.count = stream.cursor = 0;
  memset(stream.pending, 0, sizeof(stream.pending));
  stream.auto_mode = false;
  stream.auto_capture_start = 0;
  memset(stream.auto_seen, 0, sizeof(stream.auto_seen));
  stream.auto_expected = stream.auto_captured = 0;
  stream.auto_wait_for_vmid = stream.auto_finished_parked = false;
  stream.auto_programmed_this_stream = stream.auto_resumed_persistent = false;
  stream.auto_program_mask = 0;
  stream.adc = adcs_[adc];
  stream.adc_index = adc;
  for (uint8_t channel = 0; channel < testboard_config::kAdcChannels;
       ++channel) {
    stream.auto_destinations[channel] = 0xFF;
  }
}

bool PztController::appendOp(
    FrameStream &stream, uint16_t command, bool expected_valid,
    uint8_t expected_channel, bool store, uint8_t destination) {
  if (stream.count >= testboard_config::kMaxFrameOps) return false;
  FrameOp &op = stream.ops[stream.count++];
  op.command = command;
  op.expected_channel = expected_channel;
  op.destination = destination;
  op.expected_valid = expected_valid;
  op.store = store;
  return true;
}

bool PztController::buildManualStream(
    FrameStream &stream, uint8_t adc, const AdcRoute *plan,
    uint8_t plan_count, bool park_after) {
  resetStream(stream, adc);
  bool found = false;
  uint8_t last_channel = testboard_config::kDefaultVmidChannel;
  for (uint8_t index = 0; index < plan_count; ++index) {
    if (plan[index].adc != adc) continue;
    found = true;
    last_channel = plan[index].channel;
    for (uint8_t repeat = 0; repeat < channel_repeat_; ++repeat) {
      if (!appendOp(
              stream, stream.adc->manualCommand(last_channel), true,
              last_channel, repeat + 1 == channel_repeat_, index)) {
        return false;
      }
    }
    if (vmid_between_channels_) {
      for (uint8_t drain = 0;
           drain < testboard_config::kAds7953PipelineFrames; ++drain) {
        if (!appendOp(
                stream,
                stream.adc->manualCommand(
                    testboard_config::kDefaultVmidChannel),
                true, testboard_config::kDefaultVmidChannel)) {
          return false;
        }
      }
    }
  }
  if (!found) return true;

  if (!vmid_between_channels_) {
    const uint8_t drain_channel = park_after
        ? testboard_config::kDefaultVmidChannel
        : last_channel;
    for (uint8_t drain = 0;
         drain < testboard_config::kAds7953PipelineFrames; ++drain) {
      if (!appendOp(
              stream, stream.adc->manualCommand(drain_channel), true,
              drain_channel)) {
        return false;
      }
    }
  }
  return true;
}

bool PztController::buildAuto1Stream(
    FrameStream &stream, uint8_t adc) {
  resetStream(stream, adc);
  stream.auto_mode = true;
  const uint16_t channel_mask = adc_channel_masks_[adc];
  memcpy(stream.auto_destinations, adc_destinations_[adc],
         sizeof(stream.auto_destinations));
  stream.auto_expected = adc_route_counts_[adc];
  if (!stream.auto_expected) return true;

  stream.auto_program_mask = channel_mask;
  stream.auto_programmed_this_stream =
      !auto1_mask_valid_[adc] || auto1_programmed_masks_[adc] != channel_mask;
  if (stream.auto_programmed_this_stream) {
    if (!appendOp(stream, stream.adc->auto1ProgramCommand()) ||
        !appendOp(stream, channel_mask)) {
      return false;
    }
  }

  if (stream.auto_programmed_this_stream || !auto1_active_parked_[adc]) {
    if (!appendOp(stream, stream.adc->auto1ControlCommand(true))) return false;
    // The first selected-channel response arrives two frames after the
    // Auto-1 control word. The program-register frames, when needed, are
    // already included in stream.count.
    stream.auto_capture_start =
        stream.count + testboard_config::kAds7953PipelineFrames - 1;
  } else {
    // This ADC remained in Auto-1 with its MUX parked on channel 15. Ignore
    // pipeline history until the discarded Vmid conversion is returned; that
    // frame also advances the MUX to the first enabled sensor channel.
    stream.auto_wait_for_vmid = true;
    stream.auto_resumed_persistent = true;
  }

  // Provide a guarded upper bound. consumeResponse() ends this stream as soon
  // as every sensor result has arrived; at that exact frame Auto-1 advances
  // the MUX from the highest sensor channel to the enabled Vmid channel.
  const uint8_t continuation_frames = stream.auto_expected +
      testboard_config::kAds7953PipelineFrames + 3;
  for (uint8_t index = 0; index < continuation_frames; ++index) {
    if (!appendOp(stream, stream.adc->continueCommand())) return false;
  }
  return true;
}

bool PztController::buildParkStream(FrameStream &stream, uint8_t adc) {
  resetStream(stream, adc);
  for (uint8_t frame = 0;
       frame < testboard_config::kAds7953PipelineFrames; ++frame) {
    if (!appendOp(
            stream,
            stream.adc->manualCommand(
                testboard_config::kDefaultVmidChannel))) {
      return false;
    }
  }
  return true;
}

bool PztController::executeFrame(
    Ads7953Adc *first_adc, uint16_t first_command, uint16_t &first_response,
    Ads7953Adc *second_adc, uint16_t second_command,
    uint16_t &second_response) {
  if (first_adc == nullptr && second_adc == nullptr) return true;
  if (first_adc != nullptr && second_adc != nullptr &&
      &first_adc->spiController() == &second_adc->spiController()) {
    return false;
  }

  if (spi_engine_ == SPI_ENGINE_BLOCKING) {
    if (first_adc != nullptr) {
      first_response = first_adc->transferBlocking(first_command);
    }
    if (second_adc != nullptr) {
      second_response = second_adc->transferBlocking(second_command);
    }
    return true;
  }

  SpiController *first_spi = first_adc == nullptr
      ? nullptr
      : &first_adc->spiController();
  SpiController *second_spi = second_adc == nullptr
      ? nullptr
      : &second_adc->spiController();
  bool first_started = false;
  bool second_started = false;

  if (spi_engine_ == SPI_ENGINE_DMA) {
    if (first_adc != nullptr) {
      first_started = first_spi->startDma16(
          first_adc->chipSelectPin(), first_command);
      if (!first_started) ++dma_start_errors_;
    }
    if (second_adc != nullptr) {
      second_started = second_spi->startDma16(
          second_adc->chipSelectPin(), second_command);
      if (!second_started) ++dma_start_errors_;
    }
  } else {
    if (first_adc != nullptr) {
      first_started = first_spi->startLpspi16(
          first_adc->chipSelectPin(), first_command);
      if (!first_started) ++lpspi_start_errors_;
    }
    if (second_adc != nullptr) {
      second_started = second_spi->startLpspi16(
          second_adc->chipSelectPin(), second_command);
      if (!second_started) ++lpspi_start_errors_;
    }
  }

  if ((first_adc != nullptr && !first_started) ||
      (second_adc != nullptr && !second_started)) {
    if (first_started) {
      if (spi_engine_ == SPI_ENGINE_DMA) first_spi->cancelDma16();
      else first_spi->cancelLpspi16();
    }
    if (second_started) {
      if (spi_engine_ == SPI_ENGINE_DMA) second_spi->cancelDma16();
      else second_spi->cancelLpspi16();
    }
    return false;
  }

  const uint32_t started_us = micros();
  while (true) {
    const bool first_done = first_adc == nullptr ||
        (spi_engine_ == SPI_ENGINE_DMA
             ? first_spi->dmaComplete()
             : first_spi->lpspiComplete());
    const bool second_done = second_adc == nullptr ||
        (spi_engine_ == SPI_ENGINE_DMA
             ? second_spi->dmaComplete()
             : second_spi->lpspiComplete());
    if (first_done && second_done) break;
    if (micros() - started_us >= testboard_config::kSpiTransferTimeoutUs) {
      ++transfer_timeouts_;
      if (first_adc != nullptr) {
        if (spi_engine_ == SPI_ENGINE_DMA) first_spi->cancelDma16();
        else first_spi->cancelLpspi16();
      }
      if (second_adc != nullptr) {
        if (spi_engine_ == SPI_ENGINE_DMA) second_spi->cancelDma16();
        else second_spi->cancelLpspi16();
      }
      return false;
    }
    yield();
  }

  bool success = true;
  if (first_adc != nullptr) {
    success = (spi_engine_ == SPI_ENGINE_DMA
                   ? first_spi->finishDma16(first_response)
                   : first_spi->finishLpspi16(first_response)) &&
              success;
  }
  if (second_adc != nullptr) {
    success = (spi_engine_ == SPI_ENGINE_DMA
                   ? second_spi->finishDma16(second_response)
                   : second_spi->finishLpspi16(second_response)) &&
              success;
  }
  return success;
}

bool PztController::consumeResponse(
    FrameStream &stream, const FrameOp &op, uint16_t response,
    uint16_t op_index) {
  if (stream.auto_mode) {
    if (op_index < stream.auto_capture_start) return true;
    const uint8_t channel = stream.adc->returnedChannel(response);
    if (stream.auto_wait_for_vmid) {
      if (channel == testboard_config::kDefaultVmidChannel) {
        stream.auto_wait_for_vmid = false;
      }
      return true;
    }
    if (channel < testboard_config::kAdcChannels &&
        stream.auto_destinations[channel] != 0xFF &&
        !stream.auto_seen[channel]) {
      const uint8_t destination = stream.auto_destinations[channel];
      g_samples[destination] = stream.adc->returnedSample(response);
      sample_written_[destination] = true;
      stream.auto_seen[channel] = true;
      ++stream.auto_captured;
      if (stream.auto_captured == stream.auto_expected) {
        // Channel 15 is the highest enabled channel. When the last sensor
        // result is shifted out, Auto-1 has already switched the MUX to Vmid.
        stream.auto_finished_parked = true;
        stream.cursor = stream.count;
      }
    }
    return true;
  }

  const PendingResult ready = stream.pending[0];
  for (uint8_t index = 1;
       index < testboard_config::kAds7953PipelineFrames; ++index) {
    stream.pending[index - 1] = stream.pending[index];
  }
  PendingResult &next =
      stream.pending[testboard_config::kAds7953PipelineFrames - 1];
  next.channel = op.expected_channel;
  next.destination = op.destination;
  next.valid = op.expected_valid;
  next.store = op.store;

  if (!ready.valid) return true;
  uint16_t sample = 0;
  if (!stream.adc->decodeResponse(response, ready.channel, sample)) {
    ++returned_channel_errors_;
    return false;
  }
  if (ready.store) {
    g_samples[ready.destination] = sample;
    sample_written_[ready.destination] = true;
  }
  return true;
}

void PztController::commitStreamState(const FrameStream &stream) {
  const uint8_t adc = stream.adc_index;
  if (adc >= adc_count_) return;
  if (!stream.auto_mode) {
    auto1_active_parked_[adc] = false;
    return;
  }
  if (stream.auto_programmed_this_stream) {
    auto1_programmed_masks_[adc] = stream.auto_program_mask;
    auto1_mask_valid_[adc] = true;
    ++auto1_program_count_;
  }
  if (stream.auto_resumed_persistent) ++auto1_resume_count_;
  auto1_active_parked_[adc] = stream.auto_finished_parked;
}

bool PztController::executeStreams(
    FrameStream *first, FrameStream *second) {
  while ((first != nullptr && first->cursor < first->count) ||
         (second != nullptr && second->cursor < second->count)) {
    FrameOp *first_op = first != nullptr && first->cursor < first->count
        ? &first->ops[first->cursor]
        : nullptr;
    FrameOp *second_op = second != nullptr && second->cursor < second->count
        ? &second->ops[second->cursor]
        : nullptr;
    uint16_t first_response = 0;
    uint16_t second_response = 0;
    if (!executeFrame(
            first_op == nullptr ? nullptr : first->adc,
            first_op == nullptr ? 0 : first_op->command, first_response,
            second_op == nullptr ? nullptr : second->adc,
            second_op == nullptr ? 0 : second_op->command, second_response)) {
      return false;
    }
    if (first_op != nullptr) {
      const uint16_t op_index = first->cursor++;
      if (!consumeResponse(*first, *first_op, first_response, op_index)) {
        return false;
      }
    }
    if (second_op != nullptr) {
      const uint16_t op_index = second->cursor++;
      if (!consumeResponse(*second, *second_op, second_response, op_index)) {
        return false;
      }
    }
  }
  if (first != nullptr && first->auto_mode &&
      first->auto_captured != first->auto_expected) {
    first->adc->recordError();
    ++returned_channel_errors_;
    return false;
  }
  if (second != nullptr && second->auto_mode &&
      second->auto_captured != second->auto_expected) {
    second->adc->recordError();
    ++returned_channel_errors_;
    return false;
  }
  return true;
}

bool PztController::parkActiveAdcs() {
  for (uint8_t position = 0; position < 2; ++position) {
    const uint8_t first_adc = position;
    const uint8_t second_adc = position + 2;
    FrameStream *first = nullptr;
    FrameStream *second = nullptr;
    if (first_adc < adc_count_ && adcHasRoutes(first_adc)) {
      if (!buildParkStream(streams_[first_adc], first_adc)) return false;
      first = &streams_[first_adc];
    }
    if (second_adc < adc_count_ && adcHasRoutes(second_adc)) {
      if (!buildParkStream(streams_[second_adc], second_adc)) return false;
      second = &streams_[second_adc];
    }
    if (!executeStreams(first, second)) return false;
    if (first != nullptr) commitStreamState(*first);
    if (second != nullptr) commitStreamState(*second);
  }
  return true;
}

bool PztController::captureBlock() {
  const uint8_t plan_count = route_count_;
  memset(sample_written_, 0, plan_count * sizeof(sample_written_[0]));
  const uint32_t started = micros();
  LpspiSession sessions[2];
  if (spi_engine_ == SPI_ENGINE_LPSPI &&
      (!sessions[0].begin(active_buses_[0]) || !sessions[1].begin(active_buses_[1]))) {
    ++lpspi_start_errors_;
    return false;
  }

  for (uint8_t position = 0; position < 2; ++position) {
    const uint8_t first_adc = position;
    const uint8_t second_adc = position + 2;
    FrameStream *first = nullptr;
    FrameStream *second = nullptr;
    if (first_adc < adc_count_ && adc_route_counts_[first_adc]) {
      if (!prepareSweepStream(first_adc)) return false;
      first = &streams_[first_adc];
    }
    if (second_adc < adc_count_ && adc_route_counts_[second_adc]) {
      if (!prepareSweepStream(second_adc)) return false;
      second = &streams_[second_adc];
    }
    if (!executeStreams(first, second)) return false;
    if (first != nullptr) commitStreamState(*first);
    if (second != nullptr) commitStreamState(*second);
  }

  for (uint8_t index = 0; index < plan_count; ++index) {
    if (!sample_written_[index]) return false;
  }
  sessions[0].close();
  sessions[1].close();
  const uint32_t ended = micros();
  const uint16_t average = plan_count
      ? static_cast<uint16_t>(min(
            (ended - started + plan_count / 2u) / plan_count, 65535u))
      : 0;
  const uint32_t bytes = api_protocol::encodeBinaryBlock(
      g_wire_block, sizeof(g_wire_block), g_samples, plan_count, average,
      started, ended);
  if (!bytes) return false;
  return usb_.writeBinaryBlock(g_wire_block, bytes);
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
  if (running_) (void)parkActiveAdcs();
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

const __FlashStringHelper *PztController::adcSequenceName() const {
  return adc_sequence_ == ADC_SEQUENCE_AUTO1 ? F("auto1") : F("manual");
}

const __FlashStringHelper *PztController::spiEngineName() const {
  if (spi_engine_ == SPI_ENGINE_DMA) return F("dma");
  if (spi_engine_ == SPI_ENGINE_LPSPI) return F("lpspi");
  return F("blocking");
}

const __FlashStringHelper *PztController::vrefRangeName() const {
  return vref_range_2x_ ? F("5.0") : F("2.5");
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
  Serial.print(F("# adcseq=")); Serial.println(adcSequenceName());
  Serial.print(F("# spiengine=")); Serial.println(spiEngineName());
  Serial.print(F("# spi_clock_hz=")); Serial.println(spi_clock_hz_);
  Serial.print(F("# channelrepeat_requested="));
  Serial.println(channel_repeat_);
  Serial.print(F("# channelrepeat_effective="));
  Serial.println(adc_sequence_ == ADC_SEQUENCE_AUTO1 ? 1 : channel_repeat_);
  Serial.print(F("# vmid_channel="));
  Serial.println(testboard_config::kDefaultVmidChannel);
  Serial.print(F("# vmid_between_channels_requested="));
  Serial.println(vmid_between_channels_ ? F("true") : F("false"));
  Serial.print(F("# vmid_between_channels_effective="));
  Serial.println(
      adc_sequence_ == ADC_SEQUENCE_MANUAL && vmid_between_channels_
          ? F("true") : F("false"));
  Serial.println(F("# vmid_parking=mandatory"));
  Serial.print(F("# route_count=")); Serial.println(route_count_);
  Serial.print(F("# vref=")); Serial.println(vrefRangeName());
  Serial.print(F("# active_adcs="));
  bool emitted = false;
  for (uint8_t adc = 0; adc < adc_count_; ++adc) {
    if (!adcHasRoutes(adc)) continue;
    if (emitted) Serial.print(',');
    Serial.print(adc + 1);
    emitted = true;
  }
  Serial.println();
  Serial.print(F("# active_spi_buses="));
  if (activeAdcsOnBus(0)) Serial.print('1');
  if (activeAdcsOnBus(0) && activeAdcsOnBus(1)) Serial.print(',');
  if (activeAdcsOnBus(1)) Serial.print('2');
  Serial.println();
  Serial.print(F("# dma_start_errors=")); Serial.println(dma_start_errors_);
  Serial.print(F("# lpspi_start_errors="));
  Serial.println(lpspi_start_errors_);
  Serial.print(F("# transfer_timeouts=")); Serial.println(transfer_timeouts_);
  Serial.print(F("# returned_channel_errors="));
  Serial.println(returned_channel_errors_);
  Serial.print(F("# usb_write_errors=")); Serial.println(usb_.writeErrors());
  Serial.print(F("# auto1_program_count="));
  Serial.println(auto1_program_count_);
  Serial.print(F("# auto1_resume_count="));
  Serial.println(auto1_resume_count_);
  for (uint8_t adc = 0; adc < adc_count_; ++adc) {
    Serial.print(F("# adc")); Serial.print(adc + 1);
    Serial.print(F("_errors=")); Serial.println(adcs_[adc]->errorCount());
  }
  Serial.print(F("# running="));
  Serial.println(running_ ? F("true") : F("false"));
  Serial.println(F("# --------------------------------------"));
}
