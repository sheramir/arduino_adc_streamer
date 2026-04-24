/*
 * Teensy_SPI_Master_Array_PZT1.ino
 * Teensy 4.1 — SPI Master + Python Serial Bridge
 * ================================================
 * Bridges the Python host (same text serial API as the README) to the
 * XIAO MG24 running MG24_Dual_MUX_SPI_Slave.ino.
 *
 * SPI transport is identical to SPI_Master_test3_Claude:
 *   - Uses default SPI (SPI0) — same pins as test3
 *   - SPI_BITRATE Hz, MSB-first, SPI_MODE1
 *   - No DRDY pin.  After sending a command, Teensy waits a computed
 *     delay then reads the response in a second CS transaction.
 *
 * Identified to the Python host as "Array_PZT1":
 *   mcu*  →  # Array_PZT1
 *
 * ── Wiring (identical to SPI_Master_test3_Claude) ─────────────────────
 *   Teensy 10 (CS)   → MG24 D0   (CS,   PC0)
 *   Teensy 13 (SCK)  → MG24 D8   (SCK,  PA3)
 *   Teensy 11 (MOSI) → MG24 D10  (MOSI, PA5)
 *   Teensy 12 (MISO) ← MG24 D9   (MISO, PA4)
 *   Common GND
 *
 * ── No-DRDY timing model ──────────────────────────────────────────────
 *   Config commands : delay CONFIG_ACK_DELAY_MS, then read ACK_FRAME_LEN bytes.
 *   First RUN block : delay warmupDelayMs() + blockDelayMs(), then read block.
 *   Subsequent blocks : delay blockDelayMs(), then read block.
 *   blockDelayMs() = (channelCount × repeatCount × sweepsPerBlock × US_PER_PAIR_OSR)
 *                    / 1000  +  BLOCK_DELAY_MARGIN_MS
 *   US_PER_PAIR_OSR is the estimated µs to capture one (MUX1, MUX2) pair:
 *     MUX settle (MUX_SETTLE_US) + 2 × IADC conversion (OSR-dependent)
 */

#include <Arduino.h>
#include <SPI.h>

// =====================================================================
// ── USER-CONFIGURABLE CONSTANTS ──────────────────────────────────────
// =====================================================================

// ── Teensy SPI0 (default SPI) chip-select pin ─────────────────────────
// Uses the same default SPI bus as SPI_Master_test3_Claude:
//   CS=10 (manual GPIO), SCK=13, MOSI=11, MISO=12
static const uint8_t CS_PIN              = 10;

// ── SPI transport ─────────────────────────────────────────────────────
static const uint32_t SPI_BITRATE        = 4000000UL; // 4 MHz

// ── CS setup time ─────────────────────────────────────────────────────
// Short pause between asserting CS and the first SCK edge (same as test3).
static const uint32_t CS_SETUP_US        = 10;

// ── Python-host serial ────────────────────────────────────────────────
static const uint32_t SERIAL_BAUD        = 460800;
static const char     CMD_TERM           = '*';
static const uint16_t MAX_CMD_LEN        = 512;
static const bool     DEBUG_TEXT_STREAM  = false; // if true, prints human-readable block info and samples instead of raw bytes

// ── Protocol frame sizes (must match MG24 sketch) ─────────────────────
static const uint8_t  CMD_FRAME_LEN      = 20;   // fixed command TX frame (bytes)
static const uint8_t  ACK_FRAME_LEN      = 4;    // fixed ACK RX frame (bytes)
static const uint8_t  BLOCK_TRAILER_LEN  = 10;   // avg_dt(2) + start_us(4) + end_us(4)
static const uint8_t  BLOCK_MAGIC1       = 0xAA;
static const uint8_t  BLOCK_MAGIC2       = 0x55;
static const uint8_t  ACK_MAGIC          = 0xAC;
static const uint8_t  ACK_STATUS_OK      = 0x00;

// ── Timing: config command ACK ────────────────────────────────────────
// Time (ms) to wait after sending any non-RUN command before reading the
// 4-byte ACK.  Covers MG24 command processing time.
static const uint32_t CONFIG_ACK_DELAY_MS   = 20;
static const uint32_t INTER_BLOCK_CMD_DELAY_MS = 0;

