/*
 * High-speed IADC Binary Sweeper with Blocked Output — XIAO MG24
 * --------------------------------------------------------------
 *
 * Core behavior (same protocol as before):
 *   - Configure channels with:
 *       channels 0,1,1,1,2,2,3,4,5*
 *
 *   - Configure repeats per channel with:
 *       repeat N*
 *
 *     One "sweep" (on the PC side) is an ordered list:
 *       [ch0_r1, ch0_r2, ... ch0_rN, ch1_r1, ... chLast_rN]
 *
 *   - Configure how many sweeps to accumulate before sending:
 *       buffer B*
 *     Each block has (B * samplesPerSweep) samples.
 *
 *   - Blocks are sent as binary:
 *       [0xAA][0x55][countL][countH] + count * uint16 + avg_dt_us(uint16) + block_start_us(uint32) + block_end_us(uint32)
 *
 *   - The average time per sample (µs) is measured only for the
 *     ADC CAPTURE time, not including serial printing.
 *
 * High-speed ADC configuration:
 *   - ref 1.2*        -> use 1.2V internal reference
 *   - ref 3.3*        -> use VDD ~3.3V as reference
 *   - ref vdd*        -> same as 3.3
 *   - osr 2|4|8*      -> high-speed oversampling
 *   - gain 1|2|3|4*   -> analog gain multiplier
 *
 * Ground dummy behavior:
 *   - ground 2*          -> set groundPin = 2
 *   - ground true*       -> enable ground dummy reads
 *   - ground false*      -> disable ground dummy reads
 *
 *   When ground is enabled, the IADC scan pattern becomes:
 *
 *      [G,ch0_r1..ch0_rN, G,ch1_r1..ch1_rN, ...]
 *
 *   where G = one sample from groundPin, and:
 *     - A "new channel" is the first occurrence of a channel after
 *       a different one in channelSequence[]; adjacent duplicates
 *       share the same G before the first of them.
 *     - Ground samples are used ONLY inside the MCU and are NOT
 *       sent to the PC. The PC still sees:
 *
 *         samplesPerSweep = channelCount * repeatCount
 *
 *   NOTE: ref 0.8vdd / ref ext from the old sketch are NOT supported
 *         here and will return an error.
 *
 * Commands (terminated by '*'):
 *
 *   channels 0,1,1,1,2,2,3,4,5*
 *   ground 2*
 *   ground true*
 *   ground false*
 *   repeat 20*
 *   buffer 10*
 *   ref 1.2*
 *   ref 3.3*
 *   ref vdd*
 *   osr 2*
 *   osr 4*
 *   osr 8*
 *   gain 1*
 *   gain 2*
 *   gain 3*
 *   gain 4*
 *   run*
 *   run 100*
 *   stop*
 *   status*
 *   help*
 */

#include <Arduino.h>
#include "pins_arduino.h"
#include "pinDefinitions.h"

extern "C" {
  #include "em_cmu.h"
  #include "em_gpio.h"
  #include "em_iadc.h"
}

// ---------------------------------------------------------------------
// Limits & defaults
// ---------------------------------------------------------------------

const uint8_t  MAX_SEQUENCE_LEN   = 16;     // Maximum number of channels in a sequence
const uint32_t BAUD_RATE          = 460800; // High-speed baud

// Max samples in RAM buffer (each sample = uint16_t)
const uint32_t MAX_SAMPLES_BUFFER = 32000;  // 32000 * 2bytes = 64kB

// MG24 IADC scan table entry limit (HARDWARE LIMIT).
// Do NOT set this above the number of SCAN table entries supported
// by the IADC (e.g. 16).
const uint8_t  MAX_SCAN_ENTRIES   = 16;

// ---------------------------------------------------------------------
// Command framing constants
// ---------------------------------------------------------------------

static const char     CMD_TERMINATOR   = '*';    // '*' ends a command
static const uint16_t MAX_CMD_LENGTH   = 512;    // Max input line length

// ---------------------------------------------------------------------
// IADC clock configuration (user-tunable)
// ---------------------------------------------------------------------
//
// You can change these two constants to try different speeds.
//
// Examples (check MG24 datasheet for absolute max values!):
//   - IADC_SRC_CLK_TARGET_HZ: 20000000, 40000000
//   - IADC_ADC_CLK_TARGET_HZ:  5000000, 10000000, 20000000
//
// Faster ADC clock  -> shorter conversion time, higher throughput, more noise.
// Slower ADC clock  -> longer conversion, lower throughput, better SNR.
//
const uint32_t IADC_SRC_CLK_TARGET_HZ = 20000000UL;  // was fixed at 20 MHz
const uint32_t IADC_ADC_CLK_TARGET_HZ = 10000000UL;  // was fixed at 10 MHz

// ---------------------------------------------------------------------
// Warm-up sweeps before real data capture
// ---------------------------------------------------------------------
// The ADC + reference + decimation filters may need a short settling period.
// This number defines how many full sweeps are captured & discarded
// immediately after "run*" starts.
// Tune as needed (e.g., 16, 32, 48, 64).
const uint16_t IADC_WARMUP_SWEEPS = 48;


// ---------------------------------------------------------------------
// Configuration state
// ---------------------------------------------------------------------

