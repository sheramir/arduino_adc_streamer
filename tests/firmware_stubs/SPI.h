#pragma once
#include "Arduino.h"
#include "EventResponder.h"
#define SPI_HAS_TRANSFER_ASYNC 1
#define MSBFIRST 1
#define LSBFIRST 0
#define SPI_MODE0 0
#define LPSPI_CR_MEN 1u
#define LPSPI_CR_RRF 2u
#define LPSPI_CR_RTF 4u
#define LPSPI_TCR_FRAMESZ(n) (static_cast<uint32_t>(n))
#define LPSPI_RSR_RXEMPTY 1u
#define LPSPI_SR_MBF (1u << 24)
#define LPSPI_SR_TCF (1u << 10)
#define LPSPI_TCR_LSBF (1u << 23)
#define LPSPI_TCR_CPOL (1u << 31)
#define LPSPI_TCR_CPHA (1u << 30)
#define LPSPI_TCR_CONT (1u << 21)
#define LPSPI_TCR_RXMSK (1u << 19)

// NXP documents that TCR reads can be incorrect while a queued command loads.
// The original plain-integer stub could not exercise that failure mode.
struct FakeCommand {
  uint32_t value = 7;
  bool unstable_read = false;
  unsigned unstable_reads = 0;
  operator uint32_t() {
    if (unstable_read) { ++unstable_reads; return value | LPSPI_TCR_CONT | LPSPI_TCR_RXMSK; }
    return value;
  }
  void operator=(uint32_t command) { value = command; }
};

// SR completion flags are write-one-to-clear; MBF is read-only.
struct FakeStatus {
  uint32_t value = 0;
  unsigned completion_reads = 0;
  operator uint32_t() {
    if (completion_reads && !--completion_reads) {
      value |= LPSPI_SR_TCF;
      value &= ~LPSPI_SR_MBF;
    }
    return value;
  }
  void operator=(uint32_t mask) {
    value &= ~(mask & 0x3F00u);
    if (mask & LPSPI_SR_TCF) completion_reads = 0;
  }
};

struct IMXRT_LPSPI_t;
struct FakeReceive {
  IMXRT_LPSPI_t *owner;
  uint32_t value = 0;
  operator uint32_t();
};
struct FakeTransmit {
  IMXRT_LPSPI_t *owner;
  void operator=(uint32_t command);
};
struct IMXRT_LPSPI_t {
  uint32_t CR = 0, RSR = LPSPI_RSR_RXEMPTY, DER = 0;
  FakeStatus SR;
  FakeCommand TCR;
  FakeReceive RDR{this};
  FakeTransmit TDR{this};
  bool stall = false;
  unsigned completion_reads = 0;
};
extern IMXRT_LPSPI_t IMXRT_LPSPI4_S, IMXRT_LPSPI3_S;
uint16_t emulate_conversion(IMXRT_LPSPI_t *bus, uint16_t command);

inline FakeReceive::operator uint32_t() { owner->RSR = LPSPI_RSR_RXEMPTY; return value; }
inline unsigned fake_stalled_words = 0;
inline void FakeTransmit::operator=(uint32_t command) {
  assert(!(owner->SR.value & LPSPI_SR_TCF)); // completion must be cleared per word
  if (owner->stall || (owner->TCR.value & LPSPI_TCR_RXMSK)) {
    ++fake_stalled_words;
    owner->SR.value |= LPSPI_SR_MBF; owner->RSR = LPSPI_RSR_RXEMPTY; return;
  }
  assert((owner->TCR.value & 0xFFFu) == 15);
  owner->RDR.value = emulate_conversion(owner, static_cast<uint16_t>(command));
  owner->RSR = 0;
  if (owner->completion_reads) {
    owner->SR.completion_reads = owner->completion_reads;
    owner->SR.value |= LPSPI_SR_MBF;
  } else {
    owner->SR.value &= ~LPSPI_SR_MBF;
    owner->SR.value |= LPSPI_SR_TCF;
  }
}

struct SPISettings { SPISettings(uint32_t, uint8_t, uint8_t) {} };
class SPIClass {
 public:
  explicit SPIClass(IMXRT_LPSPI_t *registers) : regs(registers) {}
  void setMISO(uint8_t) {} void setMOSI(uint8_t) {} void setSCK(uint8_t) {} void begin() {}
  void beginTransaction(SPISettings) { ++begins; regs->TCR = 7; regs->RSR = LPSPI_RSR_RXEMPTY; }
  void endTransaction() { ++ends; }
  uint16_t transfer16(uint16_t command) { return emulate_conversion(regs, command); }
  bool transfer(uint8_t *tx, uint8_t *rx, size_t n, EventResponder &event) {
    assert(n == 2);
    auto word = emulate_conversion(regs, static_cast<uint16_t>((tx[0] << 8) | tx[1]));
    rx[0] = word >> 8; rx[1] = word & 255; event.ready = true; return true;
  }
  IMXRT_LPSPI_t *regs;
  unsigned begins = 0, ends = 0;
};
extern SPIClass SPI, SPI1;
