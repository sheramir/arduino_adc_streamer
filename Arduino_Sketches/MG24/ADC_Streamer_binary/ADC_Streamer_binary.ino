/*
 * Interactive ADC CSV Sweeper — XIAO MG24 / similar
 * -------------------------------------------------
 *
 * Core behavior:
 *   - You configure a list of channels with `channels ...`
 *   - You configure how many times to read each channel with `repeat N`
 *   - Each "sweep" prints ONE CSV line:
 *
 *        [ch0_r1, ch0_r2, ... ch0_rN, ch1_r1, ... chLast_rN]
 *
 *   - If `ground true` is enabled, before each capture the code reads
 *     the ground pin (discarded, not printed) to help you do your own
 *     offset / reference corrections.
 *
 * New commands:
 *   - ref 1.2      -> ADC reference = 1.2V internal (AR_INTERNAL1V2)
 *   - ref 3.3      -> ADC reference = VDD (3.3V typical) (AR_VDD)
 *   - ref vdd      -> same as 3.3 (VDD)
 *   - ref 0.8vdd   -> ADC reference = 0.8*VDD (AR_08VDD)
 *   - ref ext      -> ADC reference = external 1.25V (AR_EXTERNAL_1V25)
 *
 *   - res 16       -> ADC resolution = 16 bits
 *                     (You can also use res 8, 10, 12, etc.)
 *
 * IMPORTANT:
 *   After each ref / res change, the sketch performs a dummy analogRead()
 *   to allow the ADC reference / resolution to settle:
 *     - If groundPin is defined use that.
 *     - Else if channels are defined use the first channel pin.
 *     - Else fall back to pin 0.
 *
 * Commands (one per line, via Serial @ 115200):
 *
 *   channels 0,1,1,1,2,2,3,4,5
 *     - Set the ADC sweep sequence (Arduino pin numbers, duplicates allowed).
 *
 *   delay 50
 *     - Add delay between samples in µs.
 *
 *   ground 2
 *     - Set "ground" pin (physically tied to GND).
 *
 *   ground true
 *   ground false
 *     - Enable/disable ground sampling before each individual capture.
 *       Ground reading is DISCARDED (not printed).
 *
 *   repeat 20
 *     - For each channel in the sequence, capture it 20 times per sweep.
 *
 *   ref 1.2
 *   ref 3.3
 *   ref vdd
 *   ref 0.8vdd
 *   ref ext
 *     - Set ADC reference as described above.
 *
 *   res 16
 *     - Set ADC resolution (bits). Typical useful values: 8,10,12,16.
 *
 *   run
 *     - Continuous run (sweeps forever) until 'stop' is received.
 *
 *   run 100
 *     - Timed run: sweeps for ~100 ms then stops automatically.
 *
 *   stop
 *     - Stop running, stay in command mode.
 *
 *   status
 *     - Print current configuration (with '#'-prefixed lines).
 *
 *   help
 *     - Print help text (with '#'-prefixed lines).
 *
 * CSV OUTPUT WHILE RUNNING:
 *   One line per sweep:
 *       v0,v1,...,v(N-1)
 *   where N = channels_count * repeatCount
 *   No headers, no channel IDs, no comments.
 */

#include <Arduino.h>


// ---------------------------------------------------------------------
// Limits & defaults
// ---------------------------------------------------------------------

const uint8_t  MAX_SEQUENCE_LEN  = 16; // Maximum number of channels in a sequence
const uint32_t DEFAULT_DELAY_US  = 0;

// ---------------------------------------------------------------------
// Configuration state
// ---------------------------------------------------------------------

uint8_t  channelSequence[MAX_SEQUENCE_LEN];
uint8_t  channelCount        = 0;

int      groundPin           = -1;   // -1 = not set
bool     useGroundBeforeEach = false;

uint32_t interSweepDelayUs   = DEFAULT_DELAY_US;

// repeatCount = number of ADC readings per channel per sweep
uint16_t repeatCount         = 1;

// ADC configuration state
uint8_t  adcResolutionBits   = 12;   // default 12-bit for XIAO MG24
analog_references currentRef = AR_VDD; // default reference = VDD

// Maximum repeat count we support (same as previous logical limit)
const uint16_t MAX_REPEAT_COUNT = 100;

// ADC sample buffer: max 64 channels * 1000 repeats = 64000 samples = 128kB
// With 256kB RAM on MG24 this is safe.
uint16_t adcBuffer[MAX_SEQUENCE_LEN * MAX_REPEAT_COUNT];

