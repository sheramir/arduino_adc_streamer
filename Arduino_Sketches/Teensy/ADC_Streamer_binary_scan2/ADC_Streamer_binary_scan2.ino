/*
 * High-speed ADC Binary Sweeper with Blocked Output — Teensy 4.1
 * --------------------------------------------------------------
 *
 * New Teensy-specific features:
 *
 *   - ref 3.3* / ref vdd*   -> ADC reference = 3.3V (actual hardware setting)
 *   - ref 1.2*              -> ERROR on Teensy 4.1 (1.2V internal ref not supported)
 *
 *   - conv low|med|high|ad10|ad20*
 *        low   -> ADC_CONVERSION_SPEED::LOW_SPEED
 *        med   -> ADC_CONVERSION_SPEED::MED_SPEED
 *        high  -> ADC_CONVERSION_SPEED::HIGH_SPEED
 *        ad10  -> ADC_CONVERSION_SPEED::ADACK_10  (10 MHz async clock)
 *        ad20  -> ADC_CONVERSION_SPEED::ADACK_20  (20 MHz async clock)
 *
 *   - samp vlow|low|lmed|med|mhigh|high|hvhigh|vhigh*
 *        mapped to ADC_SAMPLING_SPEED enum (Teensy 4.1)
 *
 *   - rate 0*         -> free-run as fast as possible (current behavior)
 *   - rate 50000*     -> target ~50 kSamples/s, using IntervalTimer
 *
 * Timer-based sampling:
 *   - An IntervalTimer ISR increments a tick counter at the requested rate.
 *   - doOneBlock() waits for one tick per ADC sample, so every sample is paced
 *     by the hardware timer (sampling rate).
 *
 * Protocol, commands, and binary block format remain compatible with the MG24 version.
 */

#include <Arduino.h>
#include <ADC.h>
#include <ADC_util.h>
#include <IntervalTimer.h>

// ---------------------------------------------------------------------
// Limits & defaults
// ---------------------------------------------------------------------

const uint8_t  MAX_SEQUENCE_LEN   = 16;     // Max number of channels in sequence
const uint32_t BAUD_RATE          = 460800; // Ignored for USB, but kept for symmetry

// Max samples in RAM buffer (each sample = uint16_t)
const uint32_t MAX_SAMPLES_BUFFER = 32000;  // 32000 * 2bytes = 64kB

// Logical "scan entries" count (no HW table limit on Teensy; informational only)
const uint16_t MAX_SCAN_ENTRIES   = 65535;

// ---------------------------------------------------------------------
// Command framing constants
// ---------------------------------------------------------------------

static const char     CMD_TERMINATOR   = '*';   // '*' ends a command
static const uint16_t MAX_CMD_LENGTH   = 512;   // Max input line length

// ---------------------------------------------------------------------
// Simplified analog reference type (for status only)
// ---------------------------------------------------------------------

enum analog_references {
  AR_INTERNAL1V2,
  AR_EXTERNAL_1V25,
  AR_VDD,
  AR_08VDD
};

// ---------------------------------------------------------------------
// Teensy ADC instance
// ---------------------------------------------------------------------

ADC adc;  // main ADC controller (we use adc0)

// ---------------------------------------------------------------------
// Configuration state
// ---------------------------------------------------------------------

uint8_t  channelSequence[MAX_SEQUENCE_LEN]; // user-chosen pins in sweep
uint8_t  channelCount        = 0;           // how many channels in sequence

// Ground configuration:
// - Default ground pin is 0.
// - Default: ground dummy reads disabled.
int   groundPin              = 0;
bool  useGroundBeforeEach    = false;

// repeatCount = number of readings per channel per sweep (sent to PC)
uint16_t repeatCount         = 1;

// ADC sample buffer for multiple sweeps (flattened, only NON-ground samples)
uint16_t adcBuffer[MAX_SAMPLES_BUFFER];

// Derived config values
uint16_t samplesPerSweep       = 0;  // number of samples actually SENT per sweep (no ground)
uint16_t scanEntriesPerSweep   = 0;  // logical count: channels + ground entries

// Blocked/buffered sweeps:
uint16_t sweepsPerBlock        = 1;  // how many sweeps per block
uint16_t sweepsInCurrentBlock  = 0;  // informational only

