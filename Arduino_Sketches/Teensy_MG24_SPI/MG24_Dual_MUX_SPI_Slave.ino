/*
 * MG24_Dual_MUX_SPI_Slave.ino
 * Dual-MUX ADC Streamer — XIAO MG24, SPI Slave
 * ==============================================
 * Controls two ADG1206 (16:1) MUXes whose A0–A3 address pins are wired
 * in parallel; both switch simultaneously.  MUX1 output is read on D1,
 * MUX2 output is read on D2.
 *
 * SPI transport uses SPIDRV — identical driver init to SPI_Slave_test3_Claude.
 * No DRDY pin.  The Teensy master drives timing:
 *   Phase 1 — command  (Teensy→MG24, CMD_FRAME_LEN bytes)
 *   Phase 2 — response (MG24→Teensy, ACK_FRAME_LEN bytes OR full data block)
 *   The Teensy waits a computed delay between the two phases.
 *
 * ── Pin assignments ──────────────────────────────────────────────────
 *   D0  (PC0) ← CS    (from Teensy, same as test3)
 *   D1        ← ADC input for MUX1 COM
 *   D2        ← ADC input for MUX2 COM
 *   D3        → MUX A0  (shared, both MUXes)
 *   D4        → MUX A1
 *   D5        → MUX A2
 *   D6        → MUX A3
 *   D8  (PA3) ← SCK   (same as test3)
 *   D9  (PA4) → MISO  (same as test3)
 *   D10 (PA5) ← MOSI  (same as test3)
 *
 * ── SPI settings (identical to SPI_Slave_test3_Claude) ───────────────
 *   Peripheral : EUSART1
 *   Bit order  : MSB first
 *   Mode       : spidrvClockMode1  (SPI_MODE1)
 *   CS control : spidrvCsControlAuto
 *   Bit rate   : SPI_BITRATE (1 MHz)
 *
 * ── Protocol ─────────────────────────────────────────────────────────
 *   Command frame (always CMD_FRAME_LEN bytes, Teensy→MG24):
 *     [CMD][NARGS][arg0]...[argN]  (unused bytes padded with 0x00)
 *
 *   Response (MG24→Teensy):
 *     ACK (ACK_FRAME_LEN = 4 bytes):
 *       [0xAC][status 0x00=OK / 0x01=ERR][b2][b3]
 *       "return ACK_FRAME_LEN" inside processCommand() means:
 *       "arm a 4-byte ACK as the SPI response transfer".
 *     Data block (for CMD_RUN and subsequent streaming blocks):
 *       [0xAA][0x55][cntL][cntH]
 *       + cnt × uint16LE  (interleaved MUX1, MUX2 samples)
 *       + avg_dt_us (uint16LE)
 *       + block_start_us (uint32LE)
 *       + block_end_us   (uint32LE)
 *       cnt = channelCount × repeatCount × sweepsPerBlock × 2
 *
 * ── Command codes ────────────────────────────────────────────────────
 *   0x01  SET_CHANNELS  NARGS=count+1  arg0=count, arg1..=channel list
 *   0x02  SET_REPEAT    NARGS=1        arg0=repeatCount
 *   0x03  SET_BUFFER    NARGS=1        arg0=sweepsPerBlock
 *   0x04  SET_REF       NARGS=1        arg0: 0=1.2V  1=VDD(3.3V)
 *   0x05  SET_OSR       NARGS=1        arg0: 2|4|8
 *   0x06  SET_GAIN      NARGS=1        arg0: 1|2|3|4
 *   0x07  RUN           NARGS=0 (continuous) | 4 (uint32LE ms)
 *   0x08  STOP          NARGS=0
 *   0x0A  MCU_ID        NARGS=0  → ACK bytes 2-3 = 'M','G'
 *   0x0B  GROUND_PIN    NARGS=1        arg0=MUX channel (0-15)
 *   0x0C  GROUND_EN     NARGS=1        arg0: 0|1
 *
 * ── Sample interleaving ──────────────────────────────────────────────
 *   For each (channel, repeat) slot within a sweep:
 *     [MUX1_val uint16LE, MUX2_val uint16LE]
 */

#include <Arduino.h>
#include "spidrv.h"
#include "sl_gpio.h"
#include "pins_arduino.h"
#include "pinDefinitions.h"

extern "C" {
  #include "em_cmu.h"
  #include "em_gpio.h"
  #include "em_iadc.h"
}

// =====================================================================
// ── USER-CONFIGURABLE CONSTANTS ──────────────────────────────────────
// =====================================================================

// ── Pin assignments ───────────────────────────────────────────────────
static const int PIN_CS       = D0;   // SPI chip-select input (PC0)
static const int PIN_ADC_MUX1 = D1;   // IADC input: MUX1 COM output
static const int PIN_ADC_MUX2 = D2;   // IADC input: MUX2 COM output
static const int PIN_MUX_A0   = D3;   // ADG1206 address bit 0 (both MUXes)
static const int PIN_MUX_A1   = D4;   // ADG1206 address bit 1
static const int PIN_MUX_A2   = D5;   // ADG1206 address bit 2
static const int PIN_MUX_A3   = D6;   // ADG1206 address bit 3