// Derived config values (recomputed when config changes)
uint16_t samplesPerSweep       = 0;   // channelCount * repeatCount
int      effectiveGroundCached = -1;  // ground pin actually used for dummy reads

// ---------------------------------------------------------------------
// Run state
// ---------------------------------------------------------------------

bool     isRunning           = false;
bool     timedRun            = false;
uint32_t runStopMillis       = 0;

// ---------------------------------------------------------------------
// Rate measurement state (only active between start-rate / end-rate)
// ---------------------------------------------------------------------

bool     rateEnabled      = false;  // true while we're measuring timing
bool     rateEverStarted  = false;  // used so get-rate can error if never started
bool     rateHasData      = false;  // becomes true once any delta is recorded

// Per-channel-index timing (per position in channelSequence[])
uint32_t lastStartUsPerIdx[MAX_SEQUENCE_LEN];
bool     hasLastStartPerIdx[MAX_SEQUENCE_LEN];
uint32_t minDeltaPerIdx[MAX_SEQUENCE_LEN];
uint32_t maxDeltaPerIdx[MAX_SEQUENCE_LEN];
uint64_t sumDeltaPerIdx[MAX_SEQUENCE_LEN];
uint32_t countDeltaPerIdx[MAX_SEQUENCE_LEN];

// Between-consecutive-channels timing (within a sweep)
uint32_t lastChannelStartUsInSweep      = 0;
bool     haveLastChannelStartUsInSweep  = false;
uint32_t minBetweenChannelsUs           = 0xFFFFFFFFUL;
uint32_t maxBetweenChannelsUs           = 0;
uint64_t sumBetweenChannelsUs           = 0;
uint32_t countBetweenChannelsUs         = 0;

void resetRateStats() {
  for (uint8_t i = 0; i < MAX_SEQUENCE_LEN; i++) {
    lastStartUsPerIdx[i]   = 0;
    hasLastStartPerIdx[i]  = false;
    minDeltaPerIdx[i]      = 0xFFFFFFFFUL;
    maxDeltaPerIdx[i]      = 0;
    sumDeltaPerIdx[i]      = 0;
    countDeltaPerIdx[i]    = 0;
  }

  lastChannelStartUsInSweep     = 0;
  haveLastChannelStartUsInSweep = false;
  minBetweenChannelsUs          = 0xFFFFFFFFUL;
  maxBetweenChannelsUs          = 0;
  sumBetweenChannelsUs          = 0;
  countBetweenChannelsUs        = 0;

  rateHasData = false;
}


// ---------------------------------------------------------------------
// Serial input buffer
// ---------------------------------------------------------------------

String   inputLine;


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

// Choose a pin for dummy reads (after ref/res change)
int chooseDummyPin() {
  if (groundPin >= 0) {
    return groundPin;
  } else if (channelCount > 0) {
    return channelSequence[0];
  } else {
    return 0; // fallback
  }
}

// Perform a single dummy read to settle ADC after configuration changes
void doDummyRead() {
  int pin = chooseDummyPin();
  (void)analogRead(pin);
}


// ---------------------------------------------------------------------
// Derived configuration recomputation
// ---------------------------------------------------------------------
void recomputeDerivedConfig() {
  // Total samples in one sweep
  samplesPerSweep = (uint16_t)channelCount * (uint16_t)repeatCount;

  // Determine which pin to use as "ground" during sweeps (if enabled)
  if (!useGroundBeforeEach) {
    effectiveGroundCached = -1;  // no ground reads at all
  } else {
    if (groundPin >= 0) {
      effectiveGroundCached = groundPin;
    } else if (channelCount > 0) {
      // If ground not explicitly set, use first channel pin by default
      effectiveGroundCached = channelSequence[0];
    } else {
      // Fallback if no channels yet
      effectiveGroundCached = 0;
    }
  }
}



// ---------------------------------------------------------------------
// Binary sweep output helpers
// ---------------------------------------------------------------------

const uint8_t SWEEP_MAGIC1 = 0xAA;
const uint8_t SWEEP_MAGIC2 = 0x55;

// Send 4-byte sweep header: [0xAA][0x55][countL][countH]
void sendSweepHeader(uint16_t totalSamples) {
  uint8_t header[4];
  header[0] = SWEEP_MAGIC1;
  header[1] = SWEEP_MAGIC2;
  header[2] = (uint8_t)(totalSamples & 0xFF);
  header[3] = (uint8_t)(totalSamples >> 8);
  Serial.write(header, 4);
}


