#pragma once

#include "SpiController.h"

enum class SpiEngine : uint8_t { BLOCKING, DMA, LPSPI };

// A route identifies an ADC/array, its MUX, and a zero-based external input.
struct SensorRoute {
  uint8_t array;  // 1..2 (also ADC number)
  uint8_t mux;    // 1..4
  uint8_t input;  // 0..6; input 6 is a sensor only on MUX4
};

bool validSensorRoute(const SensorRoute &route);

class Adc124s101 {
 public:
  Adc124s101(SpiController &spi, uint8_t array_index);
  void begin();
  void disable();
  void selectAddress(uint8_t address, uint32_t settle_us);
  void park(uint32_t settle_us);
  bool transfer(uint8_t adc_input, SpiEngine engine, uint16_t &sample);
  // All routes in a batch must have this ADC and the same MUX address. Prime
  // the one-frame channel selector once, then pipeline the four ADC inputs.
  bool readBatch(const SensorRoute *routes, uint8_t count, uint8_t repeat,
                 SpiEngine engine, uint16_t *samples);
  bool sampleVmid(uint32_t settle_us, SpiEngine engine);
  uint32_t transferErrors() const { return transfer_errors_; }
  uint32_t dataErrors() const { return data_errors_; }

 private:
  void enable(bool enabled);
  SpiController &spi_;
  uint8_t index_;
  uint8_t address_ = 0xFF;
  bool enabled_ = false;
  // DMA abort cannot reset SPIClass's private DMA state. Latch the fault and
  // require a reset instead of reusing buffers that may still be DMA-owned.
  bool faulted_ = false;
  uint32_t transfer_errors_ = 0;
  uint32_t data_errors_ = 0;
};
