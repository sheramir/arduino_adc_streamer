#include "SpiController.h"

#include "ConfigurableParameters.h"

namespace {
DMAMEM static uint8_t g_dma_tx[2][32] __attribute__((aligned(32)));
DMAMEM static uint8_t g_dma_rx[2][32] __attribute__((aligned(32)));
#if defined(__IMXRT1062__)
// Match SPISettings' command format without reading asynchronous TCR state.
// RT1060 RM 48.4.1.15 warns that a read during FIFO command loading can be wrong.
constexpr uint32_t kSpiCommand = LPSPI_TCR_FRAMESZ(7) |
    (testboard_config::kSpiBitOrder == LSBFIRST ? LPSPI_TCR_LSBF : 0u) |
    (testboard_config::kSpiMode & 0x08 ? LPSPI_TCR_CPOL : 0u) |
    (testboard_config::kSpiMode & 0x04 ? LPSPI_TCR_CPHA : 0u);
constexpr uint32_t kLpspiCommand =
    (kSpiCommand & ~LPSPI_TCR_FRAMESZ(0xFFF)) | LPSPI_TCR_FRAMESZ(15);
#endif
}

SpiController::SpiController(SPIClass &bus, uint8_t miso, uint8_t mosi, uint8_t sck)
    : bus_(bus), miso_(miso), mosi_(mosi), sck_(sck) {
#if defined(__IMXRT1062__)
  if (&bus_ == &SPI) {
    lpspi_ = &IMXRT_LPSPI4_S;
    dma_tx_ = g_dma_tx[0];
    dma_rx_ = g_dma_rx[0];
  } else if (&bus_ == &SPI1) {
    lpspi_ = &IMXRT_LPSPI3_S;
    dma_tx_ = g_dma_tx[1];
    dma_rx_ = g_dma_rx[1];
  }
#endif
}

void SpiController::begin() {
  bus_.setMISO(miso_);
  bus_.setMOSI(mosi_);
  bus_.setSCK(sck_);
  bus_.begin();
}

void SpiController::registerChipSelect(uint8_t cs_pin) {
  pinMode(cs_pin, OUTPUT);
  digitalWriteFast(cs_pin, HIGH);
}

bool SpiController::setClockHz(uint32_t clock_hz) {
  if (transaction_active_ || lpspi_session_active_ ||
      clock_hz < testboard_config::kMinSpiClockHz ||
      clock_hz > testboard_config::kMaxSpiClockHz) {
    return false;
  }
  clock_hz_ = clock_hz;
  return true;
}

uint32_t SpiController::clockHz() const {
  return clock_hz_;
}

uint16_t SpiController::transfer16(uint8_t cs_pin, uint16_t tx_word) {
  // The blocking path must never inherit the direct engine's 16-bit session.
  endLpspiSession();
  const SPISettings settings(
      clock_hz_,
      testboard_config::kSpiBitOrder,
      testboard_config::kSpiMode);
  bus_.beginTransaction(settings);
  digitalWriteFast(cs_pin, LOW);
  const uint16_t rx_word = bus_.transfer16(tx_word);
  digitalWriteFast(cs_pin, HIGH);
  bus_.endTransaction();
  delayNanoseconds(testboard_config::kCsHighTimeNs);
  return rx_word;
}

bool SpiController::startDma16(uint8_t cs_pin, uint16_t tx_word) {
#if defined(SPI_HAS_TRANSFER_ASYNC)
  if (transaction_active_ || lpspi_session_active_ ||
      dma_tx_ == nullptr || dma_rx_ == nullptr) {
    return false;
  }
  dma_tx_[0] = static_cast<uint8_t>(tx_word >> 8);
  dma_tx_[1] = static_cast<uint8_t>(tx_word & 0xFF);
  dma_rx_[0] = 0;
  dma_rx_[1] = 0;
  dma_event_.clearEvent();
  const SPISettings settings(
      clock_hz_,
      testboard_config::kSpiBitOrder,
      testboard_config::kSpiMode);
  bus_.beginTransaction(settings);
  active_cs_pin_ = cs_pin;
  transaction_active_ = true;
  digitalWriteFast(cs_pin, LOW);
  if (!bus_.transfer(dma_tx_, dma_rx_, 2, dma_event_)) {
    endActiveTransfer();
    return false;
  }
  dma_active_ = true;
  return true;
#else
  (void)cs_pin;
  (void)tx_word;
  return false;
#endif
}

bool SpiController::dmaComplete() {
  return dma_active_ && static_cast<bool>(dma_event_);
}

bool SpiController::finishDma16(uint16_t &rx_word) {
  if (!dmaComplete()) return false;
  rx_word = (static_cast<uint16_t>(dma_rx_[0]) << 8) | dma_rx_[1];
  dma_event_.clearEvent();
  dma_active_ = false;
  endActiveTransfer();
  return true;
}