uint8_t  channelSequence[MAX_SEQUENCE_LEN]; // user-chosen pins in sweep
uint8_t  channelCount        = 0;           // how many channels in sequence

// Ground configuration:
// - Default ground pin is D0 (0).
// - Default behavior: ground dummy reads disabled (useGroundBeforeEach=false).
int   groundPin              = 0;
bool  useGroundBeforeEach    = false;

// repeatCount = number of readings per channel per sweep (sent to PC)
uint16_t repeatCount         = 1;

// Maximum repeat count we support at API level (trimmed if scan table too small)
const uint16_t MAX_REPEAT_COUNT = 100;

// ADC sample buffer for multiple sweeps (flattened, only NON-ground samples)
uint16_t adcBuffer[MAX_SAMPLES_BUFFER];

// Derived config values
uint16_t samplesPerSweep       = 0;  // number of samples actually SENT per sweep (no ground)
uint16_t scanEntriesPerSweep   = 0;  // number of IADC scan entries per sweep (including ground entries)

// For each scan entry, track whether it's a ground read or channel read
bool isGroundEntry[MAX_SCAN_ENTRIES];  // true = ground sample, false = channel sample

// Blocked/buffered sweeps:
uint16_t sweepsPerBlock        = 1;  // how many sweeps per block

// ---------------------------------------------------------------------
// High-speed IADC configuration state (runtime adjustable)
// ---------------------------------------------------------------------

analog_references currentRef = AR_VDD; // for status only

static uint32_t            g_vref_mV   = 3300;
static IADC_CfgReference_t g_vref_sel  = iadcCfgReferenceVddx;

static IADC_CfgOsrHighSpeed_t g_osr_hs = iadcCfgOsrHighSpeed2x;
static IADC_CfgAnalogGain_t   g_gain   = iadcCfgAnalogGain1x;

// Flag to re-init IADC after any config / channel / repeat change
static bool g_configDirty = true;

// ---------------------------------------------------------------------
// Run state
// ---------------------------------------------------------------------

bool     isRunning           = false;
bool     timedRun            = false;
uint32_t runStopMillis       = 0;

// ---------------------------------------------------------------------
// Serial input buffer
// ---------------------------------------------------------------------

String   inputLine;

// ---------------------------------------------------------------------
// Timing measurement: block timing
// ---------------------------------------------------------------------

uint32_t blockStartMicros = 0;  // micros() when first sample of block is taken

// ---------------------------------------------------------------------
// Local GPIO→IADC map (from core, copied locally)
// ---------------------------------------------------------------------

static const IADC_PosInput_t GPIO_to_ADC_pin_map_local[64] = {
  // Port A
  iadcPosInputPortAPin0,
  iadcPosInputPortAPin1,
  iadcPosInputPortAPin2,
  iadcPosInputPortAPin3,
  iadcPosInputPortAPin4,
  iadcPosInputPortAPin5,
  iadcPosInputPortAPin6,
  iadcPosInputPortAPin7,
  iadcPosInputPortAPin8,
  iadcPosInputPortAPin9,
  iadcPosInputPortAPin10,
  iadcPosInputPortAPin11,
  iadcPosInputPortAPin12,
  iadcPosInputPortAPin13,
  iadcPosInputPortAPin14,
  iadcPosInputPortAPin15,
  // Port B
  iadcPosInputPortBPin0,
  iadcPosInputPortBPin1,
  iadcPosInputPortBPin2,
  iadcPosInputPortBPin3,
  iadcPosInputPortBPin4,
  iadcPosInputPortBPin5,
  iadcPosInputPortBPin6,
  iadcPosInputPortBPin7,
  iadcPosInputPortBPin8,
  iadcPosInputPortBPin9,
  iadcPosInputPortBPin10,
  iadcPosInputPortBPin11,
  iadcPosInputPortBPin12,
  iadcPosInputPortBPin13,
  iadcPosInputPortBPin14,
  iadcPosInputPortBPin15,
  // Port C
  iadcPosInputPortCPin0,
  iadcPosInputPortCPin1,
  iadcPosInputPortCPin2,
  iadcPosInputPortCPin3,
  iadcPosInputPortCPin4,
  iadcPosInputPortCPin5,
  iadcPosInputPortCPin6,
  iadcPosInputPortCPin7,
  iadcPosInputPortCPin8,
  iadcPosInputPortCPin9,
  iadcPosInputPortCPin10,
  iadcPosInputPortCPin11,
  iadcPosInputPortCPin12,
  iadcPosInputPortCPin13,
  iadcPosInputPortCPin14,
  iadcPosInputPortCPin15,
  // Port D
  iadcPosInputPortDPin0,
  iadcPosInputPortDPin1,
  iadcPosInputPortDPin2,
  iadcPosInputPortDPin3,
  iadcPosInputPortDPin4,
  iadcPosInputPortDPin5,
  iadcPosInputPortDPin6,
  iadcPosInputPortDPin7,
  iadcPosInputPortDPin8,
  iadcPosInputPortDPin9,
  iadcPosInputPortDPin10,
  iadcPosInputPortDPin11,
  iadcPosInputPortDPin12,
  iadcPosInputPortDPin13,
  iadcPosInputPortDPin14,
  iadcPosInputPortDPin15
};

