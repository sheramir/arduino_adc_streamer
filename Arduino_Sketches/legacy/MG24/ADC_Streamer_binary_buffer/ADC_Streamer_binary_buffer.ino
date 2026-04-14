/*
 * Interactive ADC Binary Sweeper with Blocked Output — XIAO MG24 / similar
 * ------------------------------------------------------------------------
 *
 * Core behavior:
 *   - You configure a list of channels with `channels ...`
 *   - You configure how many times to read each channel with `repeat N`
 *   - Each "sweep" is an ordered list of samples:
 *
 *        [ch0_r1, ch0_r2, ... ch0_rN, ch1_r1, ... chLast_rN]
 *
 *   - You configure how many sweeps to accumulate before sending with:
 *
 *        buffer B    (B = sweepsPerBlock)
 *
 *   - The Arduino fills a large RAM buffer with multiple sweeps, and only
 *     after B sweeps are captured, it sends ONE binary block to the host:
 *
 *      [0xAA][0x55][countL][countH] + count * uint16 samples + avg_dt_us (uint16)
 *
 *       where:
 *         - count  = total number of samples in this block (uint16_t),
 *                    so total data bytes = count * 2
 *
 *   - If a timed run or stop occurs with a partially filled block, the
 *     partial block is sent with the actual sample count.
 *
 * Ground sampling (optional):
 *   - If `ground true` is enabled, before each individual sample we perform
 *     a read from a "ground pin" (discarded, not sent) to help you do your
 *     own offset / reference corrections.
 *
 * ADC configuration commands:
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
 * Commands (one per line, via Serial @ BAUD_RATE, terminated by '*'):
 *
 *   channels 0,1,1,1,2,2,3,4,5*
 *     - Set the ADC sweep sequence (Arduino pin numbers, duplicates allowed).
 *
 *   ground 2*
 *     - Set "ground" pin (physically tied to GND).
 *
 *   ground true*
 *   ground false*
 *     - Enable/disable ground sampling before each individual capture.
 *       Ground reading is DISCARDED (not sent).
 *
 *   repeat 20*
 *     - For each channel in the sequence, capture it 20 times per sweep.
 *
 *   buffer 10*
 *     - Accumulate 10 sweeps in the ADC buffer before sending one block.
 *       Each block has (10 * samplesPerSweep) samples.
 *       buffer 1 = send one sweep per block (like old behavior).
 *
 *   ref 1.2*
 *   ref 3.3*
 *   ref vdd*
 *   ref 0.8vdd*
 *   ref ext*
 *     - Set ADC reference as described above.
 *
 *   res 16*
 *     - Set ADC resolution (bits). Typical useful values: 8,10,12,16.
 *
 *   run*
 *     - Continuous run (sweeps forever) until 'stop' is received.
 *
 *   run 100*
 *     - Timed run: sweeps for ~100 ms then stops automatically.
 *       Any partially filled block is sent at the end.
 *
 *   stop*
 *     - Stop running, send any partial block, stay in command mode.
 *
 *   status*
 *     - Print current configuration (with '#'-prefixed lines).
 *
 *   help*
 *     - Print help text (with '#'-prefixed lines).
 *
 * BINARY OUTPUT WHILE RUNNING:
 *   - Data comes in BLOCKS, not lines of text.
 *   - Each block:
 *
 *       [0xAA][0x55][countL][countH][sample0_lo][sample0_hi]...[sample(count-1)]
 *
 *     where:
 *       - count = total number of samples in this block
 *       - Each sample is uint16_t in little-endian
 *
 *   - Host side must:
 *       1) Read 4-byte header, check 0xAA, 0x55
 *       2) Parse count = header[2] | (header[3] << 8)
 *       3) Read count * 2 bytes of sample data
 *       4) Use its knowledge of (channels, repeat, buffer) to reshape
 *          into [block_sweep_index][channel][repeat] as desired.
 */

#include <Arduino.h>

// ---------------------------------------------------------------------
// Limits & defaults
// ---------------------------------------------------------------------

const uint8_t  MAX_SEQUENCE_LEN  = 16;     // Maximum number of channels in a sequence
const uint32_t BAUD_RATE         = 460800; // Working high-speed baud

