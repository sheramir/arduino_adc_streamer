#pragma once

#include <Arduino.h>
#include <SPI.h>

namespace testboard_config {
static constexpr char kMcuName[] = "TestBoard_ADC124";
static constexpr uint32_t kUsbSerialBaud = 460800;
static constexpr float kReferenceVolts = 3.3f;
static constexpr float kVmidVolts = kReferenceVolts / 2.0f;
// TI specifies ADC124S101 AC performance at 8..16 MHz, not the ADS7953 clocks.
static constexpr uint32_t kDefaultSpiClockHz = 16000000;
static constexpr uint32_t kMinSpiClockHz = 8000000;
static constexpr uint32_t kMaxSpiClockHz = 16000000;
static constexpr uint8_t kSpiBitOrder = MSBFIRST;
static constexpr uint8_t kSpiMode = SPI_MODE0;
static constexpr uint32_t kCsHighTimeNs = 100;
static constexpr uint32_t kCsSetupTimeNs = 100;
static constexpr uint32_t kSpiTransferTimeoutUs = 1000;
static constexpr uint8_t kMisoPin = 12, kMosiPin = 11, kSckPin = 13;
static constexpr uint8_t kCsPins[] = {9, 24};
static constexpr uint8_t kMuxEnablePins[] = {0, 32};
static constexpr uint8_t kMuxAddressPins[2][3] = {{1, 2, 3}, {29, 30, 31}};
// TMUX1108: EN high; TMUX1308A: EN low. Set these to match any board inverter.
static constexpr bool kMuxEnableActiveHigh[] = {true, false};
// Wait for switch turn-off before sequential GPIO address writes.
static constexpr uint32_t kMuxDisableTimeNs = 200;
static constexpr uint32_t kDefaultMuxSettleUs = 5;
static constexpr uint32_t kMaxMuxSettleUs = 1000;
static constexpr uint8_t kVmidAddress = 7;
static constexpr uint8_t kMaxRoutes = 50;
static constexpr uint32_t kBiasResistorOhms[2][4] = {
    {470000, 1000000, 470000, 1000000},
    {1000000, 470000, 1000000, 470000}};
// MUX1..4 -> ADC IN1..4 is an assumed PCB connection; adjust if needed.
static constexpr uint8_t kMuxToAdcInput[4] = {0, 1, 2, 3};
}  // namespace testboard_config
