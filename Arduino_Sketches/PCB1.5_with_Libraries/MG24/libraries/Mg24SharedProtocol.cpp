#include "Mg24SharedProtocol.h"

namespace mg24_proto {

void makeAck(uint8_t *out_ack, uint8_t status, uint8_t b2, uint8_t b3) {
  out_ack[0] = kAckMagic;
  out_ack[1] = status;
  out_ack[2] = b2;
  out_ack[3] = b3;
}

uint32_t encodeBlock(
    uint8_t *dst,
    uint32_t dst_cap,
    const uint16_t *samples,
    uint16_t sample_count,
    uint16_t avg_dt_us,
    uint32_t block_start_us,
    uint32_t block_end_us) {
  const uint32_t payload_bytes = static_cast<uint32_t>(sample_count) * sizeof(uint16_t);
  const uint32_t total_bytes = 4 + payload_bytes + kBlockTrailerLen;
  if (dst_cap < total_bytes) {
    return 0;
  }

  dst[0] = kBlockMagic1;
  dst[1] = kBlockMagic2;
  dst[2] = static_cast<uint8_t>(sample_count & 0xFF);
  dst[3] = static_cast<uint8_t>((sample_count >> 8) & 0xFF);

  memcpy(dst + 4, samples, payload_bytes);

  uint8_t *trail = dst + 4 + payload_bytes;
  trail[0] = static_cast<uint8_t>(avg_dt_us & 0xFF);
  trail[1] = static_cast<uint8_t>((avg_dt_us >> 8) & 0xFF);

  trail[2] = static_cast<uint8_t>(block_start_us & 0xFF);
  trail[3] = static_cast<uint8_t>((block_start_us >> 8) & 0xFF);
  trail[4] = static_cast<uint8_t>((block_start_us >> 16) & 0xFF);
  trail[5] = static_cast<uint8_t>((block_start_us >> 24) & 0xFF);

  trail[6] = static_cast<uint8_t>(block_end_us & 0xFF);
  trail[7] = static_cast<uint8_t>((block_end_us >> 8) & 0xFF);
  trail[8] = static_cast<uint8_t>((block_end_us >> 16) & 0xFF);
  trail[9] = static_cast<uint8_t>((block_end_us >> 24) & 0xFF);

  return total_bytes;
}

}  // namespace mg24_proto
