#pragma once

#include <Arduino.h>
#include <SPI.h>

// Central hardware and acquisition configuration for PCB_TestBoard_7953.
// Change board-specific values here; controller code should not contain pins.
namespace testboard_config {

static constexpr char kMcuName[] = "TestBoard_7953";
static constexpr uint32_t kUsbSerialBaud = 460800UL;

static constexpr uint8_t kAdcCount = 4;
static constexpr uint8_t kAdcChannels = 16;
static constexpr uint16_t kAdcFullScaleCode = 0x0FFF;

// Physical sensor bias resistors, indexed by zero-based ADC index. These are
// board metadata for future settling/RC measurements; channel 15 is Vmid and
// does not use the sensor bias value.
static constexpr uint32_t kAdcBiasResistorOhms[kAdcCount] = {
    1000000UL, 470000UL, 470000UL, 249000UL};

// ADS7953 specifies up to 20 MHz SCLK. The 30 MHz ceiling retains the fastest
// clock that passed combined four-ADC benchmarking. Frequencies above 20 MHz
// remain experimental and outside the converter specification.
static constexpr uint32_t kDefaultSpiClockHz = 20000000UL;
static constexpr uint32_t kMinSpiClockHz = 100000UL;
static constexpr uint32_t kMaxSpiClockHz = 30000000UL;
static constexpr uint8_t kSpiBitOrder = MSBFIRST;
static constexpr uint8_t kSpiMode = SPI_MODE0;
static constexpr uint32_t kCsHighTimeNs = 40;

// User naming: SPI1 (ADC1 + ADC2). Teensyduino object: SPI.
static constexpr uint8_t kSpi1MisoPin = 12;
static constexpr uint8_t kSpi1MosiPin = 11;
static constexpr uint8_t kSpi1SckPin = 13;
static constexpr uint8_t kAdc1CsPin = 9;
static constexpr uint8_t kAdc2CsPin = 24;

// User naming: SPI2 (ADC3 + ADC4). Teensyduino object: SPI1.
static constexpr uint8_t kSpi2MisoPin = 39;
static constexpr uint8_t kSpi2MosiPin = 26;
static constexpr uint8_t kSpi2SckPin = 27;
static constexpr uint8_t kAdc3CsPin = 32;
static constexpr uint8_t kAdc4CsPin = 33;

// ADS7953 manual-mode power-up default range: false = 0..VREF (2.5V on this
// board), true = 0..2*VREF (5V). Overridable at runtime via the "ref" command.
static constexpr bool kAds7953Range2xVref = false;
static constexpr uint8_t kAds7953PipelineFrames = 2;
static constexpr bool kValidateReturnedChannel = true;
static constexpr uint8_t kDefaultChannelRepeat = 3;
static constexpr uint32_t kSpiTransferTimeoutUs = 1000;

static constexpr uint8_t kMaxChannelSequence = 64;
static constexpr uint8_t kMaxAdcRoutes = 64;
static constexpr uint8_t kDefaultChannels[] = {0, 1, 2, 3, 4};
static constexpr uint8_t kDefaultChannelCount = sizeof(kDefaultChannels);
static constexpr uint8_t kDefaultVmidChannel = 15;
static constexpr bool kDefaultVmidBetweenChannels = false;
static constexpr uint16_t kMaxFrameOps = kMaxAdcRoutes * 5 + 8;

// Optional future 555/PZR hardware. The test board has no 555 circuit, so the
// safe default is disabled and mode PZR returns #NOT_OK. To enable it, assign
// non-conflicting pins, set kEnablePzrHardware=true, and validate on hardware.
static constexpr bool kEnablePzrHardware = false;
static constexpr int8_t kPzrInputPin = -1;
static constexpr int8_t kPzrMuxA0Pin = -1;
static constexpr int8_t kPzrMuxA1Pin = -1;
static constexpr int8_t kPzrMuxA2Pin = -1;
static constexpr int8_t kPzrMuxA3Pin = -1;
static constexpr int8_t kPzrMuxEnablePin = -1;
static constexpr bool kPzrMuxEnableActiveHigh = true;
static constexpr uint32_t kPzrMuxSettleUs = 5;
static constexpr float kDefaultRbOhm = 470.0f;
static constexpr float kDefaultRkOhm = 470.0f;
static constexpr float kDefaultCfF = 22e-9f;
static constexpr float kDefaultRxMaxOhm = 65500.0f;

}  // namespace testboard_config
