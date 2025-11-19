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
 *     - Delay between SUCCESSIVE captures (within the same sweep), in µs.
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

const uint8_t  MAX_SEQUENCE_LEN  = 64;
const uint32_t DEFAULT_DELAY_US  = 0;

// ---------------------------------------------------------------------
// Configuration state
// ---------------------------------------------------------------------

uint8_t  channelSequence[MAX_SEQUENCE_LEN];
uint8_t  channelCount        = 0;

int      groundPin           = -1;   // -1 = not set
bool     useGroundBeforeEach = false;

uint32_t interSampleDelayUs  = DEFAULT_DELAY_US;

// repeatCount = number of ADC readings per channel per sweep
uint16_t repeatCount         = 1;

// ADC configuration state
uint8_t  adcResolutionBits   = 12;   // default 12-bit for XIAO MG24
analog_references currentRef = AR_VDD; // default reference = VDD

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
}

void handleDelay(const String &args) {
  if (args.length() == 0) {
    Serial.println(F("# ERROR: delay requires a value in microseconds"));
    return;
  }
  long val = args.toInt();
  if (val < 0) val = 0;
  interSampleDelayUs = (uint32_t)val;
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
  }
}

void handleRepeat(const String &args) {
  if (args.length() == 0) {
    Serial.println(F("# ERROR: repeat requires a positive integer"));
    return;
  }
  long val = args.toInt();
  if (val <= 0) val = 1;
  if (val > 1000) val = 1000; // some upper bound to avoid huge lines

  repeatCount = (uint16_t)val;
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

  Serial.print(F("# delay_us: "));
  Serial.println(interSampleDelayUs);

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
  Serial.println(F("#   delay 50              (µs between captures)"));
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
  Serial.println(F("#   help                  (this message)"));
}

void handleRun(const String &args) {
  if (channelCount == 0) {
    Serial.println(F("# ERROR: no channels configured. Use 'channels ...' first."));
    return;
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
}

void handleStop() {
  isRunning = false;
  timedRun  = false;
}

// ---------------------------------------------------------------------
// One sweep = one CSV line, with repeatCount samples per channel
// ---------------------------------------------------------------------

void doOneSweep() {
  if (!isRunning || channelCount == 0) return;

  // For timed runs: stop if time expired before starting a sweep
  if (timedRun) {
    uint32_t now = millis();
    if ((int32_t)(now - runStopMillis) >= 0) {
      isRunning = false;
      timedRun  = false;
      return;
    }
  }

  int effectiveGroundPin = groundPin;
  if (useGroundBeforeEach && effectiveGroundPin < 0) {
    effectiveGroundPin = (channelCount > 0) ? channelSequence[0] : 0;
  }

  // Sweep structure:
  //   for each channel i:
  //     for repeatCount times:
  //       [optional ground read] + one channel read
  //   all concatenated into one CSV line
  for (uint8_t i = 0; i < channelCount; i++) {
    uint8_t chanPin = channelSequence[i];

    for (uint16_t r = 0; r < repeatCount; r++) {
      if (useGroundBeforeEach) {
        (void)analogRead(effectiveGroundPin); // discarded
      }

      int adcRaw = analogRead(chanPin);

      bool lastValue = (i == channelCount - 1) && (r == repeatCount - 1);
      Serial.print(adcRaw);
      if (!lastValue) {
        Serial.print(',');
      }

      if (interSampleDelayUs > 0 && !lastValue) {
        delayMicroseconds(interSampleDelayUs);
      }
    }
  }

  Serial.println();
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
  }
}