// ---------------------------------------------------------------------
// Command handlers
// ---------------------------------------------------------------------

void handleChannels(const String &args) {
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
  }

  recomputeDerivedConfig();
}

void handleDelay(const String &args) {
  if (args.length() == 0) {
    Serial.println(F("# ERROR: delay requires a value in microseconds"));
    return;
  }
  long val = args.toInt();
  if (val < 0) val = 0;
  interSweepDelayUs = (uint32_t)val;
}

void handleGround(const String &args) {
  if (args.length() == 0) {
    Serial.println(F("# ERROR: ground requires an argument (pin number or true/false)"));
    return;
  }

  String a = toLowerTrim(args);

  if (a == "true") {
    useGroundBeforeEach = true;
    if (groundPin < 0) {
      groundPin = 0;  // default if not set
    }
  } else if (a == "false") {
    useGroundBeforeEach = false;
  } else {
    int pin = a.toInt();
    if (pin < 0 || pin > 255) {
      Serial.println(F("# ERROR: ground pin out of range (0-255)"));
      return;
    }
    groundPin = pin;
    recomputeDerivedConfig();
  }
}

void handleRepeat(const String &args) {
  if (args.length() == 0) {
    Serial.println(F("# ERROR: repeat requires a positive integer"));
    return;
  }
  long val = args.toInt();
  if (val <= 0) val = 1;
  if (val > MAX_REPEAT_COUNT) val = MAX_REPEAT_COUNT; // some upper bound to avoid huge lines

  repeatCount = (uint16_t)val;
  recomputeDerivedConfig();
}

// Set ADC reference (and do dummy read)
void handleRef(const String &args) {
  if (args.length() == 0) {
    Serial.println(F("# ERROR: ref requires a value (1.2, 3.3, vdd, 0.8vdd, ext)"));
    return;
  }

  String a = toLowerTrim(args);

  if (a == "1.2" || a == "1v2") {
    currentRef = AR_INTERNAL1V2;
  } else if (a == "3.3" || a == "vdd") {
    currentRef = AR_VDD;
  } else if (a == "0.8vdd" || a == "0.8*vdd") {
    currentRef = AR_08VDD;
  } else if (a == "ext" || a == "1.25" || a == "1v25") {
    currentRef = AR_EXTERNAL_1V25;
  } else {
    Serial.println(F("# ERROR: unknown ref value. Use 1.2, 3.3, vdd, 0.8vdd, ext"));
    return;
  }

  analogReference(currentRef);
  doDummyRead();  // settle ADC
}

// Set ADC resolution (and do dummy read)
void handleRes(const String &args) {
  if (args.length() == 0) {
    Serial.println(F("# ERROR: res requires a bit depth (e.g. 8, 10, 12, 16)"));
    return;
  }
  long bits = args.toInt();
  if (bits < 8)  bits = 8;
  if (bits > 16) bits = 16;

  adcResolutionBits = (uint8_t)bits;
  analogReadResolution(adcResolutionBits);
  doDummyRead();  // settle ADC
}

// Handle sampling rate measurements

void printRateStats() {
  // Aggregate all per-channel-index timing into a single average.
  uint64_t totalSampleDeltaUs  = 0;
  uint32_t totalSampleCount    = 0;

  for (uint8_t i = 0; i < channelCount; i++) {
    totalSampleDeltaUs += sumDeltaPerIdx[i];
    totalSampleCount   += countDeltaPerIdx[i];
  }

  // Need both: between-channels stats and at least one per-channel delta.
  if (totalSampleCount == 0 || countBetweenChannelsUs == 0) {
    Serial.println(F("# ERROR: not enough timing data. "
                     "Run with start-rate enabled and capture some sweeps."));
    return;
  }

  float avgBetweenChannelsUs =
      (float)sumBetweenChannelsUs / (float)countBetweenChannelsUs;

  float avgSamplePeriodUs =
      (float)totalSampleDeltaUs / (float)totalSampleCount;

  // Minimal, machine-friendly output:
  //   #RATE,<avg_between_channels_us>,<avg_between_samples_us>
  Serial.print(F("#RATE,"));
  Serial.print(avgBetweenChannelsUs, 3);
  Serial.print(',');
  Serial.println(avgSamplePeriodUs, 3);
}


