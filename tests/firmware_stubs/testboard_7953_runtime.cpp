#include "PztController.h"
#ifdef NDEBUG
#error Firmware runtime checks require assertions to be enabled
#endif
#include <array>
#include <iostream>

FakeSerial Serial;
uint32_t fake_us = 0;
int pin_values[64];
IMXRT_LPSPI_t IMXRT_LPSPI4_S, IMXRT_LPSPI3_S;
SPIClass SPI(&IMXRT_LPSPI4_S), SPI1(&IMXRT_LPSPI3_S);
static constexpr int pins[] = {9, 24, 32, 33};

struct Device {
  int pending[2] = {15, 15};
  uint16_t mask = 0;
  bool program = false, automatic = false;
  int auto_channel = 15, warmup = 0;
};
Device devices[4];
int last_selected[2] = {-1, -1};

// Tagged digital ADC model. It checks CS exclusion and the two-frame manual
// command delay; Auto-1 models tagged startup/resume and ascending sparse masks.
// It deliberately cannot validate electrical or analog timing.
uint16_t emulate_conversion(IMXRT_LPSPI_t *bus, uint16_t command) {
  int selected = -1;
  int first = bus == &IMXRT_LPSPI4_S ? 0 : 2;
  for (int adc = first; adc < first + 2; ++adc) {
    if (pin_values[pins[adc]] == LOW) { assert(selected < 0); selected = adc; }
  }
  assert(selected >= 0);
  int &outgoing = last_selected[first / 2];
  if (outgoing >= 0 && outgoing != selected) {
    const Device &previous = devices[outgoing];
    if (previous.automatic) assert(previous.auto_channel == 15);
    else assert(previous.pending[0] == 15 && previous.pending[1] == 15);
  }
  outgoing = selected;
  Device &d = devices[selected];
  int response = d.pending[0];
  if (d.automatic && !d.program && (command >> 12) == 0) {
    if (d.warmup) --d.warmup;
    else {
      response = d.auto_channel;
      do { d.auto_channel = (d.auto_channel + 1) % 16; } while (!(d.mask & (1u << d.auto_channel)));
    }
  }
  if (d.program) { d.mask = command; d.program = false; }
  else if ((command >> 12) == 8) d.program = true;
  else if ((command >> 12) == 2) {
    d.automatic = true; d.auto_channel = 0;
    while (!(d.mask & (1u << d.auto_channel))) ++d.auto_channel;
    d.warmup = 1;
  } else if ((command >> 12) == 1) {
    d.automatic = false;
    d.pending[0] = d.pending[1]; d.pending[1] = (command >> 7) & 15;
  }
  fake_us += 2;
  return static_cast<uint16_t>((response << 12) | (1000 + selected * 100 + response));
}

uint16_t le16(size_t offset) { return Serial.bytes[offset] | (Serial.bytes[offset + 1] << 8); }

std::vector<std::pair<int, int>> canonical(const std::vector<std::pair<int, int>> &routes, const std::string &order) {
  std::array<std::vector<std::pair<int, int>>, 4> lanes;
  for (auto route : routes) lanes[route.first].push_back(route);
  std::vector<std::pair<int, int>> out;
  if (order == "adc") { for (auto lane : lanes) out.insert(out.end(), lane.begin(), lane.end()); }
  else {
    for (int start = 0; start < 4; start += order == "array" ? 2 : 4)
      for (size_t depth = 0; depth < 16; ++depth)
        for (int adc = start; adc < start + (order == "array" ? 2 : 4); ++adc)
          if (depth < lanes[adc].size()) out.push_back(lanes[adc][depth]);
  }
  return out;
}

