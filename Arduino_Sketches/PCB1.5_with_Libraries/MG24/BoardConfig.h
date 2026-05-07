#pragma once

#include <Arduino.h>
#include <sl_gpio.h>

#include "libraries/Mg24AdcMux.h"
#include "libraries/Mg24SpiSlaveTransport.h"

namespace board_config {

static constexpr uint32_t kSerialBaud = 115200;

static constexpr int kAdcMux1Pin = D1;
static constexpr int kAdcMux2Pin = D2;
static constexpr int kMuxA0Pin = D3;
static constexpr int kMuxA1Pin = D4;
static constexpr int kMuxA2Pin = D5;
static constexpr int kMuxA3Pin = D6;

static constexpr int kSpiCsPin = D0;
static constexpr int kSpiDrdyPin = D7;
static constexpr uint32_t kSpiCallbackTimeoutMs = 200;

static inline mg24_adc_mux::Pins makeAdcMuxPins() {
  mg24_adc_mux::Pins pins;
  pins.adc_mux1 = kAdcMux1Pin;
  pins.adc_mux2 = kAdcMux2Pin;
  pins.mux_a0 = kMuxA0Pin;
  pins.mux_a1 = kMuxA1Pin;
  pins.mux_a2 = kMuxA2Pin;
  pins.mux_a3 = kMuxA3Pin;
  return pins;
}

static inline mg24_spi_slave::Config makeSpiSlaveConfig() {
  mg24_spi_slave::Config config;
  config.cs_pin = kSpiCsPin;
  config.drdy_pin = kSpiDrdyPin;
  config.callback_timeout_ms = kSpiCallbackTimeoutMs;

  config.init_data.port = EUSART1;
  config.init_data.portTx = SL_GPIO_PORT_A;
  config.init_data.pinTx = 5;
  config.init_data.portRx = SL_GPIO_PORT_A;
  config.init_data.pinRx = 4;
  config.init_data.portClk = SL_GPIO_PORT_A;
  config.init_data.pinClk = 3;
  config.init_data.portCs = SL_GPIO_PORT_C;
  config.init_data.pinCs = 0;
  config.init_data.bitRate = 4000000UL;
  config.init_data.frameLength = 8;
  config.init_data.dummyTxValue = 0x00;
  config.init_data.type = spidrvSlave;
  config.init_data.bitOrder = spidrvBitOrderMsbFirst;
  config.init_data.clockMode = spidrvClockMode1;
  config.init_data.csControl = spidrvCsControlAuto;
  config.init_data.slaveStartMode = spidrvSlaveStartImmediate;

  return config;
}

}  // namespace board_config