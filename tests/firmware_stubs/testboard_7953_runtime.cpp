#include "PztController.h"
#ifdef NDEBUG
#error Firmware runtime checks require assertions to be enabled
#endif
#include <array>
#include <iostream>

FakeSerial Serial;
// Model the new atomic, nonblocking core contract, including disconnects.
// write_delay_us intentionally affects only the old blocking Serial.write.
extern "C" int usb_serial_try_write_frame(const void *buffer, uint32_t size) {
  ++Serial.live_write_calls;
  if (!buffer || !size || size > 2048 || Serial.write_limit < size) return -1;
  if (!Serial.connected || Serial.write_capacity < static_cast<int>(size)) return 0;
  const auto *data = static_cast<const uint8_t *>(buffer);
  Serial.bytes.insert(Serial.bytes.end(), data, data + size);
  return size;
}
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
uint32_t le32(size_t offset) { return le16(offset) | (uint32_t(le16(offset + 2)) << 16); }

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
#if !TESTBOARD_PROFILE
  assert(!pzt.handleCommand("profile", "on"));
  command("profile", "off");
#endif
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
#if TESTBOARD_PROFILE
              command("profile", cases % 2 ? "on" : "off");
#endif
              command("run", "");
              assert(!pzt.handleCommand("profile", "off"));
              auto expected = canonical(routes, order);
              for (int sweep = 0; sweep < 4; ++sweep) {
                Serial.bytes.clear();
                unsigned before = SPI.begins + SPI1.begins;
                const unsigned gpio_before = fake_gpio_lookups;
                const unsigned micros_before = fake_micros_reads;
                pzt.service(); assert(pzt.isRunning());
                assert(Serial.bytes.size() == 14 + expected.size() * 2);
                assert(Serial.bytes[0] == 0xaa && Serial.bytes[1] == 0x55 && le16(2) == expected.size());
                for (size_t index = 0; index < expected.size(); ++index)
                  assert(le16(4 + 2 * index) == 1000 + expected[index].first * 100 + expected[index].second);
                if (std::string(engine) == "lpspi") {
                  assert(fake_gpio_lookups == gpio_before);
#if !TESTBOARD_PROFILE
                  assert(fake_micros_reads - micros_before == 2); // wire timestamps only
#endif
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
  const unsigned yield_before = fake_yield_calls;
  pzt.service(); assert(!pzt.isRunning());
  assert(fake_yield_calls > yield_before);
  assert(SPI.begins == SPI.ends && SPI1.begins == SPI1.ends);
  for (auto pin : pins) assert(pin_values[pin] == HIGH);
  IMXRT_LPSPI4_S.stall = false;
  command("spiengine", "dma"); command("run", ""); Serial.bytes.clear(); pzt.service();
  assert(pzt.isRunning() && le16(2) == 2); pzt.stop();
  command("spiengine", "lpspi"); command("run", "1");
  fake_us += 2000; pzt.service(); assert(!pzt.isRunning());
  // Timeout with the second bus stuck, while the first has already completed.
  // Force the cycle deadline to cross UINT32_MAX, then verify both CS cleanup
  // and a healthy restart. Probe overhead cannot manufacture a huge timeout.
  command("array", "both"); command("adcchannels", "1:1,3:2");
  command("run", "");
  fake_cycle_offset = UINT32_MAX - fake_us * (F_CPU_ACTUAL / 1000000u) - 100000u;
  IMXRT_LPSPI3_S.stall = true;
  const uint32_t cycle_before = ARM_DWT_CYCCNT;
  const unsigned stalled_before = fake_stalled_words;
  Serial.bytes.clear(); pzt.service();
  const uint32_t elapsed_ticks = ARM_DWT_CYCCNT - cycle_before;
  // Failure cleanup attempts parking too; each stuck word keeps the 1 ms bound.
  const uint32_t timeout_ticks = (fake_stalled_words - stalled_before) * (F_CPU_ACTUAL / 1000u);
  assert(timeout_ticks && elapsed_ticks >= timeout_ticks && elapsed_ticks < timeout_ticks + F_CPU_ACTUAL / 10000u);
  assert(!pzt.isRunning() && Serial.bytes.empty());
  assert(SPI.begins == SPI.ends && SPI1.begins == SPI1.ends);
  for (auto pin : pins) assert(pin_values[pin] == HIGH);
  IMXRT_LPSPI3_S.stall = false;
  fake_cycle_offset = 0;
  command("run", ""); Serial.bytes.clear(); pzt.service();
  assert(pzt.isRunning() && le16(2) == 2); pzt.stop();
  // RX may be ready before completion. Unequal delayed TCFs must still deliver
  // both tagged responses, with periodic foreground service and no CS overlap.
  command("run", "");
  IMXRT_LPSPI4_S.completion_reads = 9000;
  IMXRT_LPSPI3_S.completion_reads = 17000;
  const unsigned delayed_yields = fake_yield_calls;
  Serial.bytes.clear(); pzt.service();
  assert(pzt.isRunning() && le16(2) == 2);
  assert(le16(4) == 1001 && le16(6) == 1202);
  assert(fake_yield_calls > delayed_yields);
  for (auto pin : pins) assert(pin_values[pin] == HIGH);
  IMXRT_LPSPI4_S.completion_reads = IMXRT_LPSPI3_S.completion_reads = 0;
  pzt.stop();
  command("array", "1"); command("adcchannels", "2:4,1:1");
  assert(IMXRT_LPSPI4_S.TCR.unstable_reads == 0);
  assert(IMXRT_LPSPI3_S.TCR.unstable_reads == 0);
#if TESTBOARD_PROFILE
  command("profile", "on");
  assert(!pzt.handleCommand("profile", "invalid"));
  // Cross a cycle-counter wrap, inject one low-capacity write, and ensure
  // phase attribution/counters reset per run and are not printed while active.
  fake_us = 7158270;
  command("run", "");
  for (int i = 0; i < 5; ++i) {
    Serial.bytes.clear();
    Serial.write_capacity = i == 2 ? 0 : 2048;
    Serial.write_delay_us = i == 2 ? 3000 : 0;
    pzt.service();
    assert(pzt.isRunning());
    if (i == 2) assert(Serial.bytes.empty());
    else assert(le16(2) == 2);
  }
  Serial.text.clear(); pzt.printStatus();
  assert(Serial.text.find("profile_written=") == std::string::npos);
  pzt.stop(); Serial.text.clear(); pzt.printStatus();
  assert(Serial.text.find("# profile_written=4\n") != std::string::npos);
  assert(Serial.text.find("# profile_discarded=1\n") != std::string::npos);
  std::cout << "PROFILE_STATUS_BEGIN\n" << Serial.text << "PROFILE_STATUS_END\n";
  // Micros rollover is valid. An enclosing foreground interval spanning a whole
  // CPU counter cycle is invalid, rather than being reported as a tiny gap.
  Serial.write_capacity = 2048; Serial.write_delay_us = 0;
  fake_us = UINT32_MAX - 20;
  command("run", ""); pzt.service(); pzt.service();
  fake_us += 8000000;
  pzt.service(); pzt.stop(); Serial.text.clear(); pzt.printStatus();
  assert(Serial.text.find("# profile_invalid_foreground=1\n") != std::string::npos);
  command("profile", "off");
  command("run", ""); pzt.service(); pzt.stop(); Serial.text.clear(); pzt.printStatus();
  assert(Serial.text.find("# profile_enabled=false\n") != std::string::npos);
  assert(Serial.text.find("# profile_written=") == std::string::npos);
  command("profile", "on");
#endif
  // Complete hundreds of sweeps with USB busy or disconnected, across every
  // engine and sequencing mode. On recovery emit only a fresh sweep, with no
  // retained application backlog or stale pipeline, then reset per-run counts.
  Serial.write_capacity = 2048; Serial.write_delay_us = 120000;
  for (const char *engine : {"blocking", "dma", "lpspi"}) {
    for (const char *sequence : {"manual", "auto1"}) {
      command("spiengine", engine); command("adcseq", sequence);
      command("array", "both"); command("adcchannels", "1:1,2:4,3:2,4:7");
      command("run", ""); Serial.bytes.clear();
      const uint32_t begin_busy = fake_us;
      const uint32_t errors_before = usb.writeErrors();
      const unsigned writes_before = Serial.live_write_calls;
      for (int i = 0; i < 400; ++i) {
        Serial.connected = i % 2 == 0;
        Serial.write_capacity = i % 2 == 0 ? 0 : 2048;
        pzt.service();
        assert(pzt.isRunning() && Serial.bytes.empty());
        for (auto pin : pins) assert(pin_values[pin] == HIGH);
      }
      assert(Serial.live_write_calls == writes_before + 400);
      assert(fake_us - begin_busy < 100000); // Never the old 120 ms write wait.
      assert(usb.writeErrors() == errors_before);
      Serial.connected = true; Serial.write_capacity = 2048;
      const uint32_t recovered_at = fake_us;
      pzt.service();
      assert(pzt.isRunning() && Serial.bytes.size() == 22 && le16(2) == 4);
      assert(le16(4) == 1001 && le16(6) == 1104 && le16(8) == 1202 && le16(10) == 1307);
      assert(le32(14) >= recovered_at && le32(18) > le32(14));
      pzt.stop(); Serial.text.clear(); pzt.printStatus();
      assert(Serial.text.find("# sampling_sweeps=401\n") != std::string::npos);
      assert(Serial.text.find("# usb_frames_sent=1\n") != std::string::npos);
      assert(Serial.text.find("# usb_frames_discarded=400\n") != std::string::npos);
      assert(Serial.text.find("# sampling_period_over_1ms=0\n") != std::string::npos);
#if TESTBOARD_PROFILE
      assert(Serial.text.find("# profile_attempts=401\n") != std::string::npos);
      assert(Serial.text.find("# profile_aborted=0\n") != std::string::npos);
      assert(Serial.text.find("# profile_discarded=400\n") != std::string::npos);
      assert(Serial.text.find("# profile_period=400,") != std::string::npos);
#endif
      command("run", ""); pzt.service(); pzt.stop();
      Serial.text.clear(); pzt.printStatus();
      assert(Serial.text.find("# sampling_sweeps=1\n") != std::string::npos);
      assert(Serial.text.find("# usb_frames_discarded=0\n") != std::string::npos);
      // A timed run must finish even while every sweep is discarded.
      Serial.write_capacity = 0; command("run", "2");
      while (pzt.isRunning()) pzt.service();
      assert(Serial.text.find("# usb_write_errors=0\n") != std::string::npos);
      Serial.write_capacity = 2048;
    }
  }
  Serial.write_delay_us = 0;
  // An unexpected core error must stop sampling, count the error, release buses,
  // and permit a subsequent run when the host accepts data again.
  command("run", "");
  Serial.write_limit = 5;
  const auto errors_before = usb.writeErrors();
  Serial.bytes.clear(); pzt.service(); assert(!pzt.isRunning() && Serial.bytes.empty());
  assert(usb.writeErrors() == errors_before + 1);
#if TESTBOARD_PROFILE
  Serial.text.clear(); pzt.printStatus();
  assert(Serial.text.find("# profile_aborted=1\n") != std::string::npos);
  assert(Serial.text.find("# profile_written=0\n") != std::string::npos);
#endif
  assert(SPI.begins == SPI.ends && SPI1.begins == SPI1.ends);
  for (auto pin : pins) assert(pin_values[pin] == HIGH);
  Serial.write_limit = static_cast<size_t>(-1);
  command("run", ""); Serial.bytes.clear(); pzt.service();
  assert(pzt.isRunning() && le16(2) == 4); pzt.stop();
  std::cout << cases << " digital acquisition cases passed; session/recovery checks passed\n";
}
