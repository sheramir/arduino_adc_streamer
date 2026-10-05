// Execute the production ADC driver against simulated GPIO and delayed ADC
// channel selection. No board, Arduino core, or modified production driver.
#include "Adc124s101.h"
#include <assert.h>
#include <stdio.h>

namespace {
int latch[40] = {}, direction[40] = {};
uint8_t selected_input[2] = {3, 2};
uint16_t commands[256];
uint16_t command_count = 0;
uint32_t clock_us = 0, delay_us = 0;
bool complete = true, corrupt = false;
uint8_t pending_cs = 0;
uint16_t pending_command = 0;

uint16_t convert(uint8_t cs, uint16_t command) {
  assert(cs == 9 || cs == 24);
  assert((command & ~0x1800) == 0);  // command bits 12:11 only
  commands[command_count++] = command;
  uint8_t array = cs == 9 ? 0 : 1;
  const uint8_t *pins = testboard_config::kMuxAddressPins[array];
  uint8_t address = latch[pins[0]] | (latch[pins[1]] << 1) | (latch[pins[2]] << 2);
  assert(latch[testboard_config::kMuxEnablePins[array]] ==
         testboard_config::kMuxEnableActiveHigh[array]);
  uint16_t result = (array + 1) * 1000 + selected_input[array] * 100 + address;
  selected_input[array] = (command >> 11) & 3;
  return corrupt ? result | 0x8000 : result;
}
}

void digitalWrite(uint8_t pin, int value) { latch[pin] = value; }
void pinMode(uint8_t pin, int mode) { direction[pin] = mode; }
void delayNanoseconds(uint32_t) {}
void delayMicroseconds(uint32_t us) { delay_us += us; }
uint32_t micros() { clock_us += 100; return clock_us; }
void yield() {}

SpiController::SpiController(SPIClass &bus, uint8_t miso, uint8_t mosi, uint8_t sck)
    : bus_(bus), miso_(miso), mosi_(mosi), sck_(sck) {}
void SpiController::registerChipSelect(uint8_t cs) { pinMode(cs, OUTPUT); digitalWrite(cs, HIGH); }
uint16_t SpiController::transfer16(uint8_t cs, uint16_t word) { return convert(cs, word); }
bool SpiController::startDma16(uint8_t cs, uint16_t word) {
  pending_cs = cs; pending_command = word; return true;
}
bool SpiController::startLpspi16(uint8_t cs, uint16_t word) { return startDma16(cs, word); }
bool SpiController::dmaComplete() { return complete; }
bool SpiController::lpspiComplete() const { return complete; }
bool SpiController::finishDma16(uint16_t &word) { word = convert(pending_cs, pending_command); return true; }
bool SpiController::finishLpspi16(uint16_t &word) { return finishDma16(word); }
void SpiController::cancelDma16() { pending_cs = 0; }
void SpiController::cancelLpspi16() { pending_cs = 0; }

int main() {
  SPIClass bus;
  SpiController spi(bus, 12, 11, 13);
  Adc124s101 first(spi, 0), second(spi, 1);
  first.begin(); second.begin();
  assert(latch[0] == HIGH && latch[32] == LOW);
  assert(latch[1] && latch[2] && latch[3] && latch[29] && latch[30] && latch[31]);
  first.disable(); second.disable();
  assert(latch[0] == LOW && latch[32] == HIGH);
  first.selectAddress(5, 5); second.selectAddress(5, 5);
  assert(latch[1] == 1 && latch[2] == 0 && latch[3] == 1);
  assert(latch[29] == 1 && latch[30] == 0 && latch[31] == 1);
  const uint32_t delay_before = delay_us;
  first.selectAddress(5, 5);
  assert(delay_us == delay_before);  // no redundant settling for same address

  // Deliberately sparse, unsorted ADC input order; initial selected input is
  // different. Test repeats 1..3 and all three engines against actual driver.
  const SpiEngine engines[] = {SpiEngine::BLOCKING, SpiEngine::DMA, SpiEngine::LPSPI};
  for (SpiEngine engine : engines) {
    for (uint8_t repeat = 1; repeat <= 3; ++repeat) {
      command_count = 0;
      SensorRoute routes[] = {{1, 4, 5}, {1, 1, 5}, {1, 3, 5}};
      uint16_t samples[3] = {};
      assert(first.readBatch(routes, 3, repeat, engine, samples));
      assert(samples[0] == 1305 && samples[1] == 1005 && samples[2] == 1205);
      assert(command_count == 1 + repeat * 3);
      assert(commands[0] == (3 << 11));
      assert(commands[repeat] == 0);  // last repeat advances selector to next
      assert(commands[repeat * 2] == (2 << 11));
      SensorRoute array2[] = {{2, 2, 5}, {2, 4, 5}};
      assert(second.readBatch(array2, 2, repeat, engine, samples));
      assert(samples[0] == 2105 && samples[1] == 2305);
    }
  }
  first.selectAddress(6, 0);
  SensorRoute seventh[] = {{1, 4, 6}};
  uint16_t sample;
  assert(first.readBatch(seventh, 1, 1, SpiEngine::BLOCKING, &sample) && sample == 1306);
  assert(!validSensorRoute({1, 1, 6}) && !validSensorRoute({2, 4, 7}));
  SensorRoute mixed[] = {{1, 1, 5}, {1, 2, 4}};
  assert(!first.readBatch(mixed, 2, 1, SpiEngine::BLOCKING, &sample));
  command_count = 0;
  assert(first.sampleVmid(5, SpiEngine::BLOCKING));
  assert(command_count == 5);
  assert(latch[1] && latch[2] && latch[3]);

  corrupt = true;
  assert(!first.transfer(0, SpiEngine::BLOCKING, sample));
  assert(first.dataErrors() == 1);
  corrupt = false;
  complete = false;
  assert(!second.transfer(0, SpiEngine::DMA, sample));
  assert(second.transferErrors() == 1 && pending_cs == 0);
  // Never reuse the bus/DMA buffers after an incomplete transfer.
  assert(!second.transfer(0, SpiEngine::BLOCKING, sample));
  assert(second.transferErrors() == 1);
  puts("ADC124 production driver: GPIO polarity, one-frame pipeline, repeats, sparse routes and failures passed");
}