// We DON'T want to use all 256kB of RAM for the ADC buffer.
// Each sample is uint16_t (2 bytes). With 32000 samples, this is 64kB.
// This leaves plenty of RAM for stack, heap, Serial buffers, and other code.
const uint32_t MAX_SAMPLES_BUFFER = 32000; // 32000 * 2 bytes = 64kB

// ---------------------------------------------------------------------
// Command framing constants
// ---------------------------------------------------------------------

static const char     CMD_TERMINATOR   = '*';    // '*' ends a command
static const uint16_t MAX_CMD_LENGTH   = 512;    // Max input line length

// ---------------------------------------------------------------------
// Configuration state
// ---------------------------------------------------------------------

uint8_t  channelSequence[MAX_SEQUENCE_LEN]; // channels in the sweep
uint8_t  channelCount        = 0;           // how many channels

int      groundPin           = -1;          // -1 = not set
bool     useGroundBeforeEach = false;       // read ground before each sample?

// repeatCount = number of ADC readings per channel per sweep
uint16_t repeatCount         = 1;

// ADC configuration state
uint8_t  adcResolutionBits   = 12;          // default 12-bit for XIAO MG24
analog_references currentRef = AR_VDD;      // default reference = VDD

// Maximum repeat count we support
const uint16_t MAX_REPEAT_COUNT = 100;

// ADC sample buffer for multiple sweeps
// MAX_SAMPLES_BUFFER * 2 bytes = 64 kB of RAM.
uint16_t adcBuffer[MAX_SAMPLES_BUFFER];

// Derived config values (recomputed when config changes)
uint16_t samplesPerSweep       = 0;  // channelCount * repeatCount
int      effectiveGroundCached = -1; // ground pin actually used for dummy reads

// Blocked/buffered sweeps:
uint16_t sweepsPerBlock        = 1;  // how many sweeps to store before sending
uint16_t sweepsInCurrentBlock  = 0;  // how many sweeps currently accumulated

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
// Timing measurement: start time for current block
// ---------------------------------------------------------------------

uint32_t blockStartMicros = 0;  // micros() when first sample of block is taken


// ---------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------

// Convert to lowercase and trim whitespace
String toLowerTrim(const String &s) {
  String t = s;
  t.trim();
  t.toLowerCase();
  return t;
}

// Split a line into "cmd" and "args" (first token vs rest of line)
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
// Command acknowledgment helper
// ---------------------------------------------------------------------
void sendCommandAck(bool ok, const String &args) {

  // Send acknowledgment line
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

  // Ensure it is actually sent out on USB before we continue
  Serial.flush();

  // Tiny delay to give host side time to react, and to avoid
  // back-to-back command overruns when the PC is very fast.
  delay(5);  // 1–5 ms is usually enough
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

  // Make sure sweepsPerBlock * samplesPerSweep fits into adcBuffer
  if (samplesPerSweep == 0) {
    sweepsPerBlock       = 1; // meaningless but safe
    sweepsInCurrentBlock = 0;
    return;
  }

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

  // If configuration changed drastically, reset current block
  if ((uint32_t)sweepsInCurrentBlock * samplesPerSweep > MAX_SAMPLES_BUFFER) {
    sweepsInCurrentBlock = 0;
  }
}

// ---------------------------------------------------------------------
// Binary sweep/block output helpers
// ---------------------------------------------------------------------

const uint8_t SWEEP_MAGIC1 = 0xAA;
const uint8_t SWEEP_MAGIC2 = 0x55;

// Send 4-byte header: [0xAA][0x55][countL][countH]
void sendSweepHeader(uint16_t totalSamples) {
  uint8_t header[4];
  header[0] = SWEEP_MAGIC1;
  header[1] = SWEEP_MAGIC2;
  header[2] = (uint8_t)(totalSamples & 0xFF);
  header[3] = (uint8_t)(totalSamples >> 8);
  Serial.write(header, 4);
}