// ── Timing: MUX settling (must match MG24 MUX_SETTLE_US) ─────────────
// Used in blockDelayMs() to estimate per-pair capture time.
static const uint32_t MUX_SETTLE_US         = 30;

// ── Timing: IADC conversion time per sample (µs) per OSR setting ─────
// Approximate IADC conversion time for one 12-bit sample at 10 MHz ADC clock.
// OSR 2x ≈ 2 µs,  4x ≈ 4 µs,  8x ≈ 8 µs.
// One pair = 2 samples (MUX1 + MUX2), so multiply by 2 in blockDelayMs().
static const uint32_t IADC_CONV_US_OSR2     = 25;
static const uint32_t IADC_CONV_US_OSR4     = 35;
static const uint32_t IADC_CONV_US_OSR8     = 60;

// ── Timing: safety margins ────────────────────────────────────────────
// Extra ms added to block delay to cover jitter, interrupt latency, etc.
static const uint32_t BLOCK_DELAY_MARGIN_MS = 25;
// Extra ms added to warmup delay.
static const uint32_t WARMUP_DELAY_MARGIN_MS = 20;

// ── Warmup sweeps (must match MG24 WARMUP_SWEEPS) ─────────────────────
// Used only for timing estimation on the Teensy side.
static const uint16_t WARMUP_SWEEPS         = 48;

// ── Protocol limits ───────────────────────────────────────────────────
static const uint16_t MAX_REPEAT            = 100;
static const uint8_t  MUX_CH_MAX            = 15;
// Maximum (MUX1,MUX2) pairs per block — must match MG24 MAX_PAIRS.
// Used to size the local RX buffer.
static const uint32_t MAX_PAIRS             = 8000UL;

// =====================================================================
// ── END USER-CONFIGURABLE CONSTANTS ──────────────────────────────────
// =====================================================================

// Derived: maximum bytes in one data block response
static const uint32_t MAX_BLOCK_BYTES =
    (uint32_t)ACK_FRAME_LEN + MAX_PAIRS * 4UL + BLOCK_TRAILER_LEN;

// ── Command codes (must match MG24 sketch) ────────────────────────────
static const uint8_t CMD_SET_CHANNELS  = 0x01;
static const uint8_t CMD_SET_REPEAT    = 0x02;
static const uint8_t CMD_SET_BUFFER    = 0x03;
static const uint8_t CMD_SET_REF       = 0x04;
static const uint8_t CMD_SET_OSR       = 0x05;
static const uint8_t CMD_SET_GAIN      = 0x06;
static const uint8_t CMD_RUN           = 0x07;
static const uint8_t CMD_STOP          = 0x08;
static const uint8_t CMD_MCU_ID        = 0x0A;
static const uint8_t CMD_GROUND_PIN    = 0x0B;
static const uint8_t CMD_GROUND_EN     = 0x0C;
static const uint8_t CMD_CONTINUE      = 0x0D;  // request next streaming block
static const uint8_t STREAM_NOP        = 0x00;

// ── SPI bus (default SPI0, same as test3) ────────────────────────────
static SPIClass &mg24SPI = SPI;
static const SPISettings SPI_CFG(SPI_BITRATE, MSBFIRST, SPI_MODE1);

// ── Cached configuration (for delay calculation & local responses) ────
struct Config {
  uint8_t  channels[16];
  uint8_t  channelCount   = 0;
  uint8_t  repeatCount    = 1;
  uint8_t  sweepsPerBlock = 1;
  uint8_t  osr            = 2;    // 2 | 4 | 8
  uint8_t  gain           = 1;    // 1-4
  uint8_t  ref            = 1;    // 0=1.2V  1=VDD
  uint8_t  groundPin      = 0;
  bool     groundEnable   = false;
  bool     running        = false;
} cfg;