int main() {
  std::fill(std::begin(pin_values), std::end(pin_values), HIGH);
  SpiController bus1(SPI, 12, 11, 13), bus2(SPI1, 39, 26, 27);
  Ads7953Adc a1(bus1, 9), a2(bus1, 24), a3(bus2, 32), a4(bus2, 33);
  Ads7953Adc *adcs[] = {&a1, &a2, &a3, &a4};
  UsbSerialController usb;
  PztController pzt(adcs, 4, usb);
  bus1.begin(); bus2.begin(); pzt.begin();
  // Startup must not derive a new command from asynchronous TCR readback.
  IMXRT_LPSPI4_S.TCR.unstable_read = true;
  assert(bus1.beginLpspiSession());
  IMXRT_LPSPI4_S.TCR.unstable_read = false;
  assert(IMXRT_LPSPI4_S.TCR.unstable_reads == 0);
  // A receive word alone is insufficient to release CS before transfer
  // completion. Session ownership outlives a word and blocks clock/DMA changes.
  assert(!bus1.setClockHz(10000000));
  assert(!bus1.startDma16(9, a1.manualCommand(15)));
  assert(bus1.startLpspi16(9, a1.manualCommand(15)));
  assert(!bus1.startLpspi16(24, a2.manualCommand(15)));
  IMXRT_LPSPI4_S.SR.value &= ~LPSPI_SR_TCF;
  assert(!bus1.lpspiComplete() && pin_values[9] == LOW);
  IMXRT_LPSPI4_S.SR.value |= LPSPI_SR_MBF;
  assert(!bus1.lpspiComplete() && pin_values[9] == LOW);
  IMXRT_LPSPI4_S.SR.value &= ~LPSPI_SR_MBF;
  IMXRT_LPSPI4_S.SR.value |= LPSPI_SR_TCF;
  uint16_t response = 0;
  assert(bus1.finishLpspi16(response) && pin_values[9] == HIGH);
  assert(SPI.begins == SPI.ends + 1);
  bus1.endLpspiSession();
  assert(SPI.begins == SPI.ends && IMXRT_LPSPI4_S.TCR == 7);
  assert(bus1.beginLpspiSession());
  assert(bus1.startLpspi16(9, a1.manualCommand(15)));
  bus1.endLpspiSession();
  assert(SPI.begins == SPI.ends && pin_values[9] == HIGH);
  IMXRT_LPSPI4_S.TCR.unstable_read = true;
  IMXRT_LPSPI3_S.TCR.unstable_read = true;
  auto command = [&](const char *name, const std::string &arg) { assert(pzt.handleCommand(String(name), String(arg))); };
  unsigned cases = 0;
  std::vector<std::vector<std::pair<int, int>>> topologies = {
    {{0, 5}, {0, 0}, {0, 2}}, {{2, 2}, {2, 0}},
    {{1, 3}, {0, 0}, {1, 0}, {0, 5}}, {{3, 4}, {2, 0}, {3, 0}},
    {{0, 2}, {2, 2}, {0, 0}, {2, 0}},
    {{3, 4}, {1, 3}, {0, 2}, {2, 1}, {1, 0}, {3, 0}, {0, 0}, {2, 0}},
    {{0, 2}, {1, 0}, {1, 3}, {1, 5}, {2, 0}, {3, 4}},
    // Exact route selection from the failed on-board LPSPI startup.
    {{0, 0}, {0, 4}, {0, 9}, {1, 0}, {1, 3}, {1, 7}, {1, 11}, {1, 14},
     {2, 1}, {2, 5}, {3, 2}, {3, 6}, {3, 10}, {3, 12}, {3, 14}}
  };
  // Full 25-sensor arrays and the combined 50-sensor scan exercise command
  // capacity at repeat 3 with optional Vmid and mandatory parking enabled.
  std::vector<std::pair<int, int>> array1, array2;
  for (int adc = 0; adc < 4; ++adc)
    for (int channel = 0; channel < (adc % 2 ? 15 : 10); ++channel)
      (adc < 2 ? array1 : array2).push_back({adc, channel});
  topologies.push_back(array1);
  topologies.push_back(array2);
  auto both_arrays = array1;
  both_arrays.insert(both_arrays.end(), array2.begin(), array2.end());
  topologies.push_back(both_arrays);
  for (auto engine : {"blocking", "dma", "lpspi"})
    for (auto sequence : {"manual", "auto1"})
      for (auto order : {"adc", "array", "interleaved"})
        for (int repeat = 1; repeat <= 3; ++repeat)
          for (bool vmid : {false, true})
            for (auto routes : topologies) {
              pzt.stop();
              command("array", "both");
              std::string text;
              for (auto route : routes) text += (text.empty() ? "" : ",") + std::to_string(route.first + 1) + ":" + std::to_string(route.second);
              command("adcchannels", text); command("scanorder", order);
              command("spiengine", engine); command("adcseq", sequence);
              command("channelrepeat", std::to_string(repeat)); command("vmid", vmid ? "true" : "false");
              command("ref", cases % 2 ? "2.5" : "5");
              command("run", "");
              auto expected = canonical(routes, order);
              for (int sweep = 0; sweep < 4; ++sweep) {
                Serial.bytes.clear();
                unsigned before = SPI.begins + SPI1.begins;
                pzt.service(); assert(pzt.isRunning());
                assert(Serial.bytes.size() == 14 + expected.size() * 2);
                assert(Serial.bytes[0] == 0xaa && Serial.bytes[1] == 0x55 && le16(2) == expected.size());
                for (size_t index = 0; index < expected.size(); ++index)
                  assert(le16(4 + 2 * index) == 1000 + expected[index].first * 100 + expected[index].second);
                if (std::string(engine) == "lpspi") {
                  bool bus1_active = false, bus2_active = false;
                  for (auto route : routes) (route.first < 2 ? bus1_active : bus2_active) = true;
                  assert(SPI.begins + SPI1.begins - before == unsigned(bus1_active + bus2_active));
                }
                assert(SPI.begins == SPI.ends && SPI1.begins == SPI1.ends);
                for (auto pin : pins) assert(pin_values[pin] == HIGH);
              }
              pzt.stop();
              for (auto route : routes) {
                assert(!devices[route.first].automatic);
                assert(devices[route.first].pending[0] == 15 && devices[route.first].pending[1] == 15);
              }
              ++cases;
            }
  // Runtime clock changes and single-array selection rebuild caches at run start.
  command("array", "1"); command("adcchannels", "2:4,1:1"); command("spiclock", "10000000");
  command("spiengine", "lpspi"); command("adcseq", "manual");
  command("run", "");
  unsigned second_bus_before = SPI1.begins;
  Serial.bytes.clear(); pzt.service(); assert(SPI1.begins == second_bus_before); assert(le16(2) == 2);
  // A stuck peripheral must time out, stop, release CS and bus ownership, then
  // permit a new run in another engine without stale templates or RX state.
  IMXRT_LPSPI4_S.stall = true;
  pzt.service(); assert(!pzt.isRunning());
  assert(SPI.begins == SPI.ends && SPI1.begins == SPI1.ends);
  for (auto pin : pins) assert(pin_values[pin] == HIGH);
  IMXRT_LPSPI4_S.stall = false;
  command("spiengine", "dma"); command("run", ""); Serial.bytes.clear(); pzt.service();
  assert(pzt.isRunning() && le16(2) == 2); pzt.stop();
  command("spiengine", "lpspi"); command("run", "1");
  fake_us += 2000; pzt.service(); assert(!pzt.isRunning());
  assert(IMXRT_LPSPI4_S.TCR.unstable_reads == 0);
  assert(IMXRT_LPSPI3_S.TCR.unstable_reads == 0);
  // A partial USB enqueue must stop sampling, count the error, release buses,
  // and permit a subsequent run when the host accepts data again.
  command("run", "");
  Serial.write_limit = 5;
  const auto errors_before = usb.writeErrors();
  pzt.service(); assert(!pzt.isRunning());
  assert(usb.writeErrors() == errors_before + 1);
  assert(SPI.begins == SPI.ends && SPI1.begins == SPI1.ends);
  for (auto pin : pins) assert(pin_values[pin] == HIGH);
  Serial.write_limit = static_cast<size_t>(-1);
  command("run", ""); Serial.bytes.clear(); pzt.service();
  assert(pzt.isRunning() && le16(2) == 2); pzt.stop();
  std::cout << cases << " digital acquisition cases passed; session/recovery checks passed\n";
}
