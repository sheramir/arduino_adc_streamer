#pragma once

#include <Arduino.h>
#include "spidrv.h"

#include "Mg24CommandEngine.h"
#include "Mg24SharedProtocol.h"

namespace mg24_spi_slave {

struct Config {
  int cs_pin = -1;
  int drdy_pin = -1;
  uint32_t callback_timeout_ms = 0;
  SPIDRV_Init_t init_data = {};
};

struct Runtime {
  enum State : uint8_t {
    WAIT_CMD = 0,
    RESP_ARMED = 1,
  };

  Config config;
  SPIDRV_HandleData_t spi_handle = {};
  volatile bool xfer_done = false;
  volatile Ecode_t xfer_status = (Ecode_t)0xFFFFu;
  volatile bool cs_rose = false;
  State state = WAIT_CMD;

  uint8_t cmd_rx_buf[mg24_proto::kCmdFrameLen] = {0};
  uint8_t cmd_tx_dummy[mg24_proto::kCmdFrameLen] = {0};
  uint8_t resp_buf_a[mg24_proto::kMaxResponseBytes] = {0};
  uint8_t resp_buf_b[mg24_proto::kMaxResponseBytes] = {0};
  uint8_t *armed_resp_buf = nullptr;
  uint8_t *fill_resp_buf = nullptr;
  uint8_t rx_sink[mg24_proto::kMaxResponseBytes] = {0};
  uint32_t resp_len = 0;
  bool stream_resp_armed = false;
  bool next_block_ready = false;
  uint32_t next_block_len = 0;
};

void begin(Runtime &rt, const Config &config);
void service(Runtime &rt, mg24_cmd::Runtime &cmd);

}  // namespace mg24_spi_slave