// Send an entire block (one or more sweeps) currently in adcBuffer
void sendBlock(uint16_t sampleCount, uint32_t blockEndMicros) {
  if (sampleCount == 0) return;

  uint32_t totalSamples = sampleCount;
  if (totalSamples > MAX_SAMPLES_BUFFER) {
    totalSamples = MAX_SAMPLES_BUFFER;
  }

  // Compute total time and average time per sample (µs)
  uint32_t totalTimeUs   = blockEndMicros - blockStartMicros;  // micros() wrap handled by unsigned math
  uint32_t avgSampleDtUs = (totalSamples > 0) ? (totalTimeUs / totalSamples) : 0;

  // Clamp to uint16; we know this will be much smaller in practice
  uint16_t avgSampleDtUs16 = (avgSampleDtUs <= 65535u)
                               ? (uint16_t)avgSampleDtUs
                               : (uint16_t)65535u;

  // 1) Header: count = number of samples
  sendSweepHeader((uint16_t)totalSamples);

  // 2) Samples (unchanged)
  Serial.write((uint8_t*)adcBuffer, (size_t)(totalSamples * sizeof(uint16_t)));

  // 3) Append average per-sample time [µs] as uint16 LE (2 bytes)
  uint8_t rateBytes[2];
  rateBytes[0] = (uint8_t)(avgSampleDtUs16 & 0xFF);
  rateBytes[1] = (uint8_t)(avgSampleDtUs16 >> 8);
  Serial.write(rateBytes, 2);

  // Reset timing state for next block
  blockStartMicros = 0;
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
      continue;  // ignore invalid, not a fatal error for the whole command
    }

    channelSequence[channelCount++] = (uint8_t)val;
  }

  if (channelCount == 0) {
    Serial.println(F("# ERROR: no valid channels parsed."));
    recomputeDerivedConfig();
    return false;
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
    if (groundPin < 0) {
      groundPin = 0;  // default if not set
    }
  } else if (a == "false") {
    useGroundBeforeEach = false;
  } else {
    int pin = a.toInt();
    if (pin < 0 || pin > 255) {
      Serial.println(F("# ERROR: ground pin out of range (0-255)"));
      return false;
    }
    groundPin = pin;
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
  if (val > MAX_REPEAT_COUNT) val = MAX_REPEAT_COUNT;

  repeatCount = (uint16_t)val;
  recomputeDerivedConfig();
  return true;
}

// New: set sweepsPerBlock (buffer size = number of sweeps)
bool handleBuffer(const String &args) {
  if (args.length() == 0) {
    Serial.println(F("# ERROR: buffer requires a positive integer (sweeps per block)"));
    return false;
  }

  long val = args.toInt();
  if (val <= 0) val = 1;

  sweepsPerBlock = (uint16_t)val;
  // Re-apply capacity limits
  recomputeDerivedConfig();

  // Reset current partial block whenever buffer size changes
  sweepsInCurrentBlock = 0;
  return true;
}

// Set ADC reference (and do dummy read)
bool handleRef(const String &args) {
  if (args.length() == 0) {
    Serial.println(F("# ERROR: ref requires a value (1.2, 3.3, vdd, 0.8vdd, ext)"));
    return false;
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
    return false;
  }

  analogReference(currentRef);
  doDummyRead();  // settle ADC
  return true;
}

// Set ADC resolution (and do dummy read)
bool handleRes(const String &args) {
  if (args.length() == 0) {
    Serial.println(F("# ERROR: res requires a bit depth (e.g. 8, 10, 12, 16)"));
    return false;
  }
  long bits = args.toInt();
  if (bits < 8)  bits = 8;
  if (bits > 16) bits = 16;

  adcResolutionBits = (uint8_t)bits;
  analogReadResolution(adcResolutionBits);
  doDummyRead();  // settle ADC
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

  // Reset current block when starting a run
  sweepsInCurrentBlock = 0;
  recomputeDerivedConfig();
  return true;
}

void handleStop() {
  isRunning = false;
  timedRun  = false;
}