void handleStartRate(const String &args) {
  (void)args;
  if (channelCount == 0) {
    Serial.println(F("# ERROR: no channels configured. Use 'channels ...' first."));
    return;
  }

  resetRateStats();
  rateEnabled     = true;
  rateEverStarted = true;

  Serial.println(F("# rate measurement started"));
}

void handleEndRate(const String &args) {
  (void)args;
  rateEnabled = false;
  Serial.println(F("# rate measurement stopped (stats preserved)"));
}

void handleGetRate(const String &args) {
  (void)args;
  if (!rateEverStarted) {
    Serial.println(F("# ERROR: rate measurement not started. Use 'start-rate' first."));
    return;
  }
  printRateStats();
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

  Serial.print(F("# interSweepDelay_us: "));
  Serial.println(interSweepDelayUs);

  Serial.print(F("# repeatCount (samples per channel): "));
  Serial.println(repeatCount);

  Serial.print(F("# groundPin: "));
  Serial.println(groundPin);

  Serial.print(F("# useGroundBeforeEach: "));
  Serial.println(useGroundBeforeEach ? F("true") : F("false"));

  Serial.print(F("# adcResolutionBits: "));
  Serial.println(adcResolutionBits);

  Serial.print(F("# adcReference: "));
  switch (currentRef) {
    case AR_INTERNAL1V2:   Serial.println(F("INTERNAL1V2")); break;
    case AR_EXTERNAL_1V25: Serial.println(F("EXTERNAL_1V25")); break;
    case AR_VDD:           Serial.println(F("VDD")); break;
    case AR_08VDD:         Serial.println(F("0.8*VDD")); break;
    default:               Serial.println(F("UNKNOWN")); break;
  }

  Serial.println(F("# -------------------------"));
}

void printHelp() {
  Serial.println(F("# Commands:"));
  Serial.println(F("#   channels 0,1,1,1,2,2,3,4,5"));
  Serial.println(F("#   delay 50              (µs between sweeps)"));
  Serial.println(F("#   ground 2              (set ground pin)"));
  Serial.println(F("#   ground true|false     (enable/disable ground sampling)"));
  Serial.println(F("#   repeat 20             (samples per channel per sweep)"));
  Serial.println(F("#   ref 1.2 | 3.3 | vdd | 0.8vdd | ext"));
  Serial.println(F("#                        (set ADC reference)"));
  Serial.println(F("#   res 16                (set ADC resolution bits)"));
  Serial.println(F("#   run                   (continuous until 'stop')"));
  Serial.println(F("#   run 100               (~100 ms time-limited run)"));
  Serial.println(F("#   stop                  (stop running)"));
  Serial.println(F("#   status                (show configuration)"));
  Serial.println(F("#   start-rate            (start ADC timing measurement)"));   // NEW
  Serial.println(F("#   end-rate              (stop ADC timing measurement)"));    // NEW
  Serial.println(F("#   get-rate              (print timing statistics)"));        // NEW
  Serial.println(F("#   help                  (this message)"));
}

void handleRun(const String &args) {
  if (channelCount == 0) {
    Serial.println(F("# ERROR: no channels configured. Use 'channels ...' first."));
    return;
  }

  // New: reset timing statistics for a fresh measurement window
  resetRateStats();

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
  // NEW: make sure derived values match current config when we start
  recomputeDerivedConfig();
}

void handleStop() {
  isRunning = false;
  timedRun  = false;
}

// ---------------------------------------------------------------------
// One sweep = send a binary buffer, with repeatCount samples per channel
// ---------------------------------------------------------------------