// ── SPI transport ─────────────────────────────────────────────────────
static const uint32_t SPI_BITRATE         = 4000000UL; // 4 MHz

// ── SPIDRV EUSART1 GPIO routing (must match PCB; same as test3) ───────
// These are raw Silicon Labs port/pin numbers, NOT Arduino Dx numbers.
static const sl_gpio_port_t SPI_PORT_TX   = SL_GPIO_PORT_A; // PA5 = D10 MOSI
static const uint8_t        SPI_PIN_TX    = 5;
static const sl_gpio_port_t SPI_PORT_RX   = SL_GPIO_PORT_A; // PA4 = D9  MISO
static const uint8_t        SPI_PIN_RX    = 4;
static const sl_gpio_port_t SPI_PORT_CLK  = SL_GPIO_PORT_A; // PA3 = D8  SCK
static const uint8_t        SPI_PIN_CLK   = 3;
static const sl_gpio_port_t SPI_PORT_CS   = SL_GPIO_PORT_C; // PC0 = D0  CS
static const uint8_t        SPI_PIN_CS    = 0;

// ── MUX timing ────────────────────────────────────────────────────────
// Time to wait after switching the ADG1206 address lines before sampling.
// ADG1206 worst-case tON is 150 ns; we use a generous µs value to also
// allow the connected circuitry (buffer op-amp, RC filter) to settle.
static const uint32_t MUX_SETTLE_US      = 30;

// ── IADC clock targets ────────────────────────────────────────────────
// Faster ADC clock → higher throughput, more noise.
// Slower ADC clock → better SNR, lower throughput.
static const uint32_t IADC_SRC_CLK_HZ   = 10000000UL; // source clock (Hz) / orig was 20000000UL 20Mhz
static const uint32_t IADC_ADC_CLK_HZ   = 5000000UL; // ADC clock   (Hz) / orig was 10000000UL 10Mhz

// ── IADC warm-up ─────────────────────────────────────────────────────
// Number of full sweeps discarded after RUN starts so that the IADC
// reference and any analog filters have time to settle.
static const uint16_t WARMUP_SWEEPS      = 48;

// ── Buffer sizing ─────────────────────────────────────────────────────
// Maximum number of (MUX1, MUX2) pairs in one streaming block.
// Each pair = 4 bytes.  Total TX buffer = 4 (hdr) + pairs×4 + 10 (trl).
// 8000 pairs → ~32 kB.  Reduce if you need to conserve RAM.
static const uint32_t MAX_PAIRS          = 8000UL;

// ── Protocol limits ───────────────────────────────────────────────────
static const uint8_t  CMD_FRAME_LEN      = 20;  // fixed command frame size (bytes)
static const uint8_t  ACK_FRAME_LEN      = 4;   // fixed ACK frame size (bytes)
//   ACK layout: [0xAC][status 0x00=OK/0x01=ERR][b2][b3]
//   Every processCommand() case that sends only an ACK returns ACK_FRAME_LEN.
//   CMD_RUN returns 4 + pairs*4 + BLOCK_TRAILER_LEN (the full data block).
static const uint8_t  BLOCK_TRAILER_LEN  = 10;  // avg_dt_us(2) + start(4) + end(4)
static const uint8_t  MAX_SEQ_LEN        = 16;  // max channels in a sweep sequence
static const uint8_t  MUX_CH_MAX         = 15;  // highest valid ADG1206 channel (0-15)
static const uint16_t MAX_REPEAT         = 100; // max repeatCount accepted over SPI

// ── SPI callback timeout ──────────────────────────────────────────────
// How long to wait (ms) for the SPIDRV transfer-done callback before
// declaring an error and re-arming the command transfer.
static const uint32_t SPI_CALLBACK_TIMEOUT_MS = 200;

// ── Serial debug baud rate ────────────────────────────────────────────
static const uint32_t SERIAL_DEBUG_BAUD  = 115200;

// =====================================================================
// ── END USER-CONFIGURABLE CONSTANTS ──────────────────────────────────
// =====================================================================

// Derived buffer size (do not edit)
static const uint32_t SPI_TX_BUF_SIZE =
    (uint32_t)ACK_FRAME_LEN + MAX_PAIRS * 4UL + BLOCK_TRAILER_LEN;

// ── Command codes ─────────────────────────────────────────────────────
static const uint8_t CMD_SET_CHANNELS = 0x01;
static const uint8_t CMD_SET_REPEAT   = 0x02;
static const uint8_t CMD_SET_BUFFER   = 0x03;
static const uint8_t CMD_SET_REF      = 0x04;
static const uint8_t CMD_SET_OSR      = 0x05;
static const uint8_t CMD_SET_GAIN     = 0x06;
static const uint8_t CMD_RUN          = 0x07;
static const uint8_t CMD_STOP         = 0x08;
static const uint8_t CMD_MCU_ID       = 0x0A;
static const uint8_t CMD_GROUND_PIN   = 0x0B;
static const uint8_t CMD_GROUND_EN    = 0x0C;
static const uint8_t CMD_CONTINUE     = 0x0D;  // request next streaming block (no warmup)