// ---------------------------------------------------------------------
// Sweeps are captured into a big block buffer; when all sweeps are
// captured, send the block in binary.
// ---------------------------------------------------------------------
void doOneBlock() {
  if (!isRunning || channelCount == 0 || samplesPerSweep == 0) return;

  // How many samples in a full block?
  uint32_t totalSamples = (uint32_t)sweepsPerBlock * (uint32_t)samplesPerSweep;
  if (totalSamples > MAX_SAMPLES_BUFFER) {
    totalSamples = MAX_SAMPLES_BUFFER;  // recomputeDerivedConfig should prevent this, but safety
  }

  // Start timing at the FIRST sample of the block
  blockStartMicros = micros();

  uint32_t idx = 0;
  int sweepGroundPin = effectiveGroundCached;

  // Triple loop: sweeps → channels → repeats
  for (uint16_t s = 0; s < sweepsPerBlock; s++) {
    for (uint8_t i = 0; i < channelCount; i++) {
      uint8_t chanPin = channelSequence[i];

      // If "ground true": ONE dummy ground read per channel per sweep
      if (useGroundBeforeEach && sweepGroundPin >= 0) {
        (void)analogRead(sweepGroundPin);  // discarded
      }

      for (uint16_t r = 0; r < repeatCount; r++) {
        if (idx >= totalSamples) break;  // safety

        int adcRaw = analogRead(chanPin);
        adcBuffer[idx++] = (uint16_t)adcRaw;
      }
    }
  }

  // End timing right after the last sample of the block (before sending)
  uint32_t blockEndMicros = micros();

  // Send the block: samples + timing info
  sendBlock((uint16_t)idx, blockEndMicros);
}



// ---------------------------------------------------------------------
// Status / help
// ---------------------------------------------------------------------

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
    case AR_VDD:           Serial.println(F("VDD"));          break;
    case AR_08VDD:         Serial.println(F("0.8*VDD"));      break;
    default:               Serial.println(F("UNKNOWN"));      break;
  }

  Serial.print(F("# samplesPerSweep: "));
  Serial.println(samplesPerSweep);

  Serial.print(F("# sweepsPerBlock: "));
  Serial.println(sweepsPerBlock);

  Serial.print(F("# sweepsInCurrentBlock: "));
  Serial.println(sweepsInCurrentBlock);

  Serial.print(F("# MAX_SAMPLES_BUFFER: "));
  Serial.println(MAX_SAMPLES_BUFFER);

  Serial.println(F("# -------------------------"));
}

void printHelp() {
  Serial.println(F("# Commands:"));
  Serial.println(F("#   channels 0,1,1,1,2,2,3,4,5"));
  Serial.println(F("#   ground 2              (set ground pin)"));
  Serial.println(F("#   ground true|false     (enable/disable ground sampling)"));
  Serial.println(F("#   repeat 20             (samples per channel per sweep)"));
  Serial.println(F("#   buffer 10             (sweeps per binary block)"));
  Serial.println(F("#   ref 1.2 | 3.3 | vdd | 0.8vdd | ext"));
  Serial.println(F("#                        (set ADC reference)"));
  Serial.println(F("#   res 16                (set ADC resolution bits)"));
  Serial.println(F("#   run                   (continuous until 'stop')"));
  Serial.println(F("#   run 100               (~100 ms time-limited run)"));
  Serial.println(F("#   stop                  (stop running)"));
  Serial.println(F("#   status                (show configuration)"));
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
  else if (cmd == "res")         { ok = handleRes(args); }
  else if (cmd == "run")         { ok = handleRun(args); }
  else if (cmd == "stop")        { handleStop(); ok = true; }
  else if (cmd == "status")      { printStatus(); ok = true; }
  else if (cmd == "help")        { printHelp();  ok = true; }
  else {
    Serial.print(F("# ERROR: unknown command '"));
    Serial.print(cmd);
    Serial.println(F("'. Type 'help'."));
    ok = false;
  }

  // Send acknowledgment (#OK or #NOT_OK) AFTER command is fully processed.
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

  // Default ADC configuration for XIAO MG24
  analogReadResolution(adcResolutionBits); // 12 bits
  analogReference(currentRef);             // VDD
  doDummyRead();                           // initial settling

  recomputeDerivedConfig();

  // You can print help or status here if you want:
  // printHelp();
  // printStatus();
}

void loop() {
  // 1) Handle incoming serial bytes (command parser)
  while (Serial.available() > 0) {
    char c = (char)Serial.read();

    // Ignore CR/LF entirely
    if (c == '\r' || c == '\n') {
      continue;
    }

    if (c == CMD_TERMINATOR) {
      // '*' means "end of command" IF we already have some text
      if (inputLine.length() > 0) {
        // We have a complete command: process it
        handleLine(inputLine);
        inputLine = "";
      }
      // If inputLine is empty, this is leading or extra '*':
      // just ignore it. This gives you redundancy (***).
      continue;
    }

    // Any non-'*' character is part of the command text
    inputLine += c;

    // Optional safety: prevent runaway growth
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
    doOneBlock();   // this captures the entire block without returning
  }
}