// ── SPI helpers ───────────────────────────────────────────────────────
static void spiTransferBytes(const uint8_t *txBuf, uint8_t *rxBuf, uint16_t len) {
  mg24SPI.beginTransaction(SPI_CFG);
  digitalWrite(CS_PIN, LOW);
  delayMicroseconds(CS_SETUP_US);
  for (uint16_t i = 0; i < len; i++) {
    uint8_t tx = txBuf ? txBuf[i] : 0x00;
    uint8_t rx = mg24SPI.transfer(tx);
    if (rxBuf) rxBuf[i] = rx;
  }
  digitalWrite(CS_PIN, HIGH);
  mg24SPI.endTransaction();
}

static void spiSendBytes(const uint8_t *buf, uint16_t len) {
  spiTransferBytes(buf, nullptr, len);
}

static void spiRecvBytes(uint8_t *buf, uint16_t len) {
  spiTransferBytes(nullptr, buf, len);
}

// Read a streaming response where the first transmitted byte can carry a
// control token for the MG24 streaming state machine.
static bool spiRecvStreamingResponse(uint8_t *buf,
                                     uint16_t len,
                                     uint8_t controlByte = STREAM_NOP,
                                     uint8_t maxAttempts = 4) {
  for (uint8_t attempt = 0; attempt < maxAttempts; ++attempt) {
    mg24SPI.beginTransaction(SPI_CFG);
    digitalWrite(CS_PIN, LOW);
    delayMicroseconds(CS_SETUP_US);
    if (len > 0) {
      buf[0] = mg24SPI.transfer(controlByte);
      for (uint16_t i = 1; i < len; i++) buf[i] = mg24SPI.transfer(0x00);
    }
    digitalWrite(CS_PIN, HIGH);
    mg24SPI.endTransaction();

    if (buf[0] == ACK_MAGIC) return true;
    if (buf[0] == BLOCK_MAGIC1 && buf[1] == BLOCK_MAGIC2) return true;
    delayMicroseconds(250 + attempt * 250);
  }
  return false;
}

static bool spiRecvAckResponse(uint8_t *buf, uint8_t maxAttempts = 4) {
  for (uint8_t attempt = 0; attempt < maxAttempts; ++attempt) {
    spiRecvBytes(buf, ACK_FRAME_LEN);
    if (buf[0] == ACK_MAGIC) return true;
    delayMicroseconds(200 + attempt * 200);
  }
  return false;
}

static void writeBlockToHostBuffered(const uint8_t *buf, uint32_t len) {
  uint32_t offset = 0;
  while (offset < len) {
    int writable = Serial.availableForWrite();
    if (writable <= 0) {
      yield();
      continue;
    }

    uint32_t chunk = min((uint32_t)writable, len - offset);
    offset += (uint32_t)Serial.write(buf + offset, chunk);
  }
}

static void emitBlockToHost(const uint8_t *buf, uint32_t len) {
  if (!DEBUG_TEXT_STREAM) {
    writeBlockToHostBuffered(buf, len);
    return;
  }

  if (len < (uint32_t)ACK_FRAME_LEN + BLOCK_TRAILER_LEN) {
    Serial.println(F("#DBG short block"));
    Serial.flush();
    return;
  }

  if (buf[0] != BLOCK_MAGIC1 || buf[1] != BLOCK_MAGIC2) {
    Serial.print(F("#DBG non-block first bytes: "));
    Serial.print(buf[0], HEX);
    Serial.print(' ');
    Serial.println(buf[1], HEX);
    Serial.flush();
    return;
  }

  uint16_t sampleCount = (uint16_t)buf[2] | ((uint16_t)buf[3] << 8);
  uint32_t payloadBytes = (uint32_t)sampleCount * 2u;
  uint32_t trailerOffset = (uint32_t)ACK_FRAME_LEN + payloadBytes;
  if (trailerOffset + BLOCK_TRAILER_LEN > len) {
    Serial.println(F("#DBG malformed block length"));
    Serial.flush();
    return;
  }

  uint16_t avgDtUs = (uint16_t)buf[trailerOffset] | ((uint16_t)buf[trailerOffset + 1] << 8);
  uint32_t blockStartUs =
      ((uint32_t)buf[trailerOffset + 2])
    | ((uint32_t)buf[trailerOffset + 3] << 8)
    | ((uint32_t)buf[trailerOffset + 4] << 16)
    | ((uint32_t)buf[trailerOffset + 5] << 24);
  uint32_t blockEndUs =
      ((uint32_t)buf[trailerOffset + 6])
    | ((uint32_t)buf[trailerOffset + 7] << 8)
    | ((uint32_t)buf[trailerOffset + 8] << 16)
    | ((uint32_t)buf[trailerOffset + 9] << 24);

  Serial.print(F("#DBG block samples="));
  Serial.print(sampleCount);
  Serial.print(F(" pairs="));
  Serial.print(sampleCount / 2u);
  Serial.print(F(" avg_dt_us="));
  Serial.print(avgDtUs);
  Serial.print(F(" start_us="));
  Serial.print(blockStartUs);
  Serial.print(F(" end_us="));
  Serial.println(blockEndUs);

  uint32_t samplesPerSweep = (uint32_t)cfg.channelCount * cfg.repeatCount * 2u;
  if (samplesPerSweep == 0) {
    Serial.println(F("#DBG samplesPerSweep=0"));
    Serial.flush();
    return;
  }

  for (uint32_t base = 0; base < sampleCount; base += samplesPerSweep) {
    Serial.print(F("#DBG sweep "));
    Serial.print(base / samplesPerSweep);
    Serial.print(F(": "));
    for (uint32_t i = 0; i < samplesPerSweep && (base + i) < sampleCount; ++i) {
      uint32_t byteIdx = (uint32_t)ACK_FRAME_LEN + (base + i) * 2u;
      uint16_t value = (uint16_t)buf[byteIdx] | ((uint16_t)buf[byteIdx + 1] << 8);
      Serial.print(value);
      if (i + 1 < samplesPerSweep && (base + i + 1) < sampleCount) {
        Serial.print(',');
      }
    }
    Serial.println();
  }
  Serial.flush();
}