// ── Binary block magic bytes ──────────────────────────────────────────
static const uint8_t BLOCK_MAGIC1     = 0xAA;
static const uint8_t BLOCK_MAGIC2     = 0x55;
static const uint8_t ACK_MAGIC        = 0xAC;
static const uint8_t ACK_STATUS_OK    = 0x00;
static const uint8_t ACK_STATUS_ERR   = 0x01;

// ── State machine ─────────────────────────────────────────────────────
enum State : uint8_t { WAIT_CMD, RESP_ARMED };
static volatile State gState = WAIT_CMD;

// ── SPIDRV ────────────────────────────────────────────────────────────
static SPIDRV_HandleData_t spiHandle;
static volatile bool    xferDone   = false;
static volatile Ecode_t xferStatus = (Ecode_t)0xFFFFu;

static void spiCallback(SPIDRV_Handle_t, Ecode_t status, int) {
  xferStatus = status;
  xferDone   = true;
}

// Command phase buffers
static uint8_t cmdRxBuf[CMD_FRAME_LEN];
static uint8_t cmdTxDummy[CMD_FRAME_LEN]; // zeros, sent while receiving command

// Response phase buffers
static uint8_t  spiTxBufA[SPI_TX_BUF_SIZE];
static uint8_t  spiTxBufB[SPI_TX_BUF_SIZE];
static uint8_t  *armedRespBuf = spiTxBufA;   // buffer currently armed for SPI TX
static uint8_t  *fillRespBuf  = spiTxBufB;   // buffer available for the next captured block
static uint8_t  spiRxSink[SPI_TX_BUF_SIZE];  // discards dummy bytes master sends during our TX
static uint32_t respLen = 0;
static bool     streamRespArmed = false;
static bool     nextBlockReady  = false;
static uint32_t nextBlockLen    = 0;

static void armCmd() {
  xferDone   = false;
  xferStatus = (Ecode_t)0xFFFFu;
  memset(cmdRxBuf, 0, CMD_FRAME_LEN);
  SPIDRV_STransfer(&spiHandle, cmdTxDummy, cmdRxBuf,
                   CMD_FRAME_LEN, spiCallback, 0);
  gState = WAIT_CMD;
}

static void armResp(uint8_t *txBuf, uint32_t len, bool isStreaming = false) {
  xferDone   = false;
  xferStatus = (Ecode_t)0xFFFFu;
  armedRespBuf = txBuf;
  respLen    = len;
  streamRespArmed = isStreaming;
  // armedRespBuf → data to send (ACK or data block)
  // spiRxSink → receives and discards the dummy bytes master sends during our TX
  //             (using the same buffer for TX and RX would corrupt outgoing data via DMA)
  SPIDRV_STransfer(&spiHandle, armedRespBuf, spiRxSink,
                   (int)len, spiCallback, 0);
  gState = RESP_ARMED;
}

// ── CS rising-edge interrupt (identical to test3) ─────────────────────
static volatile bool csRose = false;
static void onCSRising() { csRose = true; }

// ── ADC / MUX configuration ───────────────────────────────────────────
static uint8_t  channelSeq[MAX_SEQ_LEN];
static uint8_t  channelCount     = 0;
static int      groundMuxCh      = 0;
static bool     useGround        = false;
static uint16_t repeatCount      = 1;
static uint16_t sweepsPerBlock   = 1;

// Flattened per-entry list (includes optional ground entries).
// Worst case: ground entry before each of MAX_SEQ_LEN channels.
static uint8_t  entryMuxCh[MAX_SEQ_LEN * 2];
static bool     entryIsGround[MAX_SEQ_LEN * 2];
static uint8_t  entryCount = 0;

// ── IADC runtime state ────────────────────────────────────────────────
static uint32_t            g_vref_mV  = 3300;
static IADC_CfgReference_t g_vref_sel = iadcCfgReferenceVddx;
static IADC_CfgOsrHighSpeed_t g_osr   = iadcCfgOsrHighSpeed2x;
static IADC_CfgAnalogGain_t   g_gain  = iadcCfgAnalogGain1x;
static bool                g_iadcReady   = false;
static bool                g_configDirty = true;
static IADC_PosInput_t     g_mux1Pos, g_mux2Pos;

// ── Run state ─────────────────────────────────────────────────────────
static bool     isRunning     = false;
static bool     timedRun      = false;
static uint32_t runStopMillis = 0;