void doOneSweep() {
  if (!isRunning || channelCount == 0 || samplesPerSweep == 0) return;

  // For timed runs: stop if time expired before starting a sweep
  if (timedRun) {
    uint32_t now = millis();
    if ((int32_t)(now - runStopMillis) >= 0) {
      isRunning = false;
      timedRun  = false;
      return;
    }
  }

  // Use precomputed "effective" ground pin (may be -1 if disabled)
  int sweepGroundPin = effectiveGroundCached;

  // Reset "previous channel in this sweep" marker for between-channel timing
  if (rateEnabled) {
    haveLastChannelStartUsInSweep = false;
  }

  // Fill buffer with all samples for this sweep
  uint16_t idx = 0;

  for (uint8_t i = 0; i < channelCount; i++) {
    uint8_t chanPin = channelSequence[i];

    for (uint16_t r = 0; r < repeatCount; r++) {
      if (useGroundBeforeEach && sweepGroundPin >= 0) {
        (void)analogRead(sweepGroundPin);  // discarded
      }

      // --- Timing measurement: only first sample of each channel, and only if enabled ---
      if (rateEnabled && r == 0) {
        uint32_t tStart = micros();

        // Per-channel index timing (same index i across sweeps)
        if (i < MAX_SEQUENCE_LEN) {
          if (hasLastStartPerIdx[i]) {
            uint32_t d = tStart - lastStartUsPerIdx[i];
            if (d < minDeltaPerIdx[i]) minDeltaPerIdx[i] = d;
            if (d > maxDeltaPerIdx[i]) maxDeltaPerIdx[i] = d;
            sumDeltaPerIdx[i]    += d;
            countDeltaPerIdx[i]  += 1;
            rateHasData           = true;
          }
          lastStartUsPerIdx[i]  = tStart;
          hasLastStartPerIdx[i] = true;
        }

        // Between-consecutive-channels timing (within this sweep)
        if (haveLastChannelStartUsInSweep) {
          uint32_t d2 = tStart - lastChannelStartUsInSweep;
          if (d2 < minBetweenChannelsUs) minBetweenChannelsUs = d2;
          if (d2 > maxBetweenChannelsUs) maxBetweenChannelsUs = d2;
          sumBetweenChannelsUs    += d2;
          countBetweenChannelsUs  += 1;
          rateHasData              = true;
        }
        lastChannelStartUsInSweep     = tStart;
        haveLastChannelStartUsInSweep = true;
      }
      // --- End timing measurement ---

      int adcRaw = analogRead(chanPin);
      if (idx < samplesPerSweep) {
        adcBuffer[idx++] = (uint16_t)adcRaw;
      }
      // No delay between samples!
    }
  }

  // Safety: in case of logic mismatch, clamp idx
  if (idx > samplesPerSweep) {
    idx = samplesPerSweep;
  }

  // Send one binary packet for the whole sweep
  sendSweepHeader(samplesPerSweep);
  Serial.write((uint8_t*)adcBuffer, (size_t)(idx * sizeof(uint16_t)));
  // No newline, no text.
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

  if      (cmd == "channels") { handleChannels(args); }
  else if (cmd == "delay")    { handleDelay(args); }
  else if (cmd == "ground")   { handleGround(args); }
  else if (cmd == "repeat")   { handleRepeat(args); }
  else if (cmd == "ref")      { handleRef(args); }
  else if (cmd == "res")      { handleRes(args); }
  else if (cmd == "run")      { handleRun(args); }
  else if (cmd == "stop")     { handleStop(); }
  else if (cmd == "status")   { printStatus(); }
  else if (cmd == "start-rate") { handleStartRate(args); }  // NEW
  else if (cmd == "end-rate")   { handleEndRate(args); }    // NEW
  else if (cmd == "get-rate")   { handleGetRate(args); }    // NEW
  else if (cmd == "help")     { printHelp(); }
  else {
    Serial.print(F("# ERROR: unknown command '"));
    Serial.print(cmd);
    Serial.println(F("'. Type 'help'."));
  }
}

// ---------------------------------------------------------------------
// setup() and loop()
// ---------------------------------------------------------------------

void setup() {
  Serial.begin(115200);
  while (!Serial) {
    ; // wait for USB serial
  }

  // Default ADC configuration for XIAO MG24
  analogReadResolution(adcResolutionBits); // 12 bits
  analogReference(currentRef);             // VDD
  doDummyRead();                           // initial settling

  recomputeDerivedConfig();   // NEW

  // (No banner here to keep stream clean; use 'status' if needed.)
}

void loop() {
  // 1) Handle incoming serial lines
  while (Serial.available() > 0) {
    char c = (char)Serial.read();
    if (c == '\r') continue;
    if (c == '\n') {
      handleLine(inputLine);
      inputLine = "";
    } else {
      inputLine += c;
      if (inputLine.length() > 200) {
        inputLine = "";
        Serial.println(F("# ERROR: input line too long; cleared."));
      }
    }
  }

  // 2) Run sweeps if requested
  if (isRunning) {
    doOneSweep();

    // NEW: delay between *sweeps* (if configured)
    if (interSweepDelayUs > 0) {
      delayMicroseconds(interSweepDelayUs);
    }
  
  }
}