// The GUI sends commands terminated with "***". Once handleRun() starts,
// any extra '*' bytes still pending in the USB serial RX buffer would look
// like a user-issued stop request unless we discard them first.
static void discardPendingCommandTerminators(uint32_t settleMs = 10) {
  uint32_t start = millis();
  while ((millis() - start) < settleMs) {
    while (Serial.available() > 0) {
      char c = (char)Serial.read();
      if (c != CMD_TERM && c != '\r' && c != '\n') {
        // Ignore any unexpected trailing bytes from the just-finished command.
      }
    }
    delay(1);
  }
}

// Build and send a command frame (always CMD_FRAME_LEN bytes).
static void sendCmd(uint8_t cmd, const uint8_t *args = nullptr, uint8_t nargs = 0) {
  uint8_t frame[CMD_FRAME_LEN];
  memset(frame, 0, CMD_FRAME_LEN);
  frame[0] = cmd;
  frame[1] = nargs;
  if (args && nargs > 0) {
    uint8_t n = min(nargs, (uint8_t)(CMD_FRAME_LEN - 2));
    memcpy(frame + 2, args, n);
  }
  spiSendBytes(frame, CMD_FRAME_LEN);
}

// ── Timing helpers ────────────────────────────────────────────────────
// Estimated µs to capture one (MUX1, MUX2) pair at the current OSR.
static uint32_t usPerPair() {
  uint32_t convUs = (cfg.osr == 8) ? IADC_CONV_US_OSR8 :
                    (cfg.osr == 4) ? IADC_CONV_US_OSR4 : IADC_CONV_US_OSR2;
  return MUX_SETTLE_US + convUs * 2u; // settle + two IADC conversions
}

// Delay (ms) for the Teensy to wait before reading one data block.
static uint32_t blockDelayMs() {
  uint32_t pairs = (uint32_t)cfg.channelCount * cfg.repeatCount * cfg.sweepsPerBlock;
  return (pairs * usPerPair()) / 1000u + BLOCK_DELAY_MARGIN_MS;
}

// Extra delay (ms) for the 48-sweep warmup that happens before the first block.
static uint32_t warmupDelayMs() {
  uint32_t warmupPairs = (uint32_t)WARMUP_SWEEPS * cfg.channelCount;
  return (warmupPairs * usPerPair()) / 1000u + WARMUP_DELAY_MARGIN_MS;
}

