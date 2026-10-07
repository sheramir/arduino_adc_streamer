#pragma once

#include <Arduino.h>

#include "Ads7953Adc.h"
#include "AcquisitionProfiler.h"
#include "ConfigurableParameters.h"
#include "UsbSerialController.h"

class PztController {
 public:
  PztController(Ads7953Adc **adcs, uint8_t adc_count,
                UsbSerialController &usb);

  void begin();
  bool handleCommand(const String &command, const String &arguments);
  void service();
  void stop();
  bool isRunning() const;
  void printStatus() const;

 private:
  struct AdcRoute {
    uint8_t adc;
    uint8_t channel;
  };

  enum ArraySelection : uint8_t { ARRAY_1, ARRAY_2, ARRAY_BOTH };
  enum ScanOrder : uint8_t { SCAN_INTERLEAVED, SCAN_ARRAY, SCAN_ADC };
  enum AdcSequence : uint8_t { ADC_SEQUENCE_MANUAL, ADC_SEQUENCE_AUTO1 };
  enum SpiEngine : uint8_t {
    SPI_ENGINE_BLOCKING,
    SPI_ENGINE_DMA,
    SPI_ENGINE_LPSPI,
  };

  struct FrameOp {
    uint16_t command;
    uint8_t expected_channel;
    uint8_t destination;
    bool expected_valid;
    bool store;
  };

  struct PendingResult {
    uint8_t channel;
    uint8_t destination;
    bool valid;
    bool store;
  };

  struct FrameStream {
    Ads7953Adc *adc;
    uint8_t adc_index;
    FrameOp ops[testboard_config::kMaxFrameOps];
    uint16_t count;
    uint16_t cursor;
    PendingResult pending[testboard_config::kAds7953PipelineFrames];
    bool auto_mode;
    uint16_t auto_capture_start;
    uint8_t auto_destinations[testboard_config::kAdcChannels];
    bool auto_seen[testboard_config::kAdcChannels];
    uint8_t auto_expected;
    uint8_t auto_captured;
    bool auto_wait_for_vmid;
    bool auto_finished_parked;
    bool auto_programmed_this_stream;
    bool auto_resumed_persistent;
    uint16_t auto_program_mask;
  };

  bool setAdcChannels(const String &arguments);
  bool setArraySelection(const String &arguments);
  bool setScanOrder(const String &arguments);
  bool setAdcSequence(const String &arguments);
  bool setSpiEngine(const String &arguments);
  bool setSpiClock(const String &arguments);
  bool setChannelRepeat(const String &arguments);
  bool setVmid(const String &arguments);
  bool setVrefRange(const String &arguments);
  bool startRun(const String &arguments);
  bool routesValid() const;
  bool captureBlock();
  bool prepareRun();
  bool prepareSweepStream(uint8_t adc);
  uint8_t buildScanPlan(AdcRoute *destination) const;

  void resetStream(FrameStream &stream, uint8_t adc);
  bool appendOp(FrameStream &stream, uint16_t command,
                bool expected_valid = false, uint8_t expected_channel = 0,
                bool store = false, uint8_t destination = 0);
  bool buildManualStream(FrameStream &stream, uint8_t adc,
                         const AdcRoute *plan, uint8_t plan_count,
                         bool park_after);
  bool buildAuto1Stream(FrameStream &stream, uint8_t adc);
  bool buildParkStream(FrameStream &stream, uint8_t adc);
  bool executeStreams(FrameStream *first, FrameStream *second);
  template <SpiEngine Engine>
  bool executeStreamsForEngine(FrameStream *first, FrameStream *second);
  template <SpiEngine Engine>
  bool executeFrame(Ads7953Adc *first_adc, uint16_t first_command,
                    uint16_t &first_response, Ads7953Adc *second_adc,
                    uint16_t second_command, uint16_t &second_response,
                    uint32_t timeout_ticks, uint32_t service_ticks);
  bool consumeResponse(FrameStream &stream, const FrameOp &op,
                       uint16_t response, uint16_t op_index);
  void commitStreamState(const FrameStream &stream);
  bool parkActiveAdcs();

  void applyVrefRange();
  bool adcSelected(uint8_t adc) const;
  bool adcHasRoutes(uint8_t adc) const;
  uint8_t activeAdcsOnBus(uint8_t bus) const;
  const __FlashStringHelper *arraySelectionName() const;
  const __FlashStringHelper *scanOrderName() const;
  const __FlashStringHelper *adcSequenceName() const;
  const __FlashStringHelper *spiEngineName() const;
  const __FlashStringHelper *vrefRangeName() const;

  Ads7953Adc **adcs_;
  uint8_t adc_count_;
  UsbSerialController &usb_;
  AdcRoute routes_[testboard_config::kMaxAdcRoutes];
  uint8_t route_count_ = 0;
  ArraySelection array_selection_ = ARRAY_BOTH;
  ScanOrder scan_order_ = SCAN_INTERLEAVED;
  AdcSequence adc_sequence_ = ADC_SEQUENCE_MANUAL;
  SpiEngine spi_engine_ = SPI_ENGINE_BLOCKING;
  uint32_t spi_clock_hz_ = testboard_config::kDefaultSpiClockHz;
  uint8_t channel_repeat_ = testboard_config::kDefaultChannelRepeat;
  bool vmid_between_channels_ = testboard_config::kDefaultVmidBetweenChannels;
  bool vref_range_2x_ = testboard_config::kAds7953Range2xVref;
  bool running_ = false;
  bool timed_run_ = false;
  uint32_t run_started_ms_ = 0;
  uint32_t run_duration_ms_ = 0;
  // Per-run live transport diagnostics; discarded sweeps were still acquired.
  uint32_t sampling_sweeps_ = 0, usb_frames_sent_ = 0, usb_frames_discarded_ = 0;
  uint32_t sampling_previous_start_ = 0, sampling_period_max_us_ = 0;
  uint32_t sampling_period_over_1ms_ = 0;
  uint32_t dma_start_errors_ = 0;
  uint32_t lpspi_start_errors_ = 0;
  uint32_t transfer_timeouts_ = 0;
  uint32_t returned_channel_errors_ = 0;
  uint32_t auto1_program_count_ = 0;
  uint32_t auto1_resume_count_ = 0;
  // Immutable route/manual-command plans are rebuilt once at every run start.
  AdcRoute scan_plan_[testboard_config::kMaxAdcRoutes];
  uint8_t adc_route_counts_[testboard_config::kAdcCount] = {};
  uint16_t adc_channel_masks_[testboard_config::kAdcCount] = {};
  uint8_t adc_destinations_[testboard_config::kAdcCount][testboard_config::kAdcChannels];
  SpiController *active_buses_[2] = {};
  FrameStream streams_[testboard_config::kAdcCount];
  uint16_t auto1_programmed_masks_[testboard_config::kAdcCount] = {};
  bool auto1_mask_valid_[testboard_config::kAdcCount] = {};
  bool auto1_active_parked_[testboard_config::kAdcCount] = {};
  bool sample_written_[testboard_config::kMaxAdcRoutes];
#if TESTBOARD_PROFILE
  AcquisitionProfiler profile_;
#endif
};