// ---------------------------------------------------------------------
// High-speed ADC configuration state (runtime adjustable)
// ---------------------------------------------------------------------

analog_references     currentRef    = AR_VDD; // status only

// OSR command value (2,4,8) mapped to hardware averaging
static uint8_t        g_osr_cmd      = 2;
static uint16_t       g_adc_averages = 4;  // actual averaging count used

// Conversion and sampling speeds (actual ADC settings)
static ADC_CONVERSION_SPEED g_conv_speed  = ADC_CONVERSION_SPEED::HIGH_SPEED;
static ADC_SAMPLING_SPEED   g_samp_speed  = ADC_SAMPLING_SPEED::VERY_HIGH_SPEED;

// Gain tracking (for status only)
static uint8_t        g_gain_cmd     = 1;

// ---------------------------------------------------------------------
// Sampling rate control (hardware timer pacing)
// ---------------------------------------------------------------------

IntervalTimer          g_sampleTimer;
volatile uint32_t      g_sampleTick      = 0;   // incremented by timer ISR
float                  g_sampleRateHz    = 0.0; // 0 = free-run

void sampleTimerISR() {
  g_sampleTick++;
}

void stopSampleTimer() {
  g_sampleTimer.end();
}

void startSampleTimerIfNeeded() {
  if (g_sampleRateHz <= 0.0f) {
    stopSampleTimer();
    return;
  }
  float periodUs = 1000000.0f / g_sampleRateHz;
  if (periodUs < 1.0f) periodUs = 1.0f; // clamp to >=1 µs
  g_sampleTick = 0;
  g_sampleTimer.begin(sampleTimerISR, periodUs);
}

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

// Dummy-read placeholder (does nothing significant on Teensy)
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
// Helper: calculate how many logical "scan entries" per sweep
// (including ground entries, if enabled) — purely logical on Teensy.
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
      total += 1; // ground entry
    }

    // rep samples for this channel
    total += rep;
    prevChan = chan;
  }

  return total;
}