// Total bytes in one data block response from MG24.
static uint32_t blockResponseBytes() {
  uint32_t sampleCount = (uint32_t)cfg.channelCount * cfg.repeatCount
                       * cfg.sweepsPerBlock * 2u; // ×2: MUX1 + MUX2
  return (uint32_t)ACK_FRAME_LEN + sampleCount * 2u + BLOCK_TRAILER_LEN;
}

// ── ACK helper ────────────────────────────────────────────────────────
// Prints "#OK <args>" or "#NOT_OK <args>" to the Python host.
// All command handlers return bool; handleLine calls this once at the end.
// Exception: handleRun() calls this itself before streaming starts (it is
// blocking, so the ack must be sent before data flows, not after).
static void hostAck(bool ok, const String &args = "") {
  if (ok) {
    if (args.length()) { Serial.print(F("#OK ")); Serial.println(args); }
    else                Serial.println(F("#OK"));
  } else {
    if (args.length()) { Serial.print(F("#NOT_OK ")); Serial.println(args); }
    else                Serial.println(F("#NOT_OK"));
  }
  Serial.flush();
  delay(5);
}

// Send a command, wait CONFIG_ACK_DELAY_MS, read 4-byte ACK.
// Returns true if ACK indicates OK.
static bool sendCmdAndReadAck(uint8_t cmd,
                               const uint8_t *args = nullptr,
                               uint8_t nargs = 0) {
  sendCmd(cmd, args, nargs);
  delay(CONFIG_ACK_DELAY_MS);
  uint8_t ack[ACK_FRAME_LEN] = {0};
  spiRecvBytes(ack, ACK_FRAME_LEN);
  return (ack[0] == ACK_MAGIC && ack[1] == ACK_STATUS_OK);
}

// ── Command handlers — each returns bool (ok/fail) ────────────────────

static bool handleChannels(const String &args) {
  cfg.channelCount = 0;
  int i = 0, len = args.length();
  while (i < len && cfg.channelCount < 16) {
    while (i < len && (args[i] == ' ' || args[i] == ',')) i++;
    if (i >= len) break;
    int start = i;
    while (i < len && args[i] != ' ' && args[i] != ',') i++;
    int v = args.substring(start, i).toInt();
    if (v >= 0 && v <= (int)MUX_CH_MAX) cfg.channels[cfg.channelCount++] = (uint8_t)v;
  }
  if (cfg.channelCount == 0) return false;

  uint8_t frame[CMD_FRAME_LEN];
  memset(frame, 0, CMD_FRAME_LEN);
  frame[0] = CMD_SET_CHANNELS;
  frame[1] = (uint8_t)(cfg.channelCount + 1); // NARGS = count byte + N channel bytes
  frame[2] = cfg.channelCount;
  for (uint8_t k = 0; k < cfg.channelCount && k < 16; k++) frame[3 + k] = cfg.channels[k];

  spiSendBytes(frame, CMD_FRAME_LEN);
  delay(CONFIG_ACK_DELAY_MS);
  uint8_t ack[ACK_FRAME_LEN] = {0};
  spiRecvBytes(ack, ACK_FRAME_LEN);
  return (ack[0] == ACK_MAGIC && ack[1] == ACK_STATUS_OK);
}

static bool handleRepeat(const String &args) {
  long v = constrain(args.toInt(), 1L, (long)MAX_REPEAT);
  cfg.repeatCount = (uint8_t)v;
  uint8_t a = cfg.repeatCount;
  return sendCmdAndReadAck(CMD_SET_REPEAT, &a, 1);
}

static bool handleBuffer(const String &args) {
  long v = max(1L, args.toInt());
  cfg.sweepsPerBlock = (uint8_t)min(v, 255L);
  uint8_t a = cfg.sweepsPerBlock;
  return sendCmdAndReadAck(CMD_SET_BUFFER, &a, 1);
}

static bool handleRef(const String &args) {
  String a = args; a.trim(); a.toLowerCase();
  uint8_t rb;
  if      (a == "1.2" || a == "1v2") { rb = 0; cfg.ref = 0; }
  else if (a == "3.3" || a == "vdd") { rb = 1; cfg.ref = 1; }
  else {
    Serial.println(F("# ERROR: only ref 1.2 and ref 3.3/vdd supported"));
    return false;
  }
  return sendCmdAndReadAck(CMD_SET_REF, &rb, 1);
}