static void allocateAnalogBusForPin(PinName pinName) {
  bool pinIsEven = (((uint32_t)pinName) % 2u) == 0u;

  if (pinName >= PD0 || pinName >= PC0) {
    if (pinIsEven) {
      GPIO->CDBUSALLOC |= GPIO_CDBUSALLOC_CDEVEN0_ADC0;
    } else {
      GPIO->CDBUSALLOC |= GPIO_CDBUSALLOC_CDODD0_ADC0;
    }
  } else if (pinName >= PB0) {
    if (pinIsEven) {
      GPIO->BBUSALLOC |= GPIO_BBUSALLOC_BEVEN0_ADC0;
    } else {
      GPIO->BBUSALLOC |= GPIO_BBUSALLOC_BODD0_ADC0;
    }
  } else {
    if (pinIsEven) {
      GPIO->ABUSALLOC |= GPIO_ABUSALLOC_AEVEN0_ADC0;
    } else {
      GPIO->ABUSALLOC |= GPIO_ABUSALLOC_AODD0_ADC0;
    }
  }
}

// ---------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------

String toLowerTrim(const String &s) {
  String t = s;
  t.trim();
  t.toLowerCase();
  return t;
}

void splitCommand(const String &line, String &cmd, String &args) {
  int idx = line.indexOf(' ');
  if (idx < 0) {
    cmd  = line;
    args = "";
  } else {
    cmd  = line.substring(0, idx);
    args = line.substring(idx + 1);
  }
  cmd.trim();
  args.trim();
}

// Dummy-read placeholder (no analogRead here to avoid fighting IADC config)
void doDummyRead() {
  delayMicroseconds(10);
}

// ---------------------------------------------------------------------
// Command acknowledgment helper
// ---------------------------------------------------------------------
void sendCommandAck(bool ok, const String &args) {

  if (ok) {
    if (args.length() > 0) {
      Serial.print(F("#OK "));
      Serial.println(args);
    } else {
      Serial.println(F("#OK"));
    }
  } else {
    if (args.length() > 0) {
      Serial.print(F("#NOT_OK "));
      Serial.println(args);
    } else {
      Serial.println(F("#NOT_OK"));
    }
  }

  Serial.flush();
  delay(5);
}

// ---------------------------------------------------------------------
// Helper: calculate how many IADC scan entries per sweep
// (including ground entries, if enabled)
// ---------------------------------------------------------------------
uint16_t calcScanEntryCount(uint16_t rep) {
  if (channelCount == 0) return 0;

  uint16_t total      = 0;
  int      prevChan   = -1;
  bool     haveGround = useGroundBeforeEach;

  for (uint8_t i = 0; i < channelCount; ++i) {
    uint8_t chan  = channelSequence[i];
    bool    isNew = (i == 0) || (chan != prevChan);

    if (haveGround && isNew) {
      // One ground sample before this "new" channel
      total += 1;
    }

    // rep samples for this channel
    total += rep;
    prevChan = chan;
  }

  return total;
}

// ---------------------------------------------------------------------
// Derived configuration recomputation
// Returns true if configuration is valid, false if it exceeds hardware limits
// ---------------------------------------------------------------------
bool recomputeDerivedConfig() {
  if (channelCount == 0) {
    samplesPerSweep      = 0;
    scanEntriesPerSweep  = 0;
    sweepsPerBlock       = 1;
    g_configDirty        = true;
    return true;  // "empty" config is valid, just does nothing
  }

  // First, compute scan entries for current repeatCount and ground setting
  uint16_t scanEntries = calcScanEntryCount(repeatCount);

  // HARD LIMIT: IADC scan table entries per sweep
  if (scanEntries > MAX_SCAN_ENTRIES) {
    Serial.print(F("# ERROR: total scan entries per sweep ("));
    Serial.print(scanEntries);
    Serial.print(F(") exceeds hardware limit of "));
    Serial.print(MAX_SCAN_ENTRIES);
    Serial.println(F(". Reduce channels, repeat, or disable ground."));

    // Mark as invalid so capturing won't run
    samplesPerSweep      = 0;
    scanEntriesPerSweep  = 0;
    sweepsPerBlock       = 1;
    g_configDirty        = true;
    return false;
  }

  // Number of IADC entries per sweep (ground + channels)
  scanEntriesPerSweep = scanEntries;

  // Number of samples we actually SEND per sweep (channels only)
  samplesPerSweep = (uint16_t)channelCount * (uint16_t)repeatCount;

  if (samplesPerSweep == 0) {
    sweepsPerBlock       = 1;
  } else {
    // Ensure sweepsPerBlock fits into adcBuffer (we store only non-ground samples)
    uint32_t maxSweepsByBuffer = MAX_SAMPLES_BUFFER / (uint32_t)samplesPerSweep;
    if (maxSweepsByBuffer == 0) {
      maxSweepsByBuffer = 1;
    }

    if (sweepsPerBlock == 0) {
      sweepsPerBlock = 1;
    }
    if (sweepsPerBlock > maxSweepsByBuffer) {
      sweepsPerBlock = (uint16_t)maxSweepsByBuffer;
    }
  }

  g_configDirty = true;
  return true;
}


// ---------------------------------------------------------------------
// Binary sweep/block output helpers
// ---------------------------------------------------------------------

