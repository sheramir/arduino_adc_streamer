#include "Mg24SpiSlaveTransport.h"

namespace mg24_spi_slave {

namespace {

static Runtime *g_runtime = nullptr;

static bool hasValidConfig(const Config &config) {
  return config.cs_pin >= 0 &&
         config.drdy_pin >= 0 &&
         config.callback_timeout_ms > 0 &&
         config.init_data.bitRate > 0 &&
         config.init_data.port != nullptr;
}

static inline void drdyWrite(bool asserted) {
  if (g_runtime == nullptr || g_runtime->config.drdy_pin < 0) {
    return;
  }
  digitalWrite(g_runtime->config.drdy_pin, asserted ? HIGH : LOW);
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

void begin(Runtime &rt, const Config &config) {
  g_runtime = &rt;
  rt.config = config;

  if (!hasValidConfig(rt.config)) {
    Serial.println(F("SPI transport config missing"));
    g_runtime = nullptr;
    return;
  }

  pinMode(rt.config.drdy_pin, OUTPUT);
  drdyWrite(false);

  pinMode(rt.config.cs_pin, INPUT_PULLUP);
  attachInterrupt(digitalPinToInterrupt(rt.config.cs_pin), onCSRising, RISING);

  memset(&rt.spi_handle, 0, sizeof(rt.spi_handle));
  memset(rt.cmd_tx_dummy, 0, sizeof(rt.cmd_tx_dummy));
  rt.armed_resp_buf = rt.resp_buf_a;
  rt.fill_resp_buf = rt.resp_buf_b;
  rt.next_block_ready = false;
  rt.next_block_len = 0;
  rt.stream_resp_armed = false;

  SPIDRV_Init_t init_data = rt.config.init_data;

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
    if ((millis() - start) > rt.config.callback_timeout_ms) {
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