static bool handleOsr(const String &args) {
  long v = args.toInt();
  if (v != 2 && v != 4 && v != 8) {
    Serial.println(F("# ERROR: osr must be 2, 4, or 8")); return false;
  }
  cfg.osr = (uint8_t)v;
  uint8_t a = cfg.osr;
  return sendCmdAndReadAck(CMD_SET_OSR, &a, 1);
}

static bool handleGain(const String &args) {
  long v = args.toInt();
  if (v < 1 || v > 4) {
    Serial.println(F("# ERROR: gain must be 1, 2, 3, or 4")); return false;
  }
  cfg.gain = (uint8_t)v;
  uint8_t a = cfg.gain;
  return sendCmdAndReadAck(CMD_SET_GAIN, &a, 1);
}

static bool handleGround(const String &args) {
  String a = args; a.trim(); a.toLowerCase();
  if (a == "true") {
    cfg.groundEnable = true;
    uint8_t en = 1;
    return sendCmdAndReadAck(CMD_GROUND_EN, &en, 1);
  } else if (a == "false") {
    cfg.groundEnable = false;
    uint8_t en = 0;
    return sendCmdAndReadAck(CMD_GROUND_EN, &en, 1);
  } else {
    long v = a.toInt();
    if (v < 0 || v > (int)MUX_CH_MAX) {
      Serial.println(F("# ERROR: ground channel out of range (0-15)")); return false;
    }
    cfg.groundPin    = (uint8_t)v;
    cfg.groundEnable = true;
    uint8_t pin = (uint8_t)v;
    return sendCmdAndReadAck(CMD_GROUND_PIN, &pin, 1);
  }
}

