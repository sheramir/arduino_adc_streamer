#include "Mg24AdcMux.h"

#include "pins_arduino.h"
#include "pinDefinitions.h"

extern "C" {
  #include "em_cmu.h"
  #include "em_gpio.h"
  #include "em_iadc.h"
}

namespace mg24_adc_mux {

namespace {

static const uint32_t kMuxSettleUs = 3;
static const bool kGroundReadAdc = true;
static const uint32_t kGroundDwellUs = 10;
static const bool kParkMuxAfterBlock = true;
static const uint32_t kParkMuxDwellUs = 0;
static const bool kComputeAvgDtUs = true;
static const uint32_t kIadcSrcClkHz = 10000000UL;
static const uint32_t kIadcAdcClkHz = 5000000UL;
static const uint16_t kWarmupSweeps = 48;
static const uint16_t kMaxRepeat = 100;

static const IADC_PosInput_t kGpioToAdcMap[64] = {
  iadcPosInputPortAPin0,  iadcPosInputPortAPin1,  iadcPosInputPortAPin2,  iadcPosInputPortAPin3,
  iadcPosInputPortAPin4,  iadcPosInputPortAPin5,  iadcPosInputPortAPin6,  iadcPosInputPortAPin7,
  iadcPosInputPortAPin8,  iadcPosInputPortAPin9,  iadcPosInputPortAPin10, iadcPosInputPortAPin11,
  iadcPosInputPortAPin12, iadcPosInputPortAPin13, iadcPosInputPortAPin14, iadcPosInputPortAPin15,
  iadcPosInputPortBPin0,  iadcPosInputPortBPin1,  iadcPosInputPortBPin2,  iadcPosInputPortBPin3,
  iadcPosInputPortBPin4,  iadcPosInputPortBPin5,  iadcPosInputPortBPin6,  iadcPosInputPortBPin7,
  iadcPosInputPortBPin8,  iadcPosInputPortBPin9,  iadcPosInputPortBPin10, iadcPosInputPortBPin11,
  iadcPosInputPortBPin12, iadcPosInputPortBPin13, iadcPosInputPortBPin14, iadcPosInputPortBPin15,
  iadcPosInputPortCPin0,  iadcPosInputPortCPin1,  iadcPosInputPortCPin2,  iadcPosInputPortCPin3,
  iadcPosInputPortCPin4,  iadcPosInputPortCPin5,  iadcPosInputPortCPin6,  iadcPosInputPortCPin7,
  iadcPosInputPortCPin8,  iadcPosInputPortCPin9,  iadcPosInputPortCPin10, iadcPosInputPortCPin11,
  iadcPosInputPortCPin12, iadcPosInputPortCPin13, iadcPosInputPortCPin14, iadcPosInputPortCPin15,
  iadcPosInputPortDPin0,  iadcPosInputPortDPin1,  iadcPosInputPortDPin2,  iadcPosInputPortDPin3,
  iadcPosInputPortDPin4,  iadcPosInputPortDPin5,  iadcPosInputPortDPin6,  iadcPosInputPortDPin7,
  iadcPosInputPortDPin8,  iadcPosInputPortDPin9,  iadcPosInputPortDPin10, iadcPosInputPortDPin11,
  iadcPosInputPortDPin12, iadcPosInputPortDPin13, iadcPosInputPortDPin14, iadcPosInputPortDPin15
};

static IADC_PosInput_t g_mux1_pos;
static IADC_PosInput_t g_mux2_pos;

static bool hasRequiredPins(const Pins &pins) {
  return pins.adc_mux1 >= 0 &&
         pins.adc_mux2 >= 0 &&
         pins.mux_a0 >= 0 &&
         pins.mux_a1 >= 0 &&
         pins.mux_a2 >= 0 &&
         pins.mux_a3 >= 0;
}

static void allocateAnalogBus(PinName pin_name) {
  const bool even = (((uint32_t)pin_name) % 2u) == 0u;

  if (pin_name >= PC0) {
    if (even) {
      GPIO->CDBUSALLOC |= GPIO_CDBUSALLOC_CDEVEN0_ADC0;
    } else {
      GPIO->CDBUSALLOC |= GPIO_CDBUSALLOC_CDODD0_ADC0;
    }
  } else if (pin_name >= PB0) {
    if (even) {
      GPIO->BBUSALLOC |= GPIO_BBUSALLOC_BEVEN0_ADC0;
    } else {
      GPIO->BBUSALLOC |= GPIO_BBUSALLOC_BODD0_ADC0;
    }
  } else {
    if (even) {
      GPIO->ABUSALLOC |= GPIO_ABUSALLOC_AEVEN0_ADC0;
    } else {
      GPIO->ABUSALLOC |= GPIO_ABUSALLOC_AODD0_ADC0;
    }
  }
}

static void clampSweepsPerBlock(Runtime &rt) {
  const uint32_t pairs_per_sweep = static_cast<uint32_t>(rt.cfg.channel_count) * rt.cfg.repeat_count;
  if (pairs_per_sweep == 0) {
    return;
  }

  uint32_t max_sweeps = mg24_proto::kMaxPairs / pairs_per_sweep;
  if (max_sweeps == 0) {
    max_sweeps = 1;
  }
  if (rt.cfg.sweeps_per_block > max_sweeps) {
    rt.cfg.sweeps_per_block = static_cast<uint16_t>(max_sweeps);
  }
  if (rt.cfg.sweeps_per_block == 0) {
    rt.cfg.sweeps_per_block = 1;
  }
}

static void muxSelect(Runtime &rt, uint8_t ch) {
  if (rt.last_mux_ch == ch) {
    return;
  }

  digitalWrite(rt.pins.mux_a0, (ch & 0x01) ? HIGH : LOW);
  digitalWrite(rt.pins.mux_a1, (ch & 0x02) ? HIGH : LOW);
  digitalWrite(rt.pins.mux_a2, (ch & 0x04) ? HIGH : LOW);
  digitalWrite(rt.pins.mux_a3, (ch & 0x08) ? HIGH : LOW);
  if (kMuxSettleUs > 0) {
    delayMicroseconds(kMuxSettleUs);
  }
  rt.last_mux_ch = ch;
}

static void iadcFlushFifo() {
  while (IADC_getScanFifoCnt(IADC0) > 0) {
    (void)IADC_pullScanFifoResult(IADC0);
  }
}

static bool iadcReadPairFast(uint16_t &v1, uint16_t &v2) {
  IADC_command(IADC0, iadcCmdStartScan);
  while (IADC_getScanFifoCnt(IADC0) < 2) {
  }

  const IADC_Result_t r0 = IADC_pullScanFifoResult(IADC0);
  const IADC_Result_t r1 = IADC_pullScanFifoResult(IADC0);
  v1 = r0.data & 0x0FFF;
  v2 = r1.data & 0x0FFF;
  return true;
}

static void groundStepIfNeeded(Runtime &rt) {
  if (!rt.cfg.ground_enable) {
    return;
  }

  muxSelect(rt, rt.cfg.ground_pin);
  if (kGroundReadAdc) {
    uint16_t d1 = 0;
    uint16_t d2 = 0;
    iadcReadPairFast(d1, d2);
  } else if (kGroundDwellUs > 0) {
    delayMicroseconds(kGroundDwellUs);
  }
}

static void parkMuxOnGround(Runtime &rt) {
  if (!kParkMuxAfterBlock) {
    return;
  }

  muxSelect(rt, rt.cfg.ground_pin);
  if (kParkMuxDwellUs > 0) {
    delayMicroseconds(kParkMuxDwellUs);
  }
}

static void initIadc(Runtime &rt) {
  rt.iadc_ready = false;

  const PinName n1 = pinToPinName(rt.pins.adc_mux1);
  const PinName n2 = pinToPinName(rt.pins.adc_mux2);
  if (n1 == PIN_NAME_NC || n2 == PIN_NAME_NC) {
    Serial.println(F("# ERROR: ADC pins not valid"));
    return;
  }

  CMU_ClockEnable(cmuClock_GPIO, true);
  CMU_ClockEnable(cmuClock_IADC0, true);

  g_mux1_pos = kGpioToAdcMap[(uint32_t)n1 - (uint32_t)PIN_NAME_MIN];
  g_mux2_pos = kGpioToAdcMap[(uint32_t)n2 - (uint32_t)PIN_NAME_MIN];
  allocateAnalogBus(n1);
  allocateAnalogBus(n2);

  IADC_Init_t init = IADC_INIT_DEFAULT;
  IADC_AllConfigs_t all_configs = IADC_ALLCONFIGS_DEFAULT;

  init.warmup = iadcWarmupNormal;
  init.srcClkPrescale = IADC_calcSrcClkPrescale(IADC0, kIadcSrcClkHz, 0);

  all_configs.configs[0].reference = (rt.cfg.ref == 0) ? iadcCfgReferenceInt1V2 : iadcCfgReferenceVddx;
  all_configs.configs[0].vRef = (rt.cfg.ref == 0) ? 1200 : 3300;

  if (rt.cfg.osr == 8) {
    all_configs.configs[0].osrHighSpeed = iadcCfgOsrHighSpeed8x;
  } else if (rt.cfg.osr == 4) {
    all_configs.configs[0].osrHighSpeed = iadcCfgOsrHighSpeed4x;
  } else {
    all_configs.configs[0].osrHighSpeed = iadcCfgOsrHighSpeed2x;
  }

  if (rt.cfg.gain == 4) {
    all_configs.configs[0].analogGain = iadcCfgAnalogGain4x;
  } else if (rt.cfg.gain == 3) {
    all_configs.configs[0].analogGain = iadcCfgAnalogGain3x;
  } else if (rt.cfg.gain == 2) {
    all_configs.configs[0].analogGain = iadcCfgAnalogGain2x;
  } else {
    all_configs.configs[0].analogGain = iadcCfgAnalogGain1x;
  }

  all_configs.configs[0].adcClkPrescale =
      IADC_calcAdcClkPrescale(IADC0, kIadcAdcClkHz, 0, iadcCfgModeNormal, init.srcClkPrescale);

  IADC_reset(IADC0);
  IADC_init(IADC0, &init, &all_configs);

  IADC_InitScan_t init_scan = IADC_INITSCAN_DEFAULT;
  IADC_ScanTable_t scan_table = IADC_SCANTABLE_DEFAULT;

  init_scan.alignment = iadcAlignRight12;
  init_scan.dataValidLevel = iadcFifoCfgDvl1;
  init_scan.triggerSelect = iadcTriggerSelImmediate;
  init_scan.triggerAction = iadcTriggerActionOnce;
  init_scan.start = false;

  scan_table.entries[0].posInput = g_mux1_pos;
  scan_table.entries[0].negInput = iadcNegInputGnd;
  scan_table.entries[0].configId = 0;
  scan_table.entries[0].includeInScan = true;

  scan_table.entries[1].posInput = g_mux2_pos;
  scan_table.entries[1].negInput = iadcNegInputGnd;
  scan_table.entries[1].configId = 0;
  scan_table.entries[1].includeInScan = true;

  IADC_initScan(IADC0, &init_scan, &scan_table);
  IADC_clearInt(IADC0, _IADC_IF_MASK);
  iadcFlushFifo();

  rt.iadc_ready = true;
  rt.config_dirty = false;
}

static void doWarmup(Runtime &rt) {
  if (!rt.iadc_ready || rt.cfg.channel_count == 0) {
    return;
  }

  rt.last_mux_ch = 0xFF;
  iadcFlushFifo();

  for (uint16_t sw = 0; sw < kWarmupSweeps; ++sw) {
    uint8_t prev_ch = 0xFF;
    for (uint8_t i = 0; i < rt.cfg.channel_count; ++i) {
      const uint8_t ch = rt.cfg.channels[i];
      const bool is_new_channel = (i == 0) || (ch != prev_ch);
      if (is_new_channel) {
        groundStepIfNeeded(rt);
      }
      muxSelect(rt, ch);
      for (uint16_t r = 0; r < rt.cfg.repeat_count; ++r) {
        uint16_t d1 = 0;
        uint16_t d2 = 0;
        iadcReadPairFast(d1, d2);
      }
      prev_ch = ch;
    }
  }

  parkMuxOnGround(rt);
}

}  // namespace

void begin(Runtime &rt, const Pins &pins) {
  rt.pins = pins;
  rt.iadc_ready = false;
  rt.config_dirty = true;
  rt.last_mux_ch = 0xFF;

  if (!hasRequiredPins(rt.pins)) {
    Serial.println(F("# ERROR: MG24 ADC pins not configured in sketch"));
    return;
  }

  pinMode(rt.pins.mux_a0, OUTPUT);
  digitalWrite(rt.pins.mux_a0, LOW);
  pinMode(rt.pins.mux_a1, OUTPUT);
  digitalWrite(rt.pins.mux_a1, LOW);
  pinMode(rt.pins.mux_a2, OUTPUT);
  digitalWrite(rt.pins.mux_a2, LOW);
  pinMode(rt.pins.mux_a3, OUTPUT);
  digitalWrite(rt.pins.mux_a3, LOW);

  pinMode(rt.pins.adc_mux1, INPUT);
  pinMode(rt.pins.adc_mux2, INPUT);

  clampSweepsPerBlock(rt);
  parkMuxOnGround(rt);
}

bool setChannels(Runtime &rt, const uint8_t *channels, uint8_t count) {
  if (channels == nullptr || count == 0 || count > 16) {
    return false;
  }

  for (uint8_t i = 0; i < count; ++i) {
    if (channels[i] > 15) {
      return false;
    }
    rt.cfg.channels[i] = channels[i];
  }

  rt.cfg.channel_count = count;
  clampSweepsPerBlock(rt);
  return true;
}

void setRepeat(Runtime &rt, uint8_t repeat_count) {
  rt.cfg.repeat_count = max<uint16_t>(1, min<uint16_t>(repeat_count, kMaxRepeat));
  clampSweepsPerBlock(rt);
}

void setBuffer(Runtime &rt, uint8_t sweeps_per_block) {
  rt.cfg.sweeps_per_block = max<uint16_t>(1, sweeps_per_block);
  clampSweepsPerBlock(rt);
}

bool setReference(Runtime &rt, uint8_t ref) {
  if (ref > 1) {
    return false;
  }
  rt.cfg.ref = ref;
  rt.config_dirty = true;
  return true;
}

bool setOsr(Runtime &rt, uint8_t osr) {
  if (osr != 2 && osr != 4 && osr != 8) {
    return false;
  }
  rt.cfg.osr = osr;
  rt.config_dirty = true;
  return true;
}

bool setGain(Runtime &rt, uint8_t gain) {
  if (gain < 1 || gain > 4) {
    return false;
  }
  rt.cfg.gain = gain;
  rt.config_dirty = true;
  return true;
}

bool setGroundPin(Runtime &rt, uint8_t ground_pin) {
  if (ground_pin > 15) {
    return false;
  }
  rt.cfg.ground_pin = ground_pin;
  rt.cfg.ground_enable = true;
  return true;
}

void setGroundEnabled(Runtime &rt, bool enabled) {
  rt.cfg.ground_enable = enabled;
}

bool startRun(Runtime &rt, const uint8_t *args, uint8_t nargs) {
  if (rt.cfg.channel_count == 0) {
    return false;
  }

  if (rt.config_dirty) {
    initIadc(rt);
  }
  if (!rt.iadc_ready) {
    return false;
  }

  if (nargs == 4 && args != nullptr) {
    const uint32_t run_ms = ((uint32_t)args[0]) |
                            ((uint32_t)args[1] << 8) |
                            ((uint32_t)args[2] << 16) |
                            ((uint32_t)args[3] << 24);
    rt.cfg.timed_run = (run_ms > 0);
    if (rt.cfg.timed_run) {
      rt.cfg.run_stop_ms = millis() + run_ms;
    }
  } else {
    rt.cfg.timed_run = false;
  }

  rt.cfg.running = true;
  doWarmup(rt);
  return true;
}

uint16_t fillInterleavedBlock(Runtime &rt) {
  if (!rt.iadc_ready || rt.cfg.channel_count == 0) {
    return 0;
  }

  const uint32_t max_pairs_configured = static_cast<uint32_t>(rt.cfg.sweeps_per_block) *
                                        static_cast<uint32_t>(rt.cfg.channel_count) *
                                        static_cast<uint32_t>(rt.cfg.repeat_count);
  const uint32_t max_pairs = (max_pairs_configured > mg24_proto::kMaxPairs) ? mg24_proto::kMaxPairs : max_pairs_configured;

  uint32_t pair_idx = 0;
  uint16_t sample_idx = 0;

  rt.last_block_start_us = micros();
  rt.last_mux_ch = 0xFF;
  iadcFlushFifo();

  for (uint16_t sw = 0; sw < rt.cfg.sweeps_per_block && pair_idx < max_pairs; ++sw) {
    uint8_t prev_ch = 0xFF;
    for (uint8_t i = 0; i < rt.cfg.channel_count && pair_idx < max_pairs; ++i) {
      const uint8_t ch = rt.cfg.channels[i];
      const bool is_new_channel = (i == 0) || (ch != prev_ch);
      if (is_new_channel) {
        groundStepIfNeeded(rt);
      }

      muxSelect(rt, ch);
      for (uint16_t r = 0; r < rt.cfg.repeat_count && pair_idx < max_pairs; ++r) {
        uint16_t v1 = 0;
        uint16_t v2 = 0;
        iadcReadPairFast(v1, v2);
        rt.sample_buf[sample_idx++] = v1;
        rt.sample_buf[sample_idx++] = v2;
        ++pair_idx;
      }
      prev_ch = ch;
    }
  }

  rt.last_block_end_us = micros();
  parkMuxOnGround(rt);

  if (kComputeAvgDtUs && sample_idx > 0) {
    const uint32_t elapsed = rt.last_block_end_us - rt.last_block_start_us;
    rt.last_avg_dt_us = static_cast<uint16_t>(min(elapsed / sample_idx, 65535UL));
  } else {
    rt.last_avg_dt_us = 0;
  }

  return sample_idx;
}

bool streamExpired(Runtime &rt) {
  if (rt.cfg.timed_run && (int32_t)(millis() - rt.cfg.run_stop_ms) >= 0) {
    stopRun(rt);
    return true;
  }
  return false;
}

void stopRun(Runtime &rt) {
  rt.cfg.running = false;
  rt.cfg.timed_run = false;
  parkMuxOnGround(rt);
}

bool isStreaming(const Runtime &rt) {
  return rt.cfg.running && rt.iadc_ready && rt.cfg.channel_count > 0;
}

uint32_t blockResponseBytes(const Runtime &rt) {
  const uint32_t samples = static_cast<uint32_t>(rt.cfg.channel_count) *
                           static_cast<uint32_t>(rt.cfg.repeat_count) *
                           static_cast<uint32_t>(rt.cfg.sweeps_per_block) * 2u;
  return mg24_proto::kAckFrameLen + samples * sizeof(uint16_t) + mg24_proto::kBlockTrailerLen;
}

}  // namespace mg24_adc_mux