// ---------------------------------------------------------------------
// Derived configuration recomputation
// ---------------------------------------------------------------------
void recomputeDerivedConfig() {
  if (channelCount == 0) {
    samplesPerSweep      = 0;
    scanEntriesPerSweep  = 0;
    sweepsPerBlock       = 1;
    sweepsInCurrentBlock = 0;
    return;
  }

  // Number of logical "scan entries" (channels + optional ground)
  scanEntriesPerSweep = calcScanEntryCount(repeatCount);

  // Number of samples actually SENT per sweep (channels only)
  samplesPerSweep = (uint16_t)channelCount * (uint16_t)repeatCount;

  if (samplesPerSweep == 0) {
    sweepsPerBlock       = 1;
    sweepsInCurrentBlock = 0;
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

    sweepsInCurrentBlock = 0;
  }
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

void sendBlock(uint16_t sampleCount, uint32_t totalTimeUs) {
  if (sampleCount == 0) return;

  uint32_t totalSamples = sampleCount;
  if (totalSamples > MAX_SAMPLES_BUFFER) {
    totalSamples = MAX_SAMPLES_BUFFER;
  }

  uint32_t avgSampleDtUs = (totalSamples > 0) ? (totalTimeUs / totalSamples) : 0;

  uint16_t avgSampleDtUs16 = (avgSampleDtUs <= 65535u)
                               ? (uint16_t)avgSampleDtUs
                               : (uint16_t)65535u;

  // Header
  sendSweepHeader((uint16_t)totalSamples);

  // Samples (channels only, already filtered)
  Serial.write((uint8_t*)adcBuffer, (size_t)(totalSamples * sizeof(uint16_t)));

  // Average per-sample time (µs)
  uint8_t rateBytes[2];
  rateBytes[0] = (uint8_t)(avgSampleDtUs16 & 0xFF);
  rateBytes[1] = (uint8_t)(avgSampleDtUs16 >> 8);
  Serial.write(rateBytes, 2);
}

// ---------------------------------------------------------------------
// Teensy ADC configuration
// ---------------------------------------------------------------------

void applyADCConfig() {
  // Use ADC0 only; resolution 12-bit
  adc.adc0->setResolution(12);

  // Averaging
  adc.adc0->setAveraging(g_adc_averages);

  // Conversion + sampling speed (user-configurable)
  adc.adc0->setConversionSpeed(g_conv_speed);
  adc.adc0->setSamplingSpeed(g_samp_speed);

  // Reference: Teensy 4.1 ADC uses 3.3V reference only
  adc.adc0->setReference(ADC_REFERENCE::REF_3V3);
}

// Simple helper to read one sample from a given Arduino pin using ADC0
uint16_t readSingleSample(uint8_t pin) {
  return (uint16_t)adc.adc0->analogRead(pin);
}

// ---------------------------------------------------------------------
// Capture one block into adcBuffer using fast or timer-paced ADC reads
// ---------------------------------------------------------------------

void doOneBlock() {
  if (!isRunning || channelCount == 0 || samplesPerSweep == 0) return;

  // Total SAMPLES WE WILL SEND (no ground).
  uint32_t totalSamples = (uint32_t)sweepsPerBlock * (uint32_t)samplesPerSweep;
  if (totalSamples > MAX_SAMPLES_BUFFER) {
    totalSamples = MAX_SAMPLES_BUFFER;
  }

  sweepsInCurrentBlock = sweepsPerBlock;

  uint32_t idx = 0;

  // --- Two modes: free-run vs timer-paced sampling ---
  bool useTimerPacing = (g_sampleRateHz > 0.0f);

  if (!useTimerPacing) {
    // -------------------- FREE-RUN MODE --------------------
    blockStartMicros = micros();

    for (uint16_t s = 0; s < sweepsPerBlock && idx < totalSamples; ++s) {
      int prevChan = -1;

      for (uint8_t i = 0; i < channelCount && idx < totalSamples; ++i) {
        uint8_t chan  = channelSequence[i];
        bool    isNew = (i == 0) || (chan != prevChan);

        // Optional ground dummy before each *new* channel
        if (useGroundBeforeEach && isNew) {
          (void)readSingleSample((uint8_t)groundPin); // discard
        }

        // Repeat samples for this channel
        for (uint16_t r = 0; r < repeatCount && idx < totalSamples; ++r) {
          uint16_t data = readSingleSample(chan);
          adcBuffer[idx++] = data;
        }

        prevChan = chan;
      }
    }

    uint32_t totalTimeUs = micros() - blockStartMicros; // ADC capture time only
    sendBlock((uint16_t)idx, totalTimeUs);
  } else {
    // ---------------- TIMER-PACED MODE (one tick per sample) ----------------
    uint32_t startTick    = g_sampleTick;
    uint32_t expectedTick = startTick;

    blockStartMicros = micros();

    for (uint16_t s = 0; s < sweepsPerBlock && idx < totalSamples; ++s) {
      int prevChan = -1;

      for (uint8_t i = 0; i < channelCount && idx < totalSamples; ++i) {
        uint8_t chan  = channelSequence[i];
        bool    isNew = (i == 0) || (chan != prevChan);

        // Optional ground dummy before each *new* channel
        if (useGroundBeforeEach && isNew) {
          // One timer tick for the ground sample
          expectedTick++;
          while (g_sampleTick < expectedTick) {
            // spin until timer tick arrives
          }
          (void)readSingleSample((uint8_t)groundPin); // discard
        }

        // Repeat samples for this channel
        for (uint16_t r = 0; r < repeatCount && idx < totalSamples; ++r) {
          expectedTick++;
          while (g_sampleTick < expectedTick) {
            // wait for next timer tick
          }
          uint16_t data = readSingleSample(chan);
          adcBuffer[idx++] = data;
        }

        prevChan = chan;
      }
    }

    uint32_t totalTimeUs = micros() - blockStartMicros;
    sendBlock((uint16_t)idx, totalTimeUs);
  }

  sweepsInCurrentBlock = 0;
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
    recomputeDerivedConfig();
    return false;
  }

  // Set pins as inputs
  for (uint8_t k = 0; k < channelCount; ++k) {
    pinMode(channelSequence[k], INPUT);
  }

  recomputeDerivedConfig();
  return true;
}

