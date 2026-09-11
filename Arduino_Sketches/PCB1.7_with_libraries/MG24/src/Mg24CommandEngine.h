#pragma once

#include <Arduino.h>

#include "Mg24AdcMux.h"

namespace mg24_cmd {

enum RespType : uint8_t {
  RESP_ACK = 0,
  RESP_BLOCK = 1,
};

struct Response {
  RespType type = RESP_ACK;
  uint32_t len = 0;
};

struct Runtime {
  mg24_adc_mux::Runtime *adc = nullptr;
};

void begin(Runtime &rt, mg24_adc_mux::Runtime &adc);
Response processFrame(Runtime &rt, const uint8_t *cmd_frame, uint8_t *resp_buf, uint32_t resp_cap);
Response continueStreaming(Runtime &rt, uint8_t control_byte, uint8_t *resp_buf, uint32_t resp_cap);
bool isStreaming(const Runtime &rt);
bool canPrefetchStreaming(const Runtime &rt);
Response prepareStreamingBlock(Runtime &rt, uint8_t *resp_buf, uint32_t resp_cap);

}  // namespace mg24_cmd