// ── RUN — special: blocking, handles its own ack before streaming ──────
//
// Continuous stream protocol:
//   After CMD_RUN, MG24 pre-captures blocks into alternating buffers.
//   Each block read is a single full-duplex SPI transaction. The first byte
//   sent by the Teensy is a control token: 0x00 = continue, CMD_STOP = stop.
//   MG24 inspects that control byte after each block transfer and either arms
//   the next block immediately or a final 4-byte ACK.
static void handleRun(const String &args) {
  if (cfg.channelCount == 0) {
    Serial.println(F("# ERROR: no channels configured"));
    hostAck(false, args); return;
  }

  uint32_t ms    = 0;
  bool     timed = false;
  if (args.length() > 0) {
    long v = args.toInt();
    if (v > 0) { ms = (uint32_t)v; timed = true; }
  }

  // Build RUN frame
  uint8_t frame[CMD_FRAME_LEN];
  memset(frame, 0, CMD_FRAME_LEN);
  frame[0] = CMD_RUN;
  if (timed) {
    frame[1] = 4;
    frame[2] = (uint8_t)(ms & 0xFF);
    frame[3] = (uint8_t)((ms >> 8) & 0xFF);
    frame[4] = (uint8_t)((ms >> 16) & 0xFF);
    frame[5] = (uint8_t)((ms >> 24) & 0xFF);
  } else {
    frame[1] = 0;
  }
  spiSendBytes(frame, CMD_FRAME_LEN);

  // Wait for warmup + first block capture on MG24 side
  delay(warmupDelayMs() + blockDelayMs());

  // RX buffer (static: avoids large stack allocation)
  static uint8_t rxBuf[MAX_BLOCK_BYTES];
  uint32_t rBytes = blockResponseBytes();

  if (!spiRecvStreamingResponse(rxBuf, (uint16_t)min(rBytes, (uint32_t)sizeof(rxBuf)))) {
    hostAck(false, F("first block timeout")); return;
  }

  if (rxBuf[0] != BLOCK_MAGIC1 || rxBuf[1] != BLOCK_MAGIC2) {
    hostAck(false, F("first block bad magic")); return;
  }

  cfg.running = true;
  hostAck(true, args); // "#OK <args>" — sent BEFORE data so Python knows streaming started
  discardPendingCommandTerminators();

  // Forward first block to host/debug output
  emitBlockToHost(rxBuf, rBytes);
  delay(INTER_BLOCK_CMD_DELAY_MS);

  uint32_t runStart = millis();

  // ── Streaming loop — per-block handshake ─────────────────────────────
  // Each iteration:
  //   1. Check for stop* from Python or duration expiry
  //   2. If stopping: clock out one final block read with CMD_STOP in byte 0,
  //      then read the final 4-byte ACK.
  //   3. Otherwise: read the next full block and forward it to Python.
  while (true) {

    // Check serial for stop* from Python host
    while (Serial.available() > 0) {
      if ((char)Serial.read() == CMD_TERM) cfg.running = false;
    }
    // Duration check
    if (cfg.running && timed && (millis() - runStart) >= ms) cfg.running = false;

    if (!cfg.running) {
      // MG24 is already armed with the next block; send CMD_STOP as the first
      // byte of the block-read transaction so it will arm a final ACK after.
      spiRecvStreamingResponse(rxBuf,
                               (uint16_t)min(rBytes, (uint32_t)sizeof(rxBuf)),
                               CMD_STOP,
                               2);
      uint8_t ack[ACK_FRAME_LEN];
      spiRecvAckResponse(ack, 4); // discard final ACK
      delay(INTER_BLOCK_CMD_DELAY_MS);
      break;
    }

    if (!spiRecvStreamingResponse(rxBuf,
                                  (uint16_t)min(rBytes, (uint32_t)sizeof(rxBuf)),
                                  STREAM_NOP,
                                  2)) {
      spiRecvStreamingResponse(rxBuf,
                               (uint16_t)min(rBytes, (uint32_t)sizeof(rxBuf)),
                               CMD_STOP,
                               2);
      uint8_t ack[ACK_FRAME_LEN];
      spiRecvAckResponse(ack, 4);
      delay(INTER_BLOCK_CMD_DELAY_MS);
      cfg.running = false;
      break;
    }

    // If MG24 returned an error ACK (timed-run expired on MG24 side), stop
    if (rxBuf[0] == ACK_MAGIC) {
      delay(INTER_BLOCK_CMD_DELAY_MS);
      cfg.running = false; break;
    }

    if (rxBuf[0] != BLOCK_MAGIC1 || rxBuf[1] != BLOCK_MAGIC2) {
      // Unexpected bytes — stop cleanly
      spiRecvStreamingResponse(rxBuf,
                               (uint16_t)min(rBytes, (uint32_t)sizeof(rxBuf)),
                               CMD_STOP,
                               2);
      uint8_t ack[ACK_FRAME_LEN];
      spiRecvAckResponse(ack, 4);
      delay(INTER_BLOCK_CMD_DELAY_MS);
      cfg.running = false; break;
    }

    emitBlockToHost(rxBuf, rBytes);
    delay(INTER_BLOCK_CMD_DELAY_MS);
  }

  cfg.running = false;
  // Note: hostAck already sent above before streaming started
}

// ── STATUS — answered locally from cached config ──────────────────────
static void handleStatus() {
  Serial.println(F("# -------- STATUS --------"));
  Serial.println(F("# mcu: Array_PZT1 (Teensy 4.1 + MG24 dual-MUX SPI slave)"));
  Serial.print(F("# running: "));        Serial.println(cfg.running ? F("true") : F("false"));
  Serial.print(F("# channels (count=")); Serial.print(cfg.channelCount); Serial.println(F("):"));
  Serial.print(F("#   "));
  for (uint8_t i = 0; i < cfg.channelCount; i++) {
    Serial.print(cfg.channels[i]);
    if (i + 1 < cfg.channelCount) Serial.print(',');
  }
  Serial.println();
  Serial.print(F("# repeatCount: "));    Serial.println(cfg.repeatCount);
  Serial.print(F("# sweepsPerBlock: ")); Serial.println(cfg.sweepsPerBlock);
  Serial.print(F("# ref: "));            Serial.println(cfg.ref == 0 ? F("1.2V") : F("VDD/3.3V"));
  Serial.print(F("# osr: "));            Serial.println(cfg.osr);
  Serial.print(F("# gain: "));           Serial.print(cfg.gain); Serial.println('x');
  Serial.print(F("# groundPin: "));      Serial.println(cfg.groundPin);
  Serial.print(F("# groundEnable: "));   Serial.println(cfg.groundEnable ? F("true") : F("false"));
  uint32_t sc = (uint32_t)cfg.channelCount * cfg.repeatCount * cfg.sweepsPerBlock * 2u;
  Serial.print(F("# samplesPerBlock (MUX1+MUX2 interleaved): ")); Serial.println(sc);
  Serial.print(F("# estimatedBlockDelayMs: ")); Serial.println(blockDelayMs());
  Serial.println(F("# NOTE: each channel slot yields 2 samples [MUX1_val, MUX2_val]"));
  Serial.println(F("# -------------------------"));
}