void SpiController::cancelDma16() {
  if (!dma_active_ && !transaction_active_) return;
#if defined(__IMXRT1062__)
  if (lpspi_ != nullptr) {
    lpspi_->DER = 0;
    lpspi_->CR = LPSPI_CR_MEN | LPSPI_CR_RRF | LPSPI_CR_RTF;
  }
#endif
  dma_active_ = false;
  dma_event_.clearEvent();
  endActiveTransfer();
}

bool SpiController::beginLpspiSession() {
#if defined(__IMXRT1062__)
  if (transaction_active_ || lpspi_ == nullptr) return false;
  if (lpspi_session_active_) return true;
  const SPISettings settings(
      clock_hz_,
      testboard_config::kSpiBitOrder,
      testboard_config::kSpiMode);
  bus_.beginTransaction(settings);
  // Flush once with the peripheral disabled, then queue a known 16-bit command
  // before enabling. Never derive the command from TCR readback after a flush.
  lpspi_->CR = 0;
  lpspi_->DER = 0;
  lpspi_->CR = LPSPI_CR_RRF | LPSPI_CR_RTF;
  lpspi_->SR = 0x3F00;
  saved_tcr_ = kSpiCommand;
  lpspi_->TCR = kLpspiCommand;
  lpspi_->CR = LPSPI_CR_MEN;
  lpspi_session_active_ = true;
  return true;
#else
  return false;
#endif
}

void SpiController::endLpspiSession() {
#if defined(__IMXRT1062__)
  if (!lpspi_session_active_) return;
  if (lpspi_active_) {
    lpspi_single_word_ = false;
    cancelLpspi16();
  }
  lpspi_->TCR = saved_tcr_;
  bus_.endTransaction();
  lpspi_session_active_ = false;
#endif
}

bool SpiController::startLpspi16(uint8_t cs_pin, uint16_t tx_word) {
#if defined(__IMXRT1062__)
  if (transaction_active_ || lpspi_ == nullptr) return false;
  const bool single_word = !lpspi_session_active_;
  if (!beginLpspiSession()) return false;
  lpspi_single_word_ = single_word;
  active_cs_pin_ = cs_pin;
  transaction_active_ = true;
  // TCF is sticky. Clear the previous word's completion before submitting this
  // one so GPIO CS cannot rise on stale completion or only an RX-ready edge.
  lpspi_->SR = LPSPI_SR_TCF;
  digitalWriteFast(cs_pin, LOW);
  lpspi_->TDR = tx_word;
  lpspi_active_ = true;
  return true;
#else
  (void)cs_pin;
  (void)tx_word;
  return false;
#endif
}

bool SpiController::lpspiComplete() const {
#if defined(__IMXRT1062__)
  return lpspi_active_ && lpspi_ != nullptr &&
         !(lpspi_->RSR & LPSPI_RSR_RXEMPTY) && (lpspi_->SR & LPSPI_SR_TCF);
#else
  return false;
#endif
}

bool SpiController::finishLpspi16(uint16_t &rx_word) {
#if defined(__IMXRT1062__)
  if (!lpspiComplete()) return false;
  rx_word = static_cast<uint16_t>(lpspi_->RDR);
  lpspi_active_ = false;
  releaseChipSelect();
  transaction_active_ = false;
  if (lpspi_single_word_) endLpspiSession();
  return true;
#else
  (void)rx_word;
  return false;
#endif
}

void SpiController::cancelLpspi16() {
#if defined(__IMXRT1062__)
  if (lpspi_active_ && lpspi_ != nullptr) {
    lpspi_->CR = 0;
    lpspi_->DER = 0;
    lpspi_->CR = LPSPI_CR_RRF | LPSPI_CR_RTF;
    lpspi_->SR = 0x3F00;
    lpspi_->TCR = kLpspiCommand;
    lpspi_->CR = LPSPI_CR_MEN;
  }
#endif
  lpspi_active_ = false;
  releaseChipSelect();
  transaction_active_ = false;
  if (lpspi_single_word_) endLpspiSession();
}

void SpiController::releaseChipSelect() {
  if (active_cs_pin_ != 0xFF) digitalWriteFast(active_cs_pin_, HIGH);
  delayNanoseconds(testboard_config::kCsHighTimeNs);
  active_cs_pin_ = 0xFF;
}

void SpiController::endActiveTransfer() {
  if (!transaction_active_) return;
  if (active_cs_pin_ != 0xFF) digitalWriteFast(active_cs_pin_, HIGH);
  bus_.endTransaction();
  delayNanoseconds(testboard_config::kCsHighTimeNs);
  active_cs_pin_ = 0xFF;
  transaction_active_ = false;
}
