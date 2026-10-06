#pragma once

#include <Arduino.h>
#include <SPI.h>
#include <EventResponder.h>

#include "ConfigurableParameters.h"

class SpiController {
 public:
  SpiController(SPIClass &bus, uint8_t miso, uint8_t mosi, uint8_t sck);

  void begin();
  void registerChipSelect(uint8_t cs_pin);
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
  bool lpspiComplete() const;
  bool finishLpspi16(uint16_t &rx_word);
  void cancelLpspi16();

 private:
  void releaseChipSelect();
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
#endif
};