// ── Command dispatcher ────────────────────────────────────────────────
// Pattern mirrors the original ADC_Streamer handleLine():
//   - Each handler returns bool (ok/fail)
//   - A single hostAck(ok, args) is called at the end
//   - Exception: handleRun() is void and calls hostAck() itself, because
//     it is blocking and must send #OK before data starts flowing
static String inputLine;

static void handleLine(const String &rawLine) {
  String line = rawLine; line.trim();
  if (line.length() == 0) return;

  int    idx  = line.indexOf(' ');
  String cmd  = (idx < 0) ? line : line.substring(0, idx);
  String args = (idx < 0) ? "" : line.substring(idx + 1);
  args.trim();
  cmd.toLowerCase();

  bool ok = true;

  if      (cmd == "channels") ok = handleChannels(args);
  else if (cmd == "repeat")   ok = handleRepeat(args);
  else if (cmd == "buffer")   ok = handleBuffer(args);
  else if (cmd == "ref")      ok = handleRef(args);
  else if (cmd == "osr")      ok = handleOsr(args);
  else if (cmd == "gain")     ok = handleGain(args);
  else if (cmd == "ground")   ok = handleGround(args);
  else if (cmd == "run")      { handleRun(args); return; } // manages its own ack
  else if (cmd == "stop")     { cfg.running = false; }
  else if (cmd == "status")   { handleStatus(); }
  else if (cmd == "mcu")      { Serial.println(F("# Array_PZT1")); }
  else if (cmd == "help") {
    Serial.println(F("# Commands (* terminated):"));
    Serial.println(F("#   channels 0,1,2,...  (MUX channels 0-15)"));
    Serial.println(F("#   ground <ch>         (set ground MUX channel)"));
    Serial.println(F("#   ground true|false   (enable/disable ground dummy)"));
    Serial.println(F("#   repeat <n>          (samples per channel, max 100)"));
    Serial.println(F("#   buffer <n>          (sweeps per block)"));
    Serial.println(F("#   ref 1.2|3.3|vdd"));
    Serial.println(F("#   osr 2|4|8"));
    Serial.println(F("#   gain 1|2|3|4"));
    Serial.println(F("#   run                 (stream until stop*)"));
    Serial.println(F("#   run <ms>"));
    Serial.println(F("#   stop"));
    Serial.println(F("#   status"));
    Serial.println(F("#   mcu"));
    Serial.println(F("# NOTE: each channel slot yields 2 interleaved samples [MUX1, MUX2]"));
  }
  else {
    Serial.print(F("# ERROR: unknown command '")); Serial.print(cmd);
    Serial.println(F("'. Type 'help'."));
    ok = false;
  }

  hostAck(ok, args);
}

// ── setup() / loop() ─────────────────────────────────────────────────
void setup() {
  Serial.begin(SERIAL_BAUD);
  while (!Serial) {}

  mg24SPI.begin();
  pinMode(CS_PIN, OUTPUT);
  digitalWrite(CS_PIN, HIGH);

  Serial.println(F("Teensy Array_PZT1 ready"));
}

void loop() {
  while (Serial.available() > 0) {
    char c = (char)Serial.read();
    if (c == '\r' || c == '\n') continue;
    if (c == CMD_TERM) {
      if (inputLine.length() > 0) { handleLine(inputLine); inputLine = ""; }
      continue;
    }
    inputLine += c;
    if (inputLine.length() > MAX_CMD_LEN) {
      inputLine = "";
      Serial.println(F("# ERROR: input too long; cleared."));
    }
  }
}