bool handleGround(const String &args) {
  if (args.length() == 0) {
    Serial.println(F("# ERROR: ground requires an argument (pin number or true/false)"));
    return false;
  }

  String a = toLowerTrim(args);

  if (a == "true") {
    useGroundBeforeEach = true;
  } else if (a == "false") {
    useGroundBeforeEach = false;
  } else { // command specified a pin number for groundPin
    int pin = a.toInt();
    if (pin < 0 || pin > 255) {
      Serial.println(F("# ERROR: ground pin out of range (0-255)"));
      return false;
    }

    groundPin = pin;
    pinMode(groundPin, INPUT);
    useGroundBeforeEach = true;
  }

  recomputeDerivedConfig();
  return true;
}

bool handleRepeat(const String &args) {
  if (args.length() == 0) {
    Serial.println(F("# ERROR: repeat requires a positive integer"));
    return false;
  }
  long val = args.toInt();
  if (val <= 0) val = 1;

  repeatCount = (uint16_t)val;
  recomputeDerivedConfig();
  return true;
}

bool handleBuffer(const String &args) {
  if (args.length() == 0) {
    Serial.println(F("# ERROR: buffer requires a positive integer (sweeps per block)"));
    return false;
  }

  long val = args.toInt();
  if (val <= 0) val = 1;

  sweepsPerBlock = (uint16_t)val;
  recomputeDerivedConfig();
  sweepsInCurrentBlock = 0;
  return true;
}

// Reference selection (3.3V only on Teensy 4.1)
bool handleRef(const String &args) {
  if (args.length() == 0) {
    Serial.println(F("# ERROR: ref requires a value (1.2, 3.3, vdd)"));
    return false;
  }

  String a = toLowerTrim(args);

  if (a == "1.2" || a == "1v2") {
    // Teensy 4.x has no usable 1.2V internal reference in this library.
    Serial.println(F("# ERROR: Teensy 4.1 does NOT support 1.2V ADC reference. Use ref 3.3/vdd."));
    return false;
  } else if (a == "3.3" || a == "vdd") {
    currentRef = AR_VDD;
    adc.adc0->setReference(ADC_REFERENCE::REF_3V3);
  } else {
    Serial.println(F("# ERROR: only ref 3.3/vdd are supported on Teensy 4.1."));
    return false;
  }

  doDummyRead();
  return true;
}

// OSR -> hardware averaging
bool handleOsr(const String &args) {
  if (args.length() == 0) {
    Serial.println(F("# ERROR: osr requires an integer (0,1,2,4,8,16,32)"));
    return false;
  }

  long o = args.toInt();

  // Valid Teensy averaging values:
  //   0 = disable averaging
  //   1,2,4,8,16,32 = allowed by ADC library
  if (o == 0 || o == 1 || o == 2 || o == 4 || o == 8 || o == 16 || o == 32) {
    g_osr_cmd      = (uint8_t)o;      // record user command
    g_adc_averages = (uint16_t)o;     // direct mapping to hardware
  } else {
    Serial.println(F("# ERROR: osr must be one of 0,1,2,4,8,16,32 for Teensy 4.1"));
    return false;
  }

  applyADCConfig();
  doDummyRead();
  return true;
}


// Gain (status-only)
bool handleGain(const String &args) {
  if (args.length() == 0) {
    Serial.println(F("# ERROR: gain requires an integer (1,2,3,4)"));
    return false;
  }
  long g = args.toInt();
  if (g < 1 || g > 4) {
    Serial.println(F("# ERROR: gain must be 1, 2, 3, or 4 (status-only on Teensy)."));
    return false;
  }
  g_gain_cmd = (uint8_t)g;
  doDummyRead();
  return true;
}

// Conversion speed
bool handleConv(const String &args) {
  if (args.length() == 0) {
    Serial.println(F("# ERROR: conv requires one of: low, med, high, ad10, ad20"));
    return false;
  }

  String a = toLowerTrim(args);

  if      (a == "low")  { g_conv_speed = ADC_CONVERSION_SPEED::LOW_SPEED;  }
  else if (a == "med")  { g_conv_speed = ADC_CONVERSION_SPEED::MED_SPEED;  }
  else if (a == "high") { g_conv_speed = ADC_CONVERSION_SPEED::HIGH_SPEED; }
  else if (a == "ad10") { g_conv_speed = ADC_CONVERSION_SPEED::ADACK_10;   }
  else if (a == "ad20") { g_conv_speed = ADC_CONVERSION_SPEED::ADACK_20;   }
  else {
    Serial.println(F("# ERROR: conv must be low, med, high, ad10, or ad20"));
    return false;
  }

  applyADCConfig();
  doDummyRead();
  return true;
}