const uint8_t SWEEP_MAGIC1 = 0xAA;
const uint8_t SWEEP_MAGIC2 = 0x55;

void sendSweepHeader(uint16_t totalSamples) {
  uint8_t header[4];
  header[0] = SWEEP_MAGIC1;
  header[1] = SWEEP_MAGIC2;
  header[2] = (uint8_t)(totalSamples & 0xFF);
  header[3] = (uint8_t)(totalSamples >> 8);
  Serial.write(header, 4);
}

void sendBlock(uint16_t sampleCount, uint32_t blockStartUs, uint32_t blockEndUs) {
  if (sampleCount == 0) return;

  uint32_t totalSamples = sampleCount;
  if (totalSamples > MAX_SAMPLES_BUFFER) {
    totalSamples = MAX_SAMPLES_BUFFER;
  }

  uint32_t totalTimeUs = blockEndUs - blockStartUs;  // wrap-safe unsigned math
  uint32_t avgSampleDtUs = (totalSamples > 0) ? (totalTimeUs / totalSamples) : 0;

  uint16_t avgSampleDtUs16 = (avgSampleDtUs <= 65535u)
                               ? (uint16_t)avgSampleDtUs
                               : (uint16_t)65535u;

  // Header
  sendSweepHeader((uint16_t)totalSamples);

  // Samples (channels only, already filtered)
  Serial.write((uint8_t*)adcBuffer, (size_t)(totalSamples * sizeof(uint16_t)));

  // Average per-sample time (us)
  uint8_t rateBytes[2];
  rateBytes[0] = (uint8_t)(avgSampleDtUs16 & 0xFF);
  rateBytes[1] = (uint8_t)(avgSampleDtUs16 >> 8);
  Serial.write(rateBytes, 2);

  // Append block start/end micros (uint32 LE each) for host-side timing
  uint8_t tsBytes[8];
  tsBytes[0] = (uint8_t)(blockStartUs & 0xFF);
  tsBytes[1] = (uint8_t)((blockStartUs >> 8) & 0xFF);
  tsBytes[2] = (uint8_t)((blockStartUs >> 16) & 0xFF);
  tsBytes[3] = (uint8_t)((blockStartUs >> 24) & 0xFF);
  tsBytes[4] = (uint8_t)(blockEndUs & 0xFF);
  tsBytes[5] = (uint8_t)((blockEndUs >> 8) & 0xFF);
  tsBytes[6] = (uint8_t)((blockEndUs >> 16) & 0xFF);
  tsBytes[7] = (uint8_t)((blockEndUs >> 24) & 0xFF);
  Serial.write(tsBytes, 8);
}

// ---------------------------------------------------------------------
// IADC init: uses current globals (ref/osr/gain + channels/repeat/ground)
// ---------------------------------------------------------------------

