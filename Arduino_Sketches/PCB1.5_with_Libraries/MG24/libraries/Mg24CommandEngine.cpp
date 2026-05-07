#include "Mg24CommandEngine.h"

#include "Mg24SharedProtocol.h"

namespace mg24_cmd {

void begin(Runtime &rt, mg24_adc_mux::Runtime &adc) {
  rt.adc = &adc;
}

static Response makeAckResp(uint8_t *resp_buf, uint8_t status, uint8_t b2 = 0, uint8_t b3 = 0) {
  mg24_proto::makeAck(resp_buf, status, b2, b3);
  Response r;
  r.type = RESP_ACK;
  r.len = mg24_proto::kAckFrameLen;
  return r;
}

static Response makeBlockResp(Runtime &rt, uint8_t *resp_buf, uint32_t resp_cap) {
  const uint16_t sample_count = mg24_adc_mux::fillInterleavedBlock(*rt.adc);
  const uint32_t len = mg24_proto::encodeBlock(
      resp_buf,
      resp_cap,
      rt.adc->sample_buf,
      sample_count,
      rt.adc->last_avg_dt_us,
      rt.adc->last_block_start_us,
      rt.adc->last_block_end_us);
  if (len == 0) {
    return makeAckResp(resp_buf, mg24_proto::kAckErr);
  }

  Response r;
  r.type = RESP_BLOCK;
  r.len = len;
  return r;
}

bool isStreaming(const Runtime &rt) {
  return rt.adc != nullptr && mg24_adc_mux::isStreaming(*rt.adc);
}

bool canPrefetchStreaming(const Runtime &rt) {
  if (!isStreaming(rt)) {
    return false;
  }

  const mg24_adc_mux::Runtime &adc = *rt.adc;
  if (adc.cfg.timed_run && (int32_t)(millis() - adc.cfg.run_stop_ms) >= 0) {
    return false;
  }

  return true;
}

Response prepareStreamingBlock(Runtime &rt, uint8_t *resp_buf, uint32_t resp_cap) {
  if (!isStreaming(rt)) {
    return makeAckResp(resp_buf, mg24_proto::kAckErr);
  }
  return makeBlockResp(rt, resp_buf, resp_cap);
}

Response processFrame(Runtime &rt, const uint8_t *cmd_frame, uint8_t *resp_buf, uint32_t resp_cap) {
  if (rt.adc == nullptr || cmd_frame == nullptr || resp_buf == nullptr || resp_cap < mg24_proto::kAckFrameLen) {
    return makeAckResp(resp_buf, mg24_proto::kAckErr);
  }

  const uint8_t cmd = cmd_frame[0];
  const uint8_t nargs = cmd_frame[1];

  switch (cmd) {
    case mg24_proto::kCmdSetChannels: {
      if (nargs < 1) {
        return makeAckResp(resp_buf, mg24_proto::kAckErr);
      }
      const uint8_t count = cmd_frame[2];
      if (count == 0 || count > 16 || nargs != static_cast<uint8_t>(count + 1) ||
          !mg24_adc_mux::setChannels(*rt.adc, cmd_frame + 3, count)) {
        return makeAckResp(resp_buf, mg24_proto::kAckErr);
      }
      return makeAckResp(resp_buf, mg24_proto::kAckOk);
    }

    case mg24_proto::kCmdSetRepeat: {
      if (nargs != 1 || cmd_frame[2] < 1) {
        return makeAckResp(resp_buf, mg24_proto::kAckErr);
      }
      mg24_adc_mux::setRepeat(*rt.adc, cmd_frame[2]);
      return makeAckResp(resp_buf, mg24_proto::kAckOk);
    }

    case mg24_proto::kCmdSetBuffer: {
      if (nargs != 1 || cmd_frame[2] < 1) {
        return makeAckResp(resp_buf, mg24_proto::kAckErr);
      }
      mg24_adc_mux::setBuffer(*rt.adc, cmd_frame[2]);
      return makeAckResp(resp_buf, mg24_proto::kAckOk);
    }

    case mg24_proto::kCmdSetRef: {
      if (nargs != 1 || !mg24_adc_mux::setReference(*rt.adc, cmd_frame[2])) {
        return makeAckResp(resp_buf, mg24_proto::kAckErr);
      }
      return makeAckResp(resp_buf, mg24_proto::kAckOk);
    }

    case mg24_proto::kCmdSetOsr: {
      if (nargs != 1 || !mg24_adc_mux::setOsr(*rt.adc, cmd_frame[2])) {
        return makeAckResp(resp_buf, mg24_proto::kAckErr);
      }
      return makeAckResp(resp_buf, mg24_proto::kAckOk);
    }

    case mg24_proto::kCmdSetGain: {
      if (nargs != 1 || !mg24_adc_mux::setGain(*rt.adc, cmd_frame[2])) {
        return makeAckResp(resp_buf, mg24_proto::kAckErr);
      }
      return makeAckResp(resp_buf, mg24_proto::kAckOk);
    }

    case mg24_proto::kCmdGroundPin: {
      if (nargs != 1 || !mg24_adc_mux::setGroundPin(*rt.adc, cmd_frame[2])) {
        return makeAckResp(resp_buf, mg24_proto::kAckErr);
      }
      return makeAckResp(resp_buf, mg24_proto::kAckOk);
    }

    case mg24_proto::kCmdGroundEn: {
      if (nargs != 1 || cmd_frame[2] > 1) {
        return makeAckResp(resp_buf, mg24_proto::kAckErr);
      }
      mg24_adc_mux::setGroundEnabled(*rt.adc, cmd_frame[2] != 0);
      return makeAckResp(resp_buf, mg24_proto::kAckOk);
    }

    case mg24_proto::kCmdRun:
    case mg24_proto::kCmdContinue: {
      if (cmd == mg24_proto::kCmdRun) {
        if (!mg24_adc_mux::startRun(*rt.adc, cmd_frame + 2, nargs)) {
          return makeAckResp(resp_buf, mg24_proto::kAckErr);
        }
      } else {
        if (!mg24_adc_mux::isStreaming(*rt.adc) || mg24_adc_mux::streamExpired(*rt.adc)) {
          return makeAckResp(resp_buf, mg24_proto::kAckErr);
        }
      }

      const Response response = makeBlockResp(rt, resp_buf, resp_cap);
      if (response.type != RESP_BLOCK) {
        return makeAckResp(resp_buf, mg24_proto::kAckErr);
      }
      return response;
    }

    case mg24_proto::kCmdStop: {
      mg24_adc_mux::stopRun(*rt.adc);
      return makeAckResp(resp_buf, mg24_proto::kAckOk);
    }

    case mg24_proto::kCmdMcuId: {
      return makeAckResp(resp_buf, mg24_proto::kAckOk, 'M', 'G');
    }

    default:
      return makeAckResp(resp_buf, mg24_proto::kAckErr);
  }
}

Response continueStreaming(Runtime &rt, uint8_t control_byte, uint8_t *resp_buf, uint32_t resp_cap) {
  if (rt.adc == nullptr || resp_buf == nullptr || resp_cap < mg24_proto::kAckFrameLen) {
    return makeAckResp(resp_buf, mg24_proto::kAckErr);
  }

  if (control_byte == mg24_proto::kCmdStop) {
    mg24_adc_mux::stopRun(*rt.adc);
    return makeAckResp(resp_buf, mg24_proto::kAckOk);
  }

  if (!mg24_adc_mux::isStreaming(*rt.adc) || mg24_adc_mux::streamExpired(*rt.adc)) {
    return makeAckResp(resp_buf, mg24_proto::kAckErr);
  }

  const Response response = makeBlockResp(rt, resp_buf, resp_cap);
  if (response.type != RESP_BLOCK) {
    return makeAckResp(resp_buf, mg24_proto::kAckErr);
  }
  return response;
}

}  // namespace mg24_cmd