// ── GPIO → IADC pos-input map (identical to reference sketch) ─────────
static const IADC_PosInput_t GPIO_to_ADC_map[64] = {
  // Port A
  iadcPosInputPortAPin0,  iadcPosInputPortAPin1,  iadcPosInputPortAPin2,  iadcPosInputPortAPin3,
  iadcPosInputPortAPin4,  iadcPosInputPortAPin5,  iadcPosInputPortAPin6,  iadcPosInputPortAPin7,
  iadcPosInputPortAPin8,  iadcPosInputPortAPin9,  iadcPosInputPortAPin10, iadcPosInputPortAPin11,
  iadcPosInputPortAPin12, iadcPosInputPortAPin13, iadcPosInputPortAPin14, iadcPosInputPortAPin15,
  // Port B
  iadcPosInputPortBPin0,  iadcPosInputPortBPin1,  iadcPosInputPortBPin2,  iadcPosInputPortBPin3,
  iadcPosInputPortBPin4,  iadcPosInputPortBPin5,  iadcPosInputPortBPin6,  iadcPosInputPortBPin7,
  iadcPosInputPortBPin8,  iadcPosInputPortBPin9,  iadcPosInputPortBPin10, iadcPosInputPortBPin11,
  iadcPosInputPortBPin12, iadcPosInputPortBPin13, iadcPosInputPortBPin14, iadcPosInputPortBPin15,
  // Port C
  iadcPosInputPortCPin0,  iadcPosInputPortCPin1,  iadcPosInputPortCPin2,  iadcPosInputPortCPin3,
  iadcPosInputPortCPin4,  iadcPosInputPortCPin5,  iadcPosInputPortCPin6,  iadcPosInputPortCPin7,
  iadcPosInputPortCPin8,  iadcPosInputPortCPin9,  iadcPosInputPortCPin10, iadcPosInputPortCPin11,
  iadcPosInputPortCPin12, iadcPosInputPortCPin13, iadcPosInputPortCPin14, iadcPosInputPortCPin15,
  // Port D
  iadcPosInputPortDPin0,  iadcPosInputPortDPin1,  iadcPosInputPortDPin2,  iadcPosInputPortDPin3,
  iadcPosInputPortDPin4,  iadcPosInputPortDPin5,  iadcPosInputPortDPin6,  iadcPosInputPortDPin7,
  iadcPosInputPortDPin8,  iadcPosInputPortDPin9,  iadcPosInputPortDPin10, iadcPosInputPortDPin11,
  iadcPosInputPortDPin12, iadcPosInputPortDPin13, iadcPosInputPortDPin14, iadcPosInputPortDPin15
};

static void allocateAnalogBus(PinName p) {
  bool even = (((uint32_t)p) % 2u) == 0u;
  if (p >= PD0 || p >= PC0) {
    if (even) GPIO->CDBUSALLOC |= GPIO_CDBUSALLOC_CDEVEN0_ADC0;
    else       GPIO->CDBUSALLOC |= GPIO_CDBUSALLOC_CDODD0_ADC0;
  } else if (p >= PB0) {
    if (even) GPIO->BBUSALLOC  |= GPIO_BBUSALLOC_BEVEN0_ADC0;
    else       GPIO->BBUSALLOC  |= GPIO_BBUSALLOC_BODD0_ADC0;
  } else {
    if (even) GPIO->ABUSALLOC  |= GPIO_ABUSALLOC_AEVEN0_ADC0;
    else       GPIO->ABUSALLOC  |= GPIO_ABUSALLOC_AODD0_ADC0;
  }
}

// ── MUX helpers ───────────────────────────────────────────────────────
static uint8_t g_lastMuxCh = 0xFF;

static void muxSelect(uint8_t ch) {
  uint8_t diff = ch ^ g_lastMuxCh;
  if (g_lastMuxCh == 0xFF || (diff & 0x01)) digitalWrite(PIN_MUX_A0, (ch & 0x01) ? HIGH : LOW);
  if (g_lastMuxCh == 0xFF || (diff & 0x02)) digitalWrite(PIN_MUX_A1, (ch & 0x02) ? HIGH : LOW);
  if (g_lastMuxCh == 0xFF || (diff & 0x04)) digitalWrite(PIN_MUX_A2, (ch & 0x04) ? HIGH : LOW);
  if (g_lastMuxCh == 0xFF || (diff & 0x08)) digitalWrite(PIN_MUX_A3, (ch & 0x08) ? HIGH : LOW);
  g_lastMuxCh = ch;
  delayMicroseconds(MUX_SETTLE_US);
}