static void initIADC_ScanMultiChannel() {
  if (channelCount == 0 || samplesPerSweep == 0) {
    g_configDirty = false;
    return;
  }

  // Set all channel pins as input
  for (uint8_t i = 0; i < channelCount; ++i) {
    pinMode(channelSequence[i], INPUT);
  }
  // Ground pin as input if ground dummy reads are enabled
  if (useGroundBeforeEach) {
    pinMode(groundPin, INPUT);
  }

  // Enable clocks
  CMU_ClockEnable(cmuClock_IADC0, true);
  CMU_ClockEnable(cmuClock_GPIO, true);
  CMU_ClockEnable(cmuClock_PRS,  true);

  IADC_Init_t        init       = IADC_INIT_DEFAULT;
  IADC_AllConfigs_t  allConfigs = IADC_ALLCONFIGS_DEFAULT;
  IADC_InitScan_t    initScan   = IADC_INITSCAN_DEFAULT;
  IADC_ScanTable_t   scanTable  = IADC_SCANTABLE_DEFAULT;

  // Global config
  init.warmup         = iadcWarmupNormal;
  init.srcClkPrescale = IADC_calcSrcClkPrescale(IADC0, IADC_SRC_CLK_TARGET_HZ, 0);  // SRC ≈ 20 MHz

  // Config 0: reference, OSR, gain
  allConfigs.configs[0].reference    = g_vref_sel;
  allConfigs.configs[0].vRef         = g_vref_mV;
  allConfigs.configs[0].osrHighSpeed = g_osr_hs;
  allConfigs.configs[0].analogGain   = g_gain;

  // Target ADC clock ~10 MHz
  allConfigs.configs[0].adcClkPrescale =
      IADC_calcAdcClkPrescale(IADC0,
                              IADC_ADC_CLK_TARGET_HZ,
                              0,
                              iadcCfgModeNormal,
                              init.srcClkPrescale);

  // Apply core IADC config
  IADC_reset(IADC0);
  IADC_init(IADC0, &init, &allConfigs);

  // Scan settings — trigger IMMEDIATE, ACTION ONCE
  initScan.alignment      = iadcAlignRight12;
  initScan.showId         = true;
  initScan.dataValidLevel = iadcFifoCfgDvl1;
  initScan.fifoDmaWakeup  = false;
  initScan.triggerSelect  = iadcTriggerSelImmediate;
  initScan.triggerAction  = iadcTriggerActionOnce;
  initScan.start          = false;

  // Build scan table for ONE full logical sweep:
  //   For each "new" channel:
  //      [ground entry?] + repeatCount entries for that channel
  uint16_t entryIndex  = 0;
  int      prevChan    = -1;
  bool     haveGround  = useGroundBeforeEach;

  for (uint8_t i = 0; i < channelCount && entryIndex < MAX_SCAN_ENTRIES; ++i) {
    uint8_t chan  = channelSequence[i];
    bool    isNew = (i == 0) || (chan != prevChan);

    // Ground entry (if enabled) before this "new" channel
    if (haveGround && isNew && entryIndex < MAX_SCAN_ENTRIES) {
      uint8_t  gPin  = (uint8_t)groundPin;
      PinName  gName = pinToPinName(gPin);
      if (gName == PIN_NAME_NC) {
        Serial.println(F("# ERROR: groundPin is not a valid MCU pin. Disabling ground."));
        haveGround = false;   // don't try to add ground entries
      } else {
        uint32_t gIndex   = (uint32_t)gName - (uint32_t)PIN_NAME_MIN;
        IADC_PosInput_t gPos = GPIO_to_ADC_pin_map_local[gIndex];

        scanTable.entries[entryIndex].posInput      = gPos;
        scanTable.entries[entryIndex].negInput      = iadcNegInputGnd;
        scanTable.entries[entryIndex].includeInScan = true;
        scanTable.entries[entryIndex].configId      = 0;
        scanTable.entries[entryIndex].compare       = false;

        allocateAnalogBusForPin(gName);
        isGroundEntry[entryIndex] = true;
        entryIndex++;
      }
    }

    // Channel entries
    uint8_t  arduinoPin = chan;
    PinName  pinName    = pinToPinName(arduinoPin);
    if (pinName == PIN_NAME_NC) {
      Serial.print(F("# ERROR: channel pin "));
      Serial.print(arduinoPin);
      Serial.println(F(" is not a valid MCU pin. Skipping."));
      continue;
    }

    uint32_t pinIndex   = (uint32_t)pinName - (uint32_t)PIN_NAME_MIN;
    IADC_PosInput_t pos = GPIO_to_ADC_pin_map_local[pinIndex];

    for (uint16_t r = 0; r < repeatCount && entryIndex < MAX_SCAN_ENTRIES; ++r) {
      scanTable.entries[entryIndex].posInput      = pos;
      scanTable.entries[entryIndex].negInput      = iadcNegInputGnd;
      scanTable.entries[entryIndex].includeInScan = true;
      scanTable.entries[entryIndex].configId      = 0;
      scanTable.entries[entryIndex].compare       = false;

      allocateAnalogBusForPin(pinName);
      isGroundEntry[entryIndex] = false;
      entryIndex++;
    }

    prevChan = chan;
  }

  // ---- FINAL length sanity & error handling ----
  if (entryIndex == 0) {
    Serial.println(F("# ERROR: no valid IADC scan entries configured. Stopping run."));
    scanEntriesPerSweep = 0;
    samplesPerSweep     = 0;
    isRunning           = false;
    g_configDirty       = false;
    return;
  }

  // Always trust the actual number of configured entries
  scanEntriesPerSweep = entryIndex;

  // Initialize scan
  IADC_initScan(IADC0, &initScan, &scanTable);

  // Clear flags/FIFO
  IADC_clearInt(IADC0, _IADC_IF_MASK);
  while (IADC_getScanFifoCnt(IADC0) > 0) {
    (void)IADC_pullScanFifoResult(IADC0);
  }

  g_configDirty = false;
}


// ---------------------------------------------------------------------
// Perform N warm-up sweeps and discard the results.
// This lets the IADC, reference, and any digital filters settle
// before we start filling adcBuffer for the PC.
// ---------------------------------------------------------------------
void discardWarmupSweeps(uint16_t warmupSweeps) {
  if (channelCount == 0 || samplesPerSweep == 0) return;

  if (g_configDirty) {
    initIADC_ScanMultiChannel();
  }

  for (uint16_t s = 0; s < warmupSweeps; ++s) {
    // Clear SCANTABLEDONE before starting this sweep
    IADC_clearInt(IADC0, IADC_IF_SCANTABLEDONE);

    IADC_command(IADC0, iadcCmdStartScan);

    uint16_t entriesRead = 0;

    while (entriesRead < MAX_SCAN_ENTRIES) {
      uint32_t waitStart = micros();
      while (IADC_getScanFifoCnt(IADC0) == 0) {
        uint32_t flags = IADC_getInt(IADC0);
        if (flags & IADC_IF_SCANTABLEDONE) {
          // End of this warm-up sweep
          IADC_clearInt(IADC0, IADC_IF_SCANTABLEDONE);
          goto sweep_done_warmup;
        }

        if ((uint32_t)(micros() - waitStart) > 100000UL) {  // 100 ms timeout
          Serial.println(F("# ERROR: IADC warmup scan timeout."));
          return;
        }
      }

      // Pull and discard the sample
      (void)IADC_pullScanFifoResult(IADC0);
      entriesRead++;
    }

  sweep_done_warmup:
    ; // no-op; just a label target
  }
}