// Sampling speed
bool handleSamp(const String &args) {
  if (args.length() == 0) {
    Serial.println(F("# ERROR: samp requires one of: vlow, low, lmed, med, mhigh, high, hvhigh, vhigh"));
    return false;
  }

  String a = toLowerTrim(args);

  if      (a == "vlow")   { g_samp_speed = ADC_SAMPLING_SPEED::VERY_LOW_SPEED;      }
  else if (a == "low")    { g_samp_speed = ADC_SAMPLING_SPEED::LOW_SPEED;           }
  else if (a == "lmed")   { g_samp_speed = ADC_SAMPLING_SPEED::LOW_MED_SPEED;       }
  else if (a == "med")    { g_samp_speed = ADC_SAMPLING_SPEED::MED_SPEED;           }
  else if (a == "mhigh")  { g_samp_speed = ADC_SAMPLING_SPEED::MED_HIGH_SPEED;      }
  else if (a == "high")   { g_samp_speed = ADC_SAMPLING_SPEED::HIGH_SPEED;          }
  else if (a == "hvhigh") { g_samp_speed = ADC_SAMPLING_SPEED::HIGH_VERY_HIGH_SPEED;}
  else if (a == "vhigh")  { g_samp_speed = ADC_SAMPLING_SPEED::VERY_HIGH_SPEED;     }
  else {
    Serial.println(F("# ERROR: samp must be vlow, low, lmed, med, mhigh, high, hvhigh, or vhigh"));
    return false;
  }

  applyADCConfig();
  doDummyRead();
  return true;
}

// Sampling rate via IntervalTimer
bool handleRate(const String &args) {
  if (args.length() == 0) {
    Serial.println(F("# ERROR: rate requires 0 or a positive frequency in Hz (e.g. rate 50000)"));
    return false;
  }

  long val = args.toInt();
  if (val < 0) val = 0;

  if (val == 0) {
    g_sampleRateHz = 0.0f;
    stopSampleTimer();
  } else {
    g_sampleRateHz = (float)val;
    if (isRunning) {
      startSampleTimerIfNeeded();
    }
  }

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

  sweepsInCurrentBlock = 0;
  recomputeDerivedConfig();

  if (g_sampleRateHz > 0.0f) {
    startSampleTimerIfNeeded();
  }

  return true;
}

void handleStop() {
  isRunning = false;
  timedRun  = false;
  stopSampleTimer();
}

// ---------------------------------------------------------------------
// Status / help
// ---------------------------------------------------------------------