// ── IADC scan-mode init (D1 = MUX1 COM, D2 = MUX2 COM) ───────────────
static void initIADC() {
  g_iadcReady = false;

  PinName n1 = pinToPinName(PIN_ADC_MUX1);
  PinName n2 = pinToPinName(PIN_ADC_MUX2);
  if (n1 == PIN_NAME_NC || n2 == PIN_NAME_NC) {
    Serial.println(F("# ERROR: ADC pins not valid"));
    return;
  }

  CMU_ClockEnable(cmuClock_GPIO,  true);
  CMU_ClockEnable(cmuClock_IADC0, true);

  g_mux1Pos = GPIO_to_ADC_map[(uint32_t)n1 - (uint32_t)PIN_NAME_MIN];
  g_mux2Pos = GPIO_to_ADC_map[(uint32_t)n2 - (uint32_t)PIN_NAME_MIN];
  allocateAnalogBus(n1);
  allocateAnalogBus(n2);

  IADC_Init_t       init       = IADC_INIT_DEFAULT;
  IADC_AllConfigs_t allConfigs = IADC_ALLCONFIGS_DEFAULT;

  init.warmup         = iadcWarmupNormal;
  init.srcClkPrescale = IADC_calcSrcClkPrescale(IADC0, IADC_SRC_CLK_HZ, 0);

  allConfigs.configs[0].reference    = g_vref_sel;
  allConfigs.configs[0].vRef         = g_vref_mV;
  allConfigs.configs[0].osrHighSpeed = g_osr;
  allConfigs.configs[0].analogGain   = g_gain;
  allConfigs.configs[0].adcClkPrescale =
      IADC_calcAdcClkPrescale(IADC0, IADC_ADC_CLK_HZ, 0,
                              iadcCfgModeNormal, init.srcClkPrescale);

  IADC_reset(IADC0);
  IADC_init(IADC0, &init, &allConfigs);

  // Scan table: entry 0 = MUX1 COM (D1), entry 1 = MUX2 COM (D2)
  IADC_InitScan_t  initScan  = IADC_INITSCAN_DEFAULT;
  IADC_ScanTable_t scanTable = IADC_SCANTABLE_DEFAULT;

  initScan.alignment      = iadcAlignRight12;
  initScan.dataValidLevel = iadcFifoCfgDvl1;
  initScan.triggerSelect  = iadcTriggerSelImmediate;
  initScan.triggerAction  = iadcTriggerActionOnce;
  initScan.start          = false;

  scanTable.entries[0].posInput      = g_mux1Pos;
  scanTable.entries[0].negInput      = iadcNegInputGnd;
  scanTable.entries[0].configId      = 0;
  scanTable.entries[0].includeInScan = true;

  scanTable.entries[1].posInput      = g_mux2Pos;
  scanTable.entries[1].negInput      = iadcNegInputGnd;
  scanTable.entries[1].configId      = 0;
  scanTable.entries[1].includeInScan = true;

  IADC_initScan(IADC0, &initScan, &scanTable);
  IADC_clearInt(IADC0, _IADC_IF_MASK);
  while (IADC_getScanFifoCnt(IADC0) > 0) (void)IADC_pullScanFifoResult(IADC0);

  g_iadcReady   = true;
  g_configDirty = false;
}

// Trigger one scan at the current MUX address; block until both results arrive.
static bool iadcReadPair(uint16_t &v1, uint16_t &v2) {
  if (!g_iadcReady) return false;
  while (IADC_getScanFifoCnt(IADC0) > 0) (void)IADC_pullScanFifoResult(IADC0);

  IADC_command(IADC0, iadcCmdStartScan);
  while (IADC_getScanFifoCnt(IADC0) < 2) ; // tight poll

  IADC_Result_t r0 = IADC_pullScanFifoResult(IADC0);
  IADC_Result_t r1 = IADC_pullScanFifoResult(IADC0);

  // Use scan table ID to assign correctly regardless of FIFO order
  if (r0.id == 0) { v1 = r0.data & 0x0FFF; v2 = r1.data & 0x0FFF; }
  else             { v1 = r1.data & 0x0FFF; v2 = r0.data & 0x0FFF; }
  return true;
}

// ── Config helpers ────────────────────────────────────────────────────

// Rebuild the per-entry MUX channel list (with optional ground entries).
static void buildEntryList() {
  entryCount = 0;
  int  prev       = -1;
  uint8_t maxEnt  = (uint8_t)(MAX_SEQ_LEN * 2);

  for (uint8_t i = 0; i < channelCount && entryCount < maxEnt; i++) {
    uint8_t ch    = channelSeq[i];
    bool    isNew = (i == 0) || ((int)ch != prev);
    if (useGround && isNew && entryCount < maxEnt) {
      entryMuxCh[entryCount]    = (uint8_t)groundMuxCh;
      entryIsGround[entryCount] = true;
      entryCount++;
    }
    for (uint16_t r = 0; r < repeatCount && entryCount < maxEnt; r++) {
      entryMuxCh[entryCount]    = ch;
      entryIsGround[entryCount] = false;
      entryCount++;
    }
    prev = (int)ch;
  }
  g_configDirty = true;
}

// Cap sweepsPerBlock so data always fits in spiTxBuf.
static void clampSweepsPerBlock() {
  uint32_t pps = (uint32_t)channelCount * repeatCount; // pairs per sweep
  if (pps == 0) return;
  uint32_t maxSw = MAX_PAIRS / pps;
  if (maxSw == 0)             maxSw = 1;
  if (sweepsPerBlock > maxSw) sweepsPerBlock = (uint16_t)maxSw;
  if (sweepsPerBlock == 0)    sweepsPerBlock = 1;
}

