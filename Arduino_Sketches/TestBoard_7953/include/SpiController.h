#pragma once

#include <Arduino.h>
#include <SPI.h>
#include <EventResponder.h>

#include "ConfigurableParameters.h"

class SpiController {
 public:
  struct ChipSelect {
#if defined(__IMXRT1062__)
    decltype(portSetRegister(0)) set = nullptr;
    decltype(portClearRegister(0)) clear = nullptr;
    uint32_t mask = 0;
#endif
  };

  SpiController(SPIClass &bus, uint8_t miso, uint8_t mosi, uint8_t sck);

  void begin();
  ChipSelect registerChipSelect(uint8_t cs_pin);
  bool setClockHz(uint32_t clock_hz);
  uint32_t clockHz() const;
  uint16_t transfer16(uint8_t cs_pin, uint16_t tx_word);

  bool startDma16(uint8_t cs_pin, uint16_t tx_word);
  bool dmaComplete();
  bool finishDma16(uint16_t &rx_word);
  void cancelDma16();

  bool beginLpspiSession();
  void endLpspiSession();
  bool startLpspi16(uint8_t cs_pin, uint16_t tx_word);
  // ADCs resolve GPIO registers at begin(), not for each sampled word.
  bool startLpspi16(const ChipSelect &cs, uint16_t tx_word) {
#if defined(__IMXRT1062__)
    if (transaction_active_ || lpspi_ == nullptr || cs.clear == nullptr) return false;
    const bool single_word = !lpspi_session_active_;
    if (single_word && !beginLpspiSession()) return false;
    lpspi_single_word_ = single_word;
    active_cs_set_ = cs.set;
    active_cs_mask_ = cs.mask;
    transaction_active_ = true;
    // TCF is sticky: require a fresh completion as well as receive readiness.
    lpspi_->SR = LPSPI_SR_TCF;
    *cs.clear = cs.mask;
    lpspi_->TDR = tx_word;
    lpspi_active_ = true;
    return true;
#else
    (void)cs;
    (void)tx_word;
    return false;
#endif
  }
  bool lpspiComplete() const {
#if defined(__IMXRT1062__)
    return lpspi_active_ && lpspi_ != nullptr &&
           !(lpspi_->RSR & LPSPI_RSR_RXEMPTY) && (lpspi_->SR & LPSPI_SR_TCF);
#else
    return false;
#endif
  }
  bool finishLpspi16(uint16_t &rx_word) {
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
  void cancelLpspi16();

 private:
  void releaseChipSelect() {
#if defined(__IMXRT1062__)
    if (active_cs_set_ != nullptr) *active_cs_set_ = active_cs_mask_;
    active_cs_set_ = nullptr;
#endif
    delayNanoseconds(testboard_config::kCsHighTimeNs);
  }
  void endActiveTransfer();

  SPIClass &bus_;
  uint8_t miso_;
  uint8_t mosi_;
  uint8_t sck_;
  uint32_t clock_hz_ = testboard_config::kDefaultSpiClockHz;
  uint8_t active_cs_pin_ = 0xFF;
  bool transaction_active_ = false;
  bool dma_active_ = false;
  bool lpspi_active_ = false;
  bool lpspi_session_active_ = false;
  bool lpspi_single_word_ = false;
  uint32_t saved_tcr_ = 0;
  EventResponder dma_event_;
  uint8_t *dma_tx_ = nullptr;
  uint8_t *dma_rx_ = nullptr;
#if defined(__IMXRT1062__)
  IMXRT_LPSPI_t *lpspi_ = nullptr;
  decltype(portSetRegister(0)) active_cs_set_ = nullptr;
  uint32_t active_cs_mask_ = 0;
#endif
};