// ---------------------------------------------------------------------
// Capture one block into adcBuffer using IADC scan
// ---------------------------------------------------------------------

void doOneBlock() {
  if (!isRunning || channelCount == 0 || samplesPerSweep == 0) return;

  if (g_configDirty) {
    initIADC_ScanMultiChannel();
  }

  // Total SAMPLES WE WILL SEND (no ground).
  uint32_t totalSamples = (uint32_t)sweepsPerBlock * (uint32_t)samplesPerSweep;
  if (totalSamples > MAX_SAMPLES_BUFFER) {
    totalSamples = MAX_SAMPLES_BUFFER;
  }

  blockStartMicros = micros();
  uint32_t idx = 0;

  for (uint16_t s = 0; s < sweepsPerBlock; ++s) {
    // Clear SCANTABLEDONE before starting this sweep
    IADC_clearInt(IADC0, IADC_IF_SCANTABLEDONE);

    IADC_command(IADC0, iadcCmdStartScan);

    uint16_t entriesRead = 0;

    while (idx < totalSamples && entriesRead < MAX_SCAN_ENTRIES) {

      uint32_t waitStart = micros();
      while (IADC_getScanFifoCnt(IADC0) == 0) {
        // If the hardware says the scan table is done and FIFO is empty,
        // there are no more results for this sweep.
        uint32_t flags = IADC_getInt(IADC0);
        if (flags & IADC_IF_SCANTABLEDONE) {
          // Clear the flag so the next sweep starts clean
          IADC_clearInt(IADC0, IADC_IF_SCANTABLEDONE);
          goto sweep_done;
        }

        if ((uint32_t)(micros() - waitStart) > 100000UL) {  // 100 ms timeout
          Serial.println(F("# ERROR: IADC scan timeout. Stopping run."));
          isRunning = false;
          timedRun  = false;
          return;   // abort this block, go back to loop() so serial still works
        }
      }

      // We have at least one sample in FIFO
      IADC_Result_t res = IADC_pullScanFifoResult(IADC0);
      uint16_t data     = (uint16_t)(res.data & 0x0FFF); // 12-bit

      // Only store non-ground scan entries
      if (entriesRead < scanEntriesPerSweep && !isGroundEntry[entriesRead]) {
        if (idx < totalSamples) {
          adcBuffer[idx++] = data;
        }
      }

      entriesRead++;
    }

  sweep_done:
    ; // label target, nothing to do here
  }



  uint32_t blockEndMicros = micros(); // Total sampling time for block
  //blockStartMicros        = 0;   // clear here if you want to keep the global

  // Send ONLY non-ground samples
  sendBlock((uint16_t)idx, blockStartMicros, blockEndMicros);
}

// ---------------------------------------------------------------------
// Command handlers
// ---------------------------------------------------------------------

bool handleChannels(const String &args) {
  channelCount = 0;
  int len = args.length();
  int i   = 0;

  while (i < len && channelCount < MAX_SEQUENCE_LEN) {
    while (i < len && (args[i] == ' ' || args[i] == ',' || args[i] == '\t')) {
      i++;
    }
    if (i >= len) break;

    int start = i;
    while (i < len && args[i] != ' ' && args[i] != ',' && args[i] != '\t') {
      i++;
    }
    String token = args.substring(start, i);
    token.trim();
    if (token.length() == 0) continue;

    int val = token.toInt();
    if (val < 0 || val > 255) {
      Serial.println(F("# ERROR: channel out of range (0-255)"));
      continue;
    }

    channelSequence[channelCount++] = (uint8_t)val;
  }

  if (channelCount == 0) {
    Serial.println(F("# ERROR: no valid channels parsed."));
    recomputeDerivedConfig(); // just to reset derived values
    return false;
  }

  // Validate channel + repeat + ground combination
  return recomputeDerivedConfig();
}

bool handleGround(const String &args) {
  if (args.length() == 0) {
    Serial.println(F("# ERROR: ground requires an argument (pin number or true/false)"));
    return false;
  }

  String a = toLowerTrim(args);

  if (a == "true") {
    // Enable ground dummy reads; groundPin stays as current value (default 0)
    useGroundBeforeEach = true;
  } else if (a == "false") {
    useGroundBeforeEach = false;
  } else { // command specified a pin number for groundpin
    int pin = a.toInt();
    if (pin < 0 || pin > 255) {
      Serial.println(F("# ERROR: ground pin out of range (0-255)"));
      return false;
    }

    PinName pn = pinToPinName(pin);
    if (pn == PIN_NAME_NC) {
      Serial.println(F("# ERROR: ground pin is not a valid MCU pin."));
      return false;
    }
    groundPin = pin;
    useGroundBeforeEach = true;
  }

  return recomputeDerivedConfig();
}

bool handleRepeat(const String &args) {
  if (args.length() == 0) {
    Serial.println(F("# ERROR: repeat requires a positive integer"));
    return false;
  }
  long val = args.toInt();
  if (val <= 0) val = 1;
  if (val > MAX_REPEAT_COUNT) val = MAX_REPEAT_COUNT;

  repeatCount = (uint16_t)val;
  // Validate channel + repeat + ground combination
  return recomputeDerivedConfig();
}