// ── Block capture ─────────────────────────────────────────────────────
// Captures sweepsPerBlock sweeps. Writes sample pairs into spiTxBuf at
// offset ACK_FRAME_LEN (= 4), then fills the header and trailer.
// Returns the number of (MUX1, MUX2) pairs captured.
static uint32_t captureBlock(uint8_t *txBuf) {
  if (!g_iadcReady || channelCount == 0) return 0;

  uint32_t maxPairs = (uint32_t)sweepsPerBlock * channelCount * repeatCount;
  if (maxPairs > MAX_PAIRS) maxPairs = MAX_PAIRS;

  uint32_t pairIdx    = 0;
  uint32_t blockStart = micros();
  g_lastMuxCh = 0xFF;

  for (uint16_t sw = 0; sw < sweepsPerBlock && pairIdx < maxPairs; sw++) {
    for (uint8_t e = 0; e < entryCount && pairIdx < maxPairs; e++) {
      uint8_t ch = entryMuxCh[e];
      if (ch != g_lastMuxCh) muxSelect(ch);

      uint16_t v1 = 0, v2 = 0;
      iadcReadPair(v1, v2);

      if (!entryIsGround[e]) {
        uint32_t off = (uint32_t)ACK_FRAME_LEN + pairIdx * 4u;
        txBuf[off + 0] = (uint8_t)(v1 & 0xFF);
        txBuf[off + 1] = (uint8_t)(v1 >> 8);
        txBuf[off + 2] = (uint8_t)(v2 & 0xFF);
        txBuf[off + 3] = (uint8_t)(v2 >> 8);
        pairIdx++;
      }
    }
  }

  uint32_t blockEnd    = micros();
  uint32_t sampleCount = pairIdx * 2u; // total uint16 samples (MUX1 + MUX2)
  uint32_t elapsed     = blockEnd - blockStart;
  uint16_t avgDtUs     = (sampleCount > 0)
      ? (uint16_t)min(elapsed / sampleCount, 65535UL) : 0u;

  // Header (first 4 bytes of spiTxBuf)
  txBuf[0] = BLOCK_MAGIC1;
  txBuf[1] = BLOCK_MAGIC2;
  txBuf[2] = (uint8_t)(sampleCount & 0xFF);
  txBuf[3] = (uint8_t)(sampleCount >> 8);

  // Trailer immediately after sample data
  uint32_t tOff = (uint32_t)ACK_FRAME_LEN + pairIdx * 4u;
  txBuf[tOff + 0] = (uint8_t)(avgDtUs & 0xFF);
  txBuf[tOff + 1] = (uint8_t)(avgDtUs >> 8);
  txBuf[tOff + 2] = (uint8_t)(blockStart & 0xFF);
  txBuf[tOff + 3] = (uint8_t)((blockStart >>  8) & 0xFF);
  txBuf[tOff + 4] = (uint8_t)((blockStart >> 16) & 0xFF);
  txBuf[tOff + 5] = (uint8_t)((blockStart >> 24) & 0xFF);
  txBuf[tOff + 6] = (uint8_t)(blockEnd & 0xFF);
  txBuf[tOff + 7] = (uint8_t)((blockEnd >>  8) & 0xFF);
  txBuf[tOff + 8] = (uint8_t)((blockEnd >> 16) & 0xFF);
  txBuf[tOff + 9] = (uint8_t)((blockEnd >> 24) & 0xFF);

  return pairIdx;
}

// ── ACK helpers ───────────────────────────────────────────────────────
static void prepareAck(uint8_t *txBuf, bool ok, uint8_t b2 = 0x00, uint8_t b3 = 0x00) {
  txBuf[0] = ACK_MAGIC;
  txBuf[1] = ok ? ACK_STATUS_OK : ACK_STATUS_ERR;
  txBuf[2] = b2;
  txBuf[3] = b3;
}

static uint32_t blockResponseLenFromPairs(uint32_t pairs) {
  return (uint32_t)ACK_FRAME_LEN + pairs * 4u + BLOCK_TRAILER_LEN;
}

static uint32_t prepareBlockResponse(uint8_t *txBuf) {
  return blockResponseLenFromPairs(captureBlock(txBuf));
}

static void resetStreamingPipeline() {
  streamRespArmed = false;
  nextBlockReady = false;
  nextBlockLen = 0;
}

static void prefetchNextBlockIfNeeded() {
  if (!isRunning || !streamRespArmed || nextBlockReady || gState != RESP_ARMED || xferDone) {
    return;
  }

  nextBlockLen = prepareBlockResponse(fillRespBuf);
  nextBlockReady = true;
}

// ── Warmup sweeps ─────────────────────────────────────────────────────
static void doWarmup() {
  g_lastMuxCh = 0xFF;
  for (uint16_t sw = 0; sw < WARMUP_SWEEPS; sw++) {
    for (uint8_t e = 0; e < entryCount; e++) {
      muxSelect(entryMuxCh[e]);
      uint16_t d1, d2;
      iadcReadPair(d1, d2); // discard
    }
  }
}

