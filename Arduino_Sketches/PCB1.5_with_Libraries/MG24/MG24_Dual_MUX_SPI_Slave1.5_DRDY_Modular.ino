/*
 * Modular MG24 sketch for PCB1.5.
 *
 * This version preserves the original SPI slave transport and ADC streaming
 * behavior, but moves the command and ADC functionality into libraries.
 */

#include <Arduino.h>

#include "BoardConfig.h"

#include "libraries/Mg24AdcMux.h"
#include "libraries/Mg24CommandEngine.h"
#include "libraries/Mg24SpiSlaveTransport.h"

static mg24_adc_mux::Runtime g_adc;
static mg24_cmd::Runtime g_cmd;
static mg24_spi_slave::Runtime g_spi;

void setup() {
  Serial.begin(board_config::kSerialBaud);
  while (!Serial) {
  }

  const mg24_adc_mux::Pins pins = board_config::makeAdcMuxPins();
  const mg24_spi_slave::Config spi_config = board_config::makeSpiSlaveConfig();

  mg24_adc_mux::begin(g_adc, pins);
  mg24_cmd::begin(g_cmd, g_adc);
  mg24_spi_slave::begin(g_spi, spi_config);

  Serial.println(F("MG24 Dual-MUX Slave ready (DRDY on D7, modular)"));
}

void loop() {
  mg24_spi_slave::service(g_spi, g_cmd);
}
