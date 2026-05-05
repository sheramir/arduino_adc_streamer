#include "Mg24SpiSlaveTransport.h"

#include "pins_arduino.h"
#include "pinDefinitions.h"
#include "sl_gpio.h"

namespace mg24_spi_slave {

namespace {

static const int kPinCs = D0;
static const int kPinDrdy = D7;
static const uint32_t kSpiBitrate = 4000000UL;
static const uint32_t kSpiCallbackTimeoutMs = 200;

static const sl_gpio_port_t kSpiPortTx = SL_GPIO_PORT_A;
static const uint8_t kSpiPinTx = 5;
static const sl_gpio_port_t kSpiPortRx = SL_GPIO_PORT_A;
static const uint8_t kSpiPinRx = 4;
static const sl_gpio_port_t kSpiPortClk = SL_GPIO_PORT_A;
static const uint8_t kSpiPinClk = 3;
static const sl_gpio_port_t kSpiPortCs = SL_GPIO_PORT_C;
static const uint8_t kSpiPinCs = 0;

static Runtime *g_runtime = nullptr;

static inline void drdyWrite(bool asserted) {
  digitalWrite(kPinDrdy, asserted ? HIGH : LOW);
}

static void spiCallback(SPIDRV_Handle_t, Ecode_t status, int) {
  if (g_runtime == nullptr) {
    return;
  }
  g_runtime->xfer_status = status;
  g_runtime->xfer_done = true;
}

static void onCSRising() {
  if (g_runtime == nullptr) {
    return;
  }
  drdyWrite(false);
  g_runtime->cs_rose = true;
}

static void armCmd(Runtime &rt) {
  drdyWrite(false);
  rt.xfer_done = false;
  rt.xfer_status = (Ecode_t)0xFFFFu;
  rt.next_block_ready = false;
  rt.next_block_len = 0;
  memset(rt.cmd_rx_buf, 0, sizeof(rt.cmd_rx_buf));
  SPIDRV_STransfer(&rt.spi_handle, rt.cmd_tx_dummy, rt.cmd_rx_buf,
                   mg24_proto::kCmdFrameLen, spiCallback, 0);
  rt.state = Runtime::WAIT_CMD;
  rt.stream_resp_armed = false;
}

static void armResp(Runtime &rt, uint8_t *tx_buf, uint32_t len, bool is_streaming) {
  rt.xfer_done = false;
  rt.xfer_status = (Ecode_t)0xFFFFu;
  rt.armed_resp_buf = tx_buf;
  rt.resp_len = len;
  rt.stream_resp_armed = is_streaming;
  SPIDRV_STransfer(&rt.spi_handle, rt.armed_resp_buf, rt.rx_sink, (int)len, spiCallback, 0);
  rt.state = Runtime::RESP_ARMED;
  drdyWrite(true);
}

static void prefetchNextBlockIfNeeded(Runtime &rt, mg24_cmd::Runtime &cmd) {
  if (!rt.stream_resp_armed || rt.next_block_ready || rt.state != Runtime::RESP_ARMED) {
    return;
  }

  if (!mg24_cmd::isStreaming(cmd) || !mg24_cmd::canPrefetchStreaming(cmd)) {
    return;
  }

  // If the just-finished streaming transfer already carried STOP, skip
  // prefetch so the next response can become the final ACK instead.
  if (rt.xfer_done && rt.rx_sink[0] == mg24_proto::kCmdStop) {
    return;
  }

  const mg24_cmd::Response response =
      mg24_cmd::prepareStreamingBlock(cmd, rt.fill_resp_buf, sizeof(rt.resp_buf_a));
  if (response.type != mg24_cmd::RESP_BLOCK) {
    return;
  }

  rt.next_block_len = response.len;
  rt.next_block_ready = true;
}

}  // namespace

void begin(Runtime &rt) {
  g_runtime = &rt;

  pinMode(kPinDrdy, OUTPUT);
  drdyWrite(false);

  pinMode(kPinCs, INPUT_PULLUP);
  attachInterrupt(digitalPinToInterrupt(kPinCs), onCSRising, RISING);

  memset(&rt.spi_handle, 0, sizeof(rt.spi_handle));
  memset(rt.cmd_tx_dummy, 0, sizeof(rt.cmd_tx_dummy));
  rt.armed_resp_buf = rt.resp_buf_a;
  rt.fill_resp_buf = rt.resp_buf_b;
  rt.next_block_ready = false;
  rt.next_block_len = 0;
  rt.stream_resp_armed = false;

  SPIDRV_Init_t init_data = {};
  init_data.port = EUSART1;
  init_data.portTx = kSpiPortTx;
  init_data.pinTx = kSpiPinTx;
  init_data.portRx = kSpiPortRx;
  init_data.pinRx = kSpiPinRx;
  init_data.portClk = kSpiPortClk;
  init_data.pinClk = kSpiPinClk;
  init_data.portCs = kSpiPortCs;
  init_data.pinCs = kSpiPinCs;
  init_data.bitRate = kSpiBitrate;
  init_data.frameLength = 8;
  init_data.dummyTxValue = 0x00;
  init_data.type = spidrvSlave;
  init_data.bitOrder = spidrvBitOrderMsbFirst;
  init_data.clockMode = spidrvClockMode1;
  init_data.csControl = spidrvCsControlAuto;
  init_data.slaveStartMode = spidrvSlaveStartImmediate;

  const Ecode_t e = SPIDRV_Init(&rt.spi_handle, &init_data);
  Serial.print(F("SPIDRV_Init="));
  Serial.println((int)e);

  armCmd(rt);
}

void service(Runtime &rt, mg24_cmd::Runtime &cmd) {
  prefetchNextBlockIfNeeded(rt, cmd);

  if (!rt.cs_rose) {
    return;
  }
  rt.cs_rose = false;

  const uint32_t start = millis();
  while (!rt.xfer_done) {
    if ((millis() - start) > kSpiCallbackTimeoutMs) {
      Serial.println(F("Callback timeout"));
      armCmd(rt);
      return;
    }
  }

  if (rt.xfer_status != 0) {
    Serial.print(F("SPI xfer error: "));
    Serial.println((int)rt.xfer_status);
    armCmd(rt);
    return;
  }

  switch (rt.state) {
    case Runtime::WAIT_CMD: {
      const mg24_cmd::Response response =
          mg24_cmd::processFrame(cmd, rt.cmd_rx_buf, rt.armed_resp_buf, sizeof(rt.resp_buf_a));
      rt.next_block_ready = false;
      rt.next_block_len = 0;
      armResp(rt, rt.armed_resp_buf, response.len,
              response.type == mg24_cmd::RESP_BLOCK && mg24_cmd::isStreaming(cmd));
      break;
    }

    case Runtime::RESP_ARMED: {
      if (rt.stream_resp_armed && mg24_cmd::isStreaming(cmd)) {
        const uint8_t control_byte = rt.rx_sink[0];

        if (control_byte == mg24_proto::kCmdStop) {
          rt.next_block_ready = false;
          rt.next_block_len = 0;
          const mg24_cmd::Response response =
              mg24_cmd::continueStreaming(cmd, control_byte, rt.armed_resp_buf, sizeof(rt.resp_buf_a));
          armResp(rt, rt.armed_resp_buf, response.len, false);
          break;
        }

        uint8_t *completed_buf = rt.armed_resp_buf;
        if (!rt.next_block_ready) {
          const mg24_cmd::Response response =
              mg24_cmd::continueStreaming(cmd, control_byte, rt.fill_resp_buf, sizeof(rt.resp_buf_a));
          uint8_t *next_tx_buf = rt.fill_resp_buf;
          rt.fill_resp_buf = completed_buf;
          rt.next_block_ready = false;
          rt.next_block_len = 0;
          armResp(rt, next_tx_buf, response.len,
                  response.type == mg24_cmd::RESP_BLOCK && mg24_cmd::isStreaming(cmd));
          break;
        }

        armResp(rt, rt.fill_resp_buf, rt.next_block_len, true);
        rt.fill_resp_buf = completed_buf;
        rt.next_block_ready = false;
        rt.next_block_len = 0;
      } else {
        armCmd(rt);
      }
      break;
    }
  }
}

}  // namespace mg24_spi_slave