// ── Command processing ────────────────────────────────────────────────
// Fills spiTxBuf and returns the number of bytes to arm as the response.
// For config commands this is always ACK_FRAME_LEN (= 4).
// For CMD_RUN it is ACK_FRAME_LEN + pairs*4 + BLOCK_TRAILER_LEN.
static uint32_t processCommand(const uint8_t *frame) {
  uint8_t        cmd   = frame[0];
  uint8_t        nargs = frame[1];
  const uint8_t *args  = frame + 2;

  switch (cmd) {

    case CMD_SET_CHANNELS: {
      if (nargs < 1) { prepareAck(armedRespBuf, false); return ACK_FRAME_LEN; }
      uint8_t cnt = args[0];
      if (cnt == 0 || cnt > MAX_SEQ_LEN || nargs < (uint8_t)(cnt + 1))
        { prepareAck(armedRespBuf, false); return ACK_FRAME_LEN; }
      channelCount = cnt;
      bool ok = true;
      for (uint8_t i = 0; i < cnt; i++) {
        if (args[i + 1] > MUX_CH_MAX) { ok = false; break; }
        channelSeq[i] = args[i + 1];
      }
      if (ok) { buildEntryList(); clampSweepsPerBlock(); }
      resetStreamingPipeline();
      prepareAck(armedRespBuf, ok);
      return ACK_FRAME_LEN;
    }

    case CMD_SET_REPEAT: {
      if (nargs < 1) { prepareAck(armedRespBuf, false); return ACK_FRAME_LEN; }
      repeatCount = max((uint16_t)1, min((uint16_t)args[0], MAX_REPEAT));
      buildEntryList();
      clampSweepsPerBlock();
      resetStreamingPipeline();
      prepareAck(armedRespBuf, true);
      return ACK_FRAME_LEN;
    }

    case CMD_SET_BUFFER: {
      if (nargs < 1) { prepareAck(armedRespBuf, false); return ACK_FRAME_LEN; }
      sweepsPerBlock = max((uint16_t)1, (uint16_t)args[0]);
      clampSweepsPerBlock();
      resetStreamingPipeline();
      prepareAck(armedRespBuf, true);
      return ACK_FRAME_LEN;
    }

    case CMD_SET_REF: {
      if (nargs < 1) { prepareAck(armedRespBuf, false); return ACK_FRAME_LEN; }
      if (args[0] == 0) { g_vref_mV = 1200; g_vref_sel = iadcCfgReferenceInt1V2; }
      else               { g_vref_mV = 3300; g_vref_sel = iadcCfgReferenceVddx;   }
      g_configDirty = true;
      resetStreamingPipeline();
      prepareAck(armedRespBuf, true);
      return ACK_FRAME_LEN;
    }

    case CMD_SET_OSR: {
      if (nargs < 1) { prepareAck(armedRespBuf, false); return ACK_FRAME_LEN; }
      if      (args[0] == 2) g_osr = iadcCfgOsrHighSpeed2x;
      else if (args[0] == 4) g_osr = iadcCfgOsrHighSpeed4x;
      else if (args[0] == 8) g_osr = iadcCfgOsrHighSpeed8x;
      else { prepareAck(armedRespBuf, false); return ACK_FRAME_LEN; }
      g_configDirty = true;
      resetStreamingPipeline();
      prepareAck(armedRespBuf, true);
      return ACK_FRAME_LEN;
    }

    case CMD_SET_GAIN: {
      if (nargs < 1) { prepareAck(armedRespBuf, false); return ACK_FRAME_LEN; }
      if      (args[0] == 1) g_gain = iadcCfgAnalogGain1x;
      else if (args[0] == 2) g_gain = iadcCfgAnalogGain2x;
      else if (args[0] == 3) g_gain = iadcCfgAnalogGain3x;
      else if (args[0] == 4) g_gain = iadcCfgAnalogGain4x;
      else { prepareAck(armedRespBuf, false); return ACK_FRAME_LEN; }
      g_configDirty = true;
      resetStreamingPipeline();
      prepareAck(armedRespBuf, true);
      return ACK_FRAME_LEN;
    }

    case CMD_GROUND_PIN: {
      if (nargs < 1 || args[0] > MUX_CH_MAX)
        { prepareAck(armedRespBuf, false); return ACK_FRAME_LEN; }
      groundMuxCh = args[0];
      useGround   = true;
      buildEntryList();
      resetStreamingPipeline();
      prepareAck(armedRespBuf, true);
      return ACK_FRAME_LEN;
    }

    case CMD_GROUND_EN: {
      if (nargs < 1) { prepareAck(armedRespBuf, false); return ACK_FRAME_LEN; }
      useGround = (args[0] != 0);
      buildEntryList();
      resetStreamingPipeline();
      prepareAck(armedRespBuf, true);
      return ACK_FRAME_LEN;
    }

    case CMD_MCU_ID:
      // Encode 'M','G' in bytes 2-3 of ACK so Teensy can identify MG24
      resetStreamingPipeline();
      prepareAck(armedRespBuf, true, 'M', 'G');
      return ACK_FRAME_LEN;

    case CMD_STOP:
      isRunning = timedRun = false;
      resetStreamingPipeline();
      prepareAck(armedRespBuf, true);
      return ACK_FRAME_LEN;

    case CMD_RUN: {
      if (channelCount == 0) { prepareAck(armedRespBuf, false); return ACK_FRAME_LEN; }

      if (g_configDirty) {
        initIADC();
        buildEntryList();
      }
      if (!g_iadcReady) { prepareAck(armedRespBuf, false); return ACK_FRAME_LEN; }

      // Parse optional timed duration (4 bytes LE = ms)
      if (nargs == 4) {
        uint32_t ms = ((uint32_t)args[0])
                    | ((uint32_t)args[1] << 8)
                    | ((uint32_t)args[2] << 16)
                    | ((uint32_t)args[3] << 24);
        timedRun = (ms > 0);
        if (timedRun) runStopMillis = millis() + ms;
      } else {
        timedRun = false;
      }
      isRunning = true;
      resetStreamingPipeline();

      doWarmup();

      return prepareBlockResponse(armedRespBuf);
    }

    case CMD_CONTINUE: {
      // Capture the next streaming block without warmup.
      // Returns error ACK (status=0x01) if not running — Teensy treats that as stop signal.
      if (!isRunning || !g_iadcReady || channelCount == 0) {
        resetStreamingPipeline();
        prepareAck(armedRespBuf, false);
        return ACK_FRAME_LEN;
      }
      if (timedRun && (int32_t)(millis() - runStopMillis) >= 0) {
        isRunning = timedRun = false;
        resetStreamingPipeline();
        prepareAck(armedRespBuf, false);   // error ACK signals Teensy to stop
        return ACK_FRAME_LEN;
      }
      resetStreamingPipeline();
      return prepareBlockResponse(armedRespBuf);
    }

    default:
      resetStreamingPipeline();
      prepareAck(armedRespBuf, false);
      return ACK_FRAME_LEN;
  }
}