bool handleBuffer(const String &args) {
  if (args.length() == 0) {
    Serial.println(F("# ERROR: buffer requires a positive integer (sweeps per block)"));
    return false;
  }

  long val = args.toInt();
  if (val <= 0) val = 1;

  sweepsPerBlock = (uint16_t)val;
  bool ok = recomputeDerivedConfig();  // adjust to buffer size, etc.
  return ok;
}

bool handleRef(const String &args) {
  if (args.length() == 0) {
    Serial.println(F("# ERROR: ref requires a value (1.2, 3.3, vdd)"));
    return false;
  }

  String a = toLowerTrim(args);

  if (a == "1.2" || a == "1v2") {
    currentRef = AR_INTERNAL1V2;
    g_vref_mV  = 1200;
    g_vref_sel = iadcCfgReferenceInt1V2;
  } else if (a == "3.3" || a == "vdd") {
    currentRef = AR_VDD;
    g_vref_mV  = 3300;
    g_vref_sel = iadcCfgReferenceVddx;
  } else {
    Serial.println(F("# ERROR: only ref 1.2 and ref 3.3/vdd are supported in high-speed mode."));
    return false;
  }

  g_configDirty = true;
  doDummyRead();
  return true;
}

bool handleOsr(const String &args) {
  if (args.length() == 0) {
    Serial.println(F("# ERROR: osr requires an integer (2,4,8)"));
    return false;
  }
  long o = args.toInt();
  if (o == 2) {
    g_osr_hs = iadcCfgOsrHighSpeed2x;
  } else if (o == 4) {
    g_osr_hs = iadcCfgOsrHighSpeed4x;
  } else if (o == 8) {
    g_osr_hs = iadcCfgOsrHighSpeed8x;
  } else {
    Serial.println(F("# ERROR: osr must be 2, 4, or 8"));
    return false;
  }
  g_configDirty = true;
  doDummyRead();
  return true;
}

bool handleGain(const String &args) {
  if (args.length() == 0) {
    Serial.println(F("# ERROR: gain requires an integer (1,2,3,4)"));
    return false;
  }
  long g = args.toInt();
  if (g == 1) {
    g_gain = iadcCfgAnalogGain1x;
  } else if (g == 2) {
    g_gain = iadcCfgAnalogGain2x;
  } else if (g == 3) {
    g_gain = iadcCfgAnalogGain3x;
  } else if (g == 4) {
    g_gain = iadcCfgAnalogGain4x;
  } else {
    Serial.println(F("# ERROR: gain must be 1, 2, or 3, or 4"));
    return false;
  }
  g_configDirty = true;
  doDummyRead();
  return true;
}

bool handleRun(const String &args) {
  if (channelCount == 0) {
    Serial.println(F("# ERROR: no channels configured. Use 'channels ...' first."));
    return false;
  }

  if (args.length() == 0) {
    isRunning = true;
    timedRun  = false;
  } else {
    long ms = args.toInt();
    if (ms <= 0) {
      isRunning = true;
      timedRun  = false;
    } else {
      isRunning     = true;
      timedRun      = true;
      runStopMillis = millis() + (uint32_t)ms;
    }
  }

  if (!recomputeDerivedConfig()) {
    // Invalid config: don't start the run
    isRunning = false;
    timedRun  = false;
    return false;
  }

  // Ensure IADC is initialized with current config
  g_configDirty = true;
  
  // Run configurable warm-up sweeps
  discardWarmupSweeps(IADC_WARMUP_SWEEPS);  // e.g. 48 sweeps of 6 channels
  return true;
}



void handleStop() {
  isRunning = false;
  timedRun  = false;
}

// ---------------------------------------------------------------------
// Status / help
// ---------------------------------------------------------------------

void printMcu() {
  // Single line so the GUI can parse easily
  Serial.println(F("# MG24"));
}

void printStatus() {
  Serial.println(F("# -------- STATUS --------"));
  Serial.print(F("# running: "));
  Serial.println(isRunning ? F("true") : F("false"));

  Serial.print(F("# timedRun: "));
  Serial.println(timedRun ? F("true") : F("false"));

  Serial.print(F("# channels (count="));
  Serial.print(channelCount);
  Serial.println(F("):"));
  Serial.print(F("#   "));
  for (uint8_t i = 0; i < channelCount; i++) {
    Serial.print(channelSequence[i]);
    if (i + 1 < channelCount) Serial.print(F(","));
  }
  Serial.println();

  Serial.print(F("# repeatCount: "));
  Serial.println(repeatCount);

  Serial.print(F("# groundPin: "));
  Serial.println(groundPin);

  Serial.print(F("# useGroundBeforeEach: "));
  Serial.println(useGroundBeforeEach ? F("true") : F("false"));

  Serial.print(F("# adcReference: "));
  switch (currentRef) {
    case AR_INTERNAL1V2:   Serial.println(F("INTERNAL1V2")); break;
    case AR_EXTERNAL_1V25: Serial.println(F("EXTERNAL_1V25")); break;
    case AR_VDD:           Serial.println(F("VDD"));          break;
    case AR_08VDD:         Serial.println(F("0.8*VDD"));      break;
    default:               Serial.println(F("UNKNOWN"));      break;
  }

  int osrVal = -1;
  switch (g_osr_hs) {
    case iadcCfgOsrHighSpeed2x: osrVal = 2; break;
    case iadcCfgOsrHighSpeed4x: osrVal = 4; break;
    case iadcCfgOsrHighSpeed8x: osrVal = 8; break;
    default: osrVal = -1; break;
  }
  Serial.print(F("# osr (high-speed): "));
  Serial.println(osrVal);

  int gainVal = -1;
  switch (g_gain) {
    case iadcCfgAnalogGain1x: gainVal = 1; break;
    case iadcCfgAnalogGain2x: gainVal = 2; break;
    case iadcCfgAnalogGain3x: gainVal = 3; break;
    case iadcCfgAnalogGain4x: gainVal = 4; break;
    default: gainVal = -1; break;
  }
  Serial.print(F("# gain: "));
  Serial.print(gainVal);
  Serial.println(F("x"));

  Serial.print(F("# samplesPerSweep (sent): "));
  Serial.println(samplesPerSweep);

  Serial.print(F("# scanEntriesPerSweep (IADC incl. ground): "));
  Serial.println(scanEntriesPerSweep);

  Serial.print(F("# sweepsPerBlock: "));
  Serial.println(sweepsPerBlock);

  Serial.print(F("# MAX_SAMPLES_BUFFER: "));
  Serial.println(MAX_SAMPLES_BUFFER);

  Serial.print(F("# MAX_SCAN_ENTRIES (hardware limit): "));
  Serial.println(MAX_SCAN_ENTRIES);

  Serial.println(F("# -------------------------"));
}

void printHelp() {
  Serial.println(F("# Commands:"));
  Serial.println(F("#   channels 0,1,1,1,2,2,3,4,5"));
  Serial.println(F("#   ground 2              (set ground pin)"));
  Serial.println(F("#   ground true|false     (insert ground dummy before each new channel)"));
  Serial.println(F("#   repeat 20             (samples per channel per sweep)"));
  Serial.println(F("#   buffer 10             (sweeps per binary block)"));
  Serial.println(F("#   ref 1.2 | 3.3 | vdd   (set ADC reference)"));
  Serial.println(F("#   osr 2|4|8             (set high-speed oversampling)"));
  Serial.println(F("#   gain 1|2|3|4          (set analog gain multiplier)"));
  Serial.println(F("#   run                   (continuous until 'stop')"));
  Serial.println(F("#   run 100               (~100 ms time-limited run)"));
  Serial.println(F("#   stop                  (stop running)"));
  Serial.println(F("#   status                (show configuration)"));
  Serial.println(F("#   mcu                   (print MCU name for GUI detection)"));
  Serial.println(F("#   help                  (this message)"));
}

// ---------------------------------------------------------------------
// Command dispatcher
// ---------------------------------------------------------------------

void handleLine(const String &lineRaw) {
  String line = lineRaw;
  line.trim();
  if (line.length() == 0) return;

  String cmd, args;
  splitCommand(line, cmd, args);
  cmd.toLowerCase();

  bool ok = true;

  if      (cmd == "channels")    { ok = handleChannels(args); }
  else if (cmd == "ground")      { ok = handleGround(args); }
  else if (cmd == "repeat")      { ok = handleRepeat(args); }
  else if (cmd == "buffer")      { ok = handleBuffer(args); }
  else if (cmd == "ref")         { ok = handleRef(args); }
  else if (cmd == "osr")         { ok = handleOsr(args); }
  else if (cmd == "gain")        { ok = handleGain(args); }
  else if (cmd == "run")         { ok = handleRun(args); }
  else if (cmd == "stop")        { handleStop(); ok = true; }
  else if (cmd == "status")      { printStatus(); ok = true; }
  else if (cmd == "mcu")         { printMcu();   ok = true; }
  else if (cmd == "help")        { printHelp();  ok = true; }
  else {
    Serial.print(F("# ERROR: unknown command '"));
    Serial.print(cmd);
    Serial.println(F("'. Type 'help'."));
    ok = false;
  }

  sendCommandAck(ok, args);
}

// ---------------------------------------------------------------------
// setup() and loop()
// ---------------------------------------------------------------------

void setup() {
  Serial.begin(BAUD_RATE);
  while (!Serial) {
    ; // wait for USB serial
  }

  (void)recomputeDerivedConfig();
  g_configDirty = true;
}

void loop() {
  // 1) Handle incoming serial bytes (command parser)
  while (Serial.available() > 0) {
    char c = (char)Serial.read();

    if (c == '\r' || c == '\n') {
      continue;
    }

    if (c == CMD_TERMINATOR) {
      if (inputLine.length() > 0) {
        handleLine(inputLine);
        inputLine = "";
      }
      continue;
    }

    inputLine += c;

    if (inputLine.length() > MAX_CMD_LENGTH) {
      inputLine = "";
      Serial.println(F("# ERROR: input line too long; cleared."));
    }
  }

  // 2) Handle timed run stop BETWEEN blocks
  if (isRunning && timedRun) {
    uint32_t now = millis();
    if ((int32_t)(now - runStopMillis) >= 0) {
      isRunning = false;
      timedRun  = false;
      return;   // don't start a new block
    }
  }

  // 3) Run a whole block if we're in run mode
  if (isRunning) {
    doOneBlock();   // captures entire block with IADC scan, then sends it
  }
}
