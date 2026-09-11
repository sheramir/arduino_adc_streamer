#include "Firmware.h"

#include <Arduino.h>
#include <SPI.h>

#include "../ConfigurableParameters.h"
#include "Ads7953Adc.h"
#include "ApiProtocol.h"
#include "PzrController.h"
#include "PztController.h"
#include "SpiController.h"
#include "UsbSerialController.h"

namespace testboard_firmware {
namespace {

enum DeviceMode { MODE_PZT, MODE_PZR };

UsbSerialController g_usb;
SpiController g_spi1(SPI, testboard_config::kSpi1MisoPin,
                     testboard_config::kSpi1MosiPin, testboard_config::kSpi1SckPin);
SpiController g_spi2(SPI1, testboard_config::kSpi2MisoPin,
                     testboard_config::kSpi2MosiPin, testboard_config::kSpi2SckPin);
Ads7953Adc g_adc1(g_spi1, testboard_config::kAdc1CsPin);
Ads7953Adc g_adc2(g_spi1, testboard_config::kAdc2CsPin);
Ads7953Adc g_adc3(g_spi2, testboard_config::kAdc3CsPin);
Ads7953Adc g_adc4(g_spi2, testboard_config::kAdc4CsPin);
AdcDevice *g_adcs[] = {&g_adc1, &g_adc2, &g_adc3, &g_adc4};
PztController g_pzt(g_adcs, sizeof(g_adcs) / sizeof(g_adcs[0]), g_usb);
PzrController g_pzr(g_usb);
DeviceMode g_mode = MODE_PZT;

void printMcu() {
  Serial.print(F("# "));
  Serial.println(testboard_config::kMcuName);
}

void printHelp() {
  Serial.println(F("# Commands are terminated by '*'."));
  Serial.println(F("# mode PZT|PZR, mcu, help, status, stop"));
  Serial.println(F("# channels 0..15, repeat n, buffer n, run [ms]"));
  Serial.println(F("# PZT: ground channel|true|false, ref, osr, gain"));
  Serial.println(F("# PZR: rb, rk, cf, rxmax, ascii (requires enabled 555 hardware)"));
  Serial.println(F("# PZT order: channel -> repeat -> ADC1,ADC2,ADC3,ADC4"));
}

bool switchMode(const String &arguments) {
  String mode = arguments;
  mode.toUpperCase();
  if (mode == "PZT") {
    g_pzr.stop();
    g_mode = MODE_PZT;
    return true;
  }
  if (mode == "PZR" && g_pzr.available()) {
    g_pzt.stop();
    g_mode = MODE_PZR;
    return true;
  }
  if (mode == "PZR") {
    Serial.println(F("# ERROR: PZR hardware is disabled in ConfigurableParameters.h"));
  }
  return false;
}

void handleLine(const String &raw_line) {
  String line = raw_line;
  line.trim();
  if (!line.length()) return;

  String command;
  String arguments;
  api_protocol::splitCommand(line, command, arguments);

  if (command == "mcu") {
    printMcu();
    g_usb.writeAck(true, arguments);
    return;
  }
  if (command == "help") {
    printHelp();
    g_usb.writeAck(true, arguments);
    return;
  }
  if (command == "status") {
    Serial.print(F("# Current mode: "));
    Serial.println(g_mode == MODE_PZT ? F("PZT") : F("PZR"));
    if (g_mode == MODE_PZT) g_pzt.printStatus(); else g_pzr.printStatus();
    g_usb.writeAck(true, arguments);
    return;
  }
  if (command == "mode") {
    g_usb.writeAck(switchMode(arguments), arguments);
    return;
  }
  if (command == "stop") {
    g_pzt.stop();
    g_pzr.stop();
    g_usb.writeAck(true, arguments);
    return;
  }

  const bool success = g_mode == MODE_PZT
      ? g_pzt.handleCommand(command, arguments)
      : g_pzr.handleCommand(command, arguments);
  // Match PCB1.7: PZT run transitions directly to binary data without a text
  // ACK. Other commands retain the existing #OK/#NOT_OK convention.
  if (!(g_mode == MODE_PZT && command == "run" && success)) {
    g_usb.writeAck(success, arguments);
  }
}

}  // namespace

void setupFirmware() {
  g_usb.begin(testboard_config::kUsbSerialBaud);
  g_spi1.begin();
  g_spi2.begin();
  g_pzt.begin();
  g_pzr.begin();
  printMcu();
  Serial.println(F("# Default mode: PZT; four ADS7953 lanes; two sensor arrays"));
}

void loopFirmware() {
  String line;
  while (g_usb.readCommand(line)) {
    handleLine(line);
  }
  if (g_mode == MODE_PZT) g_pzt.service(); else g_pzr.service();
  yield();
}

}  // namespace testboard_firmware