// ── setup() ───────────────────────────────────────────────────────────
void setup() {
  Serial.begin(SERIAL_DEBUG_BAUD);
  while (!Serial) {}

  // MUX address outputs
  pinMode(PIN_MUX_A0, OUTPUT); digitalWrite(PIN_MUX_A0, LOW);
  pinMode(PIN_MUX_A1, OUTPUT); digitalWrite(PIN_MUX_A1, LOW);
  pinMode(PIN_MUX_A2, OUTPUT); digitalWrite(PIN_MUX_A2, LOW);
  pinMode(PIN_MUX_A3, OUTPUT); digitalWrite(PIN_MUX_A3, LOW);

  // ADC inputs
  pinMode(PIN_ADC_MUX1, INPUT);
  pinMode(PIN_ADC_MUX2, INPUT);

  // CS pin + rising-edge interrupt (identical to test3)
  pinMode(PIN_CS, INPUT_PULLUP);
  attachInterrupt(digitalPinToInterrupt(PIN_CS), onCSRising, RISING);

  // ── SPIDRV init — identical to SPI_Slave_test3_Claude ────────────────
  memset(&spiHandle,  0, sizeof(spiHandle));
  memset(cmdTxDummy,  0, sizeof(cmdTxDummy));

  SPIDRV_Init_t initData    = {};
  initData.port             = EUSART1;
  initData.portTx           = SPI_PORT_TX;  initData.pinTx  = SPI_PIN_TX;
  initData.portRx           = SPI_PORT_RX;  initData.pinRx  = SPI_PIN_RX;
  initData.portClk          = SPI_PORT_CLK; initData.pinClk = SPI_PIN_CLK;
  initData.portCs           = SPI_PORT_CS;  initData.pinCs  = SPI_PIN_CS;
  initData.bitRate          = SPI_BITRATE;
  initData.frameLength      = 8;
  initData.dummyTxValue     = 0x00;
  initData.type             = spidrvSlave;
  initData.bitOrder         = spidrvBitOrderMsbFirst;
  initData.clockMode        = spidrvClockMode1;  // SPI_MODE1, same as test3
  initData.csControl        = spidrvCsControlAuto;
  initData.slaveStartMode   = spidrvSlaveStartImmediate;

  Ecode_t e = SPIDRV_Init(&spiHandle, &initData);
  Serial.print(F("SPIDRV_Init="));
  Serial.println((int)e);

  // Pre-arm first command receive (identical to test3)
  armCmd();
  Serial.println(F("MG24 Dual-MUX Slave ready"));
}

// ── loop() ────────────────────────────────────────────────────────────
void loop() {

  // While the current streaming block is being sent via SPI DMA, use CPU time
  // to capture the next block into the alternate buffer.
  prefetchNextBlockIfNeeded();

  // Only act on CS rising edge — identical to test3
  if (!csRose) return;
  csRose = false;

  // Wait for SPIDRV callback — identical to test3
  uint32_t t = millis();
  while (!xferDone) {
    if (millis() - t > SPI_CALLBACK_TIMEOUT_MS) {
      Serial.println(F("Callback timeout"));
      armCmd();
      return;
    }
  }

  if (xferStatus != 0) {
    Serial.print(F("SPI xfer error: ")); Serial.println((int)xferStatus);
    armCmd();
    return;
  }

  switch (gState) {

    case WAIT_CMD: {
      // Received a CMD_FRAME_LEN-byte command frame from Teensy.
      // processCommand() fills spiTxBuf and returns the response size.
      uint32_t rLen = processCommand(cmdRxBuf);
      armResp(armedRespBuf, rLen, (rLen > ACK_FRAME_LEN) && isRunning);
      break;
    }

    case RESP_ARMED: {
      // After each streaming transfer, the first byte clocked in from the
      // Teensy decides whether to stop or continue the continuous stream.
      if (streamRespArmed && isRunning) {
        uint8_t controlByte = spiRxSink[0];

        if (controlByte == CMD_STOP) {
          isRunning = timedRun = false;
          nextBlockReady = false;
          prepareAck(armedRespBuf, true);
          armResp(armedRespBuf, ACK_FRAME_LEN, false);
          break;
        }

        uint8_t *completedBuf = armedRespBuf;
        if (!nextBlockReady) {
          nextBlockLen = prepareBlockResponse(fillRespBuf);
          nextBlockReady = true;
        }

        armResp(fillRespBuf, nextBlockLen, true);
        fillRespBuf = completedBuf;
        nextBlockReady = false;
        break;
      }

      streamRespArmed = false;
      armCmd();
      break;
    }
  }
}