void printMcu() {
  // Single line so the GUI can parse easily
  Serial.println(F("# Teensy4.1"));
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

  Serial.print(F("# adcReference (Teensy 4.1 HW): 3.3V (VDD)\n"));

  Serial.print(F("# osr command: "));
  Serial.print(g_osr_cmd);
  Serial.print(F(" (averaging = "));
  Serial.print(g_adc_averages);
  Serial.println(F(" samples)"));

  Serial.print(F("# gain command: "));
  Serial.print(g_gain_cmd);
  Serial.println(F("x (status-only, no HW gain)"));

  Serial.print(F("# conv speed: "));
  // crude print of enum (by name)
  if      (g_conv_speed == ADC_CONVERSION_SPEED::LOW_SPEED)  Serial.println(F("LOW_SPEED"));
  else if (g_conv_speed == ADC_CONVERSION_SPEED::MED_SPEED)  Serial.println(F("MED_SPEED"));
  else if (g_conv_speed == ADC_CONVERSION_SPEED::HIGH_SPEED) Serial.println(F("HIGH_SPEED"));
  else if (g_conv_speed == ADC_CONVERSION_SPEED::ADACK_10)   Serial.println(F("ADACK_10"));
  else if (g_conv_speed == ADC_CONVERSION_SPEED::ADACK_20)   Serial.println(F("ADACK_20"));
  else                                                       Serial.println(F("OTHER"));

  Serial.print(F("# samp speed: "));
  if      (g_samp_speed == ADC_SAMPLING_SPEED::VERY_LOW_SPEED)       Serial.println(F("VERY_LOW_SPEED"));
  else if (g_samp_speed == ADC_SAMPLING_SPEED::LOW_SPEED)            Serial.println(F("LOW_SPEED"));
  else if (g_samp_speed == ADC_SAMPLING_SPEED::LOW_MED_SPEED)        Serial.println(F("LOW_MED_SPEED"));
  else if (g_samp_speed == ADC_SAMPLING_SPEED::MED_SPEED)            Serial.println(F("MED_SPEED"));
  else if (g_samp_speed == ADC_SAMPLING_SPEED::MED_HIGH_SPEED)       Serial.println(F("MED_HIGH_SPEED"));
  else if (g_samp_speed == ADC_SAMPLING_SPEED::HIGH_SPEED)           Serial.println(F("HIGH_SPEED"));
  else if (g_samp_speed == ADC_SAMPLING_SPEED::HIGH_VERY_HIGH_SPEED) Serial.println(F("HIGH_VERY_HIGH_SPEED"));
  else if (g_samp_speed == ADC_SAMPLING_SPEED::VERY_HIGH_SPEED)      Serial.println(F("VERY_HIGH_SPEED"));
  else                                                               Serial.println(F("OTHER"));

  Serial.print(F("# sampleRateHz (0=free-run): "));
  Serial.println(g_sampleRateHz, 2);

  Serial.print(F("# samplesPerSweep (sent): "));
  Serial.println(samplesPerSweep);

  Serial.print(F("# scanEntriesPerSweep (logical incl. ground): "));
  Serial.println(scanEntriesPerSweep);

  Serial.print(F("# sweepsPerBlock: "));
  Serial.println(sweepsPerBlock);

  Serial.print(F("# sweepsInCurrentBlock: "));
  Serial.println(sweepsInCurrentBlock);

  Serial.print(F("# MAX_SAMPLES_BUFFER: "));
  Serial.println(MAX_SAMPLES_BUFFER);

  Serial.print(F("# MAX_SCAN_ENTRIES (informational): "));
  Serial.println(MAX_SCAN_ENTRIES);

  Serial.println(F("# -------------------------"));
}

void printHelp() {
  Serial.println(F("# Commands:"));
  Serial.println(F("#   channels 0,1,1,1,2,2,3,4,5"));
  Serial.println(F("#   ground 2                 (set ground pin)"));
  Serial.println(F("#   ground true|false        (insert ground dummy before each new channel)"));
  Serial.println(F("#   repeat 20                (samples per channel per sweep)"));
  Serial.println(F("#   buffer 10                (sweeps per binary block)"));
  Serial.println(F("#   ref 3.3 | vdd            (set ADC reference to 3.3V VDD)"));
  Serial.println(F("#   ref 1.2                  (ERROR: not supported on Teensy 4.1)"));
  Serial.println(F("#   osr 2|4|8                (set hardware averaging)"));
  Serial.println(F("#   gain 1|2|3|4             (status-only gain multiplier)"));
  Serial.println(F("#   conv low|med|high|ad10|ad20    (conversion speed)"));
  Serial.println(F("#   samp vlow|low|lmed|med|mhigh|high|hvhigh|vhigh (sampling speed)"));
  Serial.println(F("#   rate 0                  (free-run as fast as possible)"));
  Serial.println(F("#   rate 50000              (target ~50k samples/s via timer)"));
  Serial.println(F("#   run                     (continuous until 'stop')"));
  Serial.println(F("#   run 100                 (~100 ms time-limited run)"));
  Serial.println(F("#   stop                    (stop running)"));
  Serial.println(F("#   status                  (show configuration)"));
  Serial.println(F("#   mcu                     (print MCU name for GUI detection)"));
  Serial.println(F("#   help                    (this message)"));
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
  else if (cmd == "conv")        { ok = handleConv(args); }
  else if (cmd == "samp")        { ok = handleSamp(args); }
  else if (cmd == "rate")        { ok = handleRate(args); }
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
    // wait for USB serial
  }

  // Basic ADC configuration
  applyADCConfig();

  recomputeDerivedConfig();
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
      stopSampleTimer();
      return;   // don't start a new block
    }
  }

  // 3) Run a whole block if we're in run mode
  if (isRunning) {
    doOneBlock();   // captures entire block, then sends it
  }
}
