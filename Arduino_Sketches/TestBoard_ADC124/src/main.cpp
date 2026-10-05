#include <Arduino.h>
#include <SPI.h>
#include "Adc124s101.h"
#include "ApiProtocol.h"
#include "UsbSerialController.h"

using namespace testboard_config;

namespace {
UsbSerialController usb;
SpiController spi(SPI, kMisoPin, kMosiPin, kSckPin);
Adc124s101 adc1(spi, 0), adc2(spi, 1);
Adc124s101 *adcs[] = {&adc1, &adc2};
SensorRoute routes[kMaxRoutes], plan[kMaxRoutes];
uint8_t route_count = 0, plan_count = 0;
uint8_t array_mask = 3, channel_repeat = 1;
enum class ScanOrder { MUX, CHANNEL, INTERLEAVED };
ScanOrder scan_order = ScanOrder::MUX;
SpiEngine engine = SpiEngine::BLOCKING;
uint32_t settle_us = kDefaultMuxSettleUs;
bool vmid = false, running = false;
uint32_t run_started_ms = 0, duration_ms = 0, sweep_count = 0;

bool parseUint(const String &text, uint32_t minimum, uint32_t maximum,
               uint32_t &value) {
  if (!text.length()) return false;
  uint32_t parsed = 0;
  for (unsigned int i = 0; i < text.length(); ++i) {
    char c = text.charAt(i);
    if (c < '0' || c > '9') return false;
    uint8_t digit = c - '0';
    if (parsed > maximum / 10 ||
        (parsed == maximum / 10 && digit > maximum % 10)) return false;
    parsed = parsed * 10 + digit;
  }
  if (parsed < minimum) return false;
  value = parsed;
  return true;
}

void parkAll() { for (auto adc : adcs) adc->park(settle_us); }
void stop() { running = false; parkAll(); }
bool selected(uint8_t array) { return array_mask & (1 << (array - 1)); }

uint16_t orderKey(const SensorRoute &r) {
  if (scan_order == ScanOrder::CHANNEL)
    return r.array * 32 + (r.mux - 1) * 8 + r.input;
  if (scan_order == ScanOrder::INTERLEAVED)
    return r.input * 8 + (r.mux - 1) * 2 + r.array - 1;
  return r.array * 32 + r.input * 4 + r.mux - 1;
}

void buildPlan() {
  plan_count = 0;
  for (uint8_t i = 0; i < route_count; ++i)
    if (selected(routes[i].array)) plan[plan_count++] = routes[i];
  for (uint8_t i = 1; i < plan_count; ++i) {
    SensorRoute r = plan[i];
    uint8_t j = i;
    while (j && orderKey(plan[j - 1]) > orderKey(r)) {
      plan[j] = plan[j - 1]; --j;
    }
    plan[j] = r;
  }
}

bool setRoutes(const String &args) {
  SensorRoute candidate[kMaxRoutes];
  uint8_t count = 0;
  int start = 0;
  while (start < static_cast<int>(args.length())) {
    int end = args.indexOf(',', start);
    if (end < 0) end = args.length();
    String token = args.substring(start, end);
    token.trim();
    int first = token.indexOf(':'), second = token.indexOf(':', first + 1);
    if (first < 1 || second < first + 2 || count >= kMaxRoutes) return false;
    uint32_t array, mux, input;
    if (!parseUint(token.substring(0, first), 1, 2, array) ||
        !parseUint(token.substring(first + 1, second), 1, 4, mux) ||
        !parseUint(token.substring(second + 1), 0, 7, input)) return false;
    SensorRoute r{static_cast<uint8_t>(array), static_cast<uint8_t>(mux),
                  static_cast<uint8_t>(input)};
    if (!validSensorRoute(r)) return false;
    for (uint8_t i = 0; i < count; ++i)
      if (candidate[i].array == r.array && candidate[i].mux == r.mux &&
          candidate[i].input == r.input) return false;
    candidate[count++] = r;
    start = end + 1;
    if (start == static_cast<int>(args.length())) return false;
  }
  if (!count) return false;
  memcpy(routes, candidate, sizeof(SensorRoute) * count);
  route_count = count;
  buildPlan();
  return true;
}

const char *orderName() {
  if (scan_order == ScanOrder::CHANNEL) return "channel";
  if (scan_order == ScanOrder::INTERLEAVED) return "interleaved";
  return "mux";
}
const char *engineName() {
  if (engine == SpiEngine::DMA) return "dma";
  if (engine == SpiEngine::LPSPI) return "lpspi";
  return "blocking";
}
void printRoute(const SensorRoute &r) {
  Serial.print(r.array); Serial.print(':');
  Serial.print(r.mux); Serial.print(':'); Serial.print(r.input);
}
void status() {
  Serial.println("# board=TestBoard_ADC124");
  Serial.println("# protocol_version=1");
  Serial.println("# mode=PZT");
  Serial.print("# array="); Serial.println(array_mask == 3 ? "both" : array_mask == 1 ? "1" : "2");
  Serial.print("# scanorder="); Serial.println(orderName());
  Serial.print("# spiengine="); Serial.println(engineName());
  Serial.print("# spi_clock_hz="); Serial.println(spi.clockHz());
  Serial.print("# channelrepeat="); Serial.println(channel_repeat);
  Serial.print("# mux_settle_us="); Serial.println(settle_us);
  Serial.print("# vmid_between_groups="); Serial.println(vmid ? "true" : "false");
  Serial.println("# vmid_address=7");
  Serial.println("# vmid_parking=mandatory");
  Serial.println("# vref=3.3");
  Serial.println("# vmid_volts=1.65");
  Serial.println("# active_spi_buses=1");
  Serial.println("# mux_enable_active_high=true,false");
  Serial.print("# adcchannels=");
  for (uint8_t i = 0; i < route_count; ++i) {
    if (i) Serial.print(',');
    printRoute(routes[i]);
  }
  Serial.println();
  Serial.print("# payload_routes=");
  for (uint8_t i = 0; i < plan_count; ++i) {
    if (i) Serial.print(',');
    printRoute(plan[i]);
  }
  Serial.println();
  Serial.print("# route_count="); Serial.println(plan_count);
  Serial.print("# sweep_count="); Serial.println(sweep_count);
  Serial.print("# transfer_errors="); Serial.println(adc1.transferErrors() + adc2.transferErrors());
  Serial.print("# data_errors="); Serial.println(adc1.dataErrors() + adc2.dataErrors());
}

bool command(const String &name, const String &args) {
  uint32_t value;
  if (name == "stop") { stop(); return args.length() == 0; }
  if (name == "mcu") { Serial.println("# TestBoard_ADC124"); return !args.length(); }
  if (name == "status") { status(); return !args.length(); }
  if (name == "help") {
    Serial.println("# array 1|2|both; adcchannels array:mux:input,...; scanorder mux|channel|interleaved");
    Serial.println("# spiengine blocking|dma|lpspi; spiclock 8000000..16000000; channelrepeat 1..3");
    Serial.println("# muxsettle 0..1000 (us); vmid true|false|7; ref 3.3 (fixed); mode PZT");
    Serial.println("# run [1..3600000 ms]; stop; status; mcu; help; commands end with '*'");
    return !args.length();
  }
  if (name == "mode") return args == "PZT" || args == "pzt";
  if (name == "ref") return args == "3.3";
  if (name == "adcchannels") return setRoutes(args);
  if (name == "array") {
    if (args == "1") array_mask = 1;
    else if (args == "2") array_mask = 2;
    else if (args == "both") array_mask = 3;
    else return false;
    buildPlan(); return true;
  }
  if (name == "scanorder") {
    if (args == "mux") scan_order = ScanOrder::MUX;
    else if (args == "channel" || args == "array" || args == "adc") scan_order = ScanOrder::CHANNEL;
    else if (args == "interleaved") scan_order = ScanOrder::INTERLEAVED;
    else return false;
    buildPlan(); return true;
  }
  if (name == "spiengine") {
    if (args == "blocking") engine = SpiEngine::BLOCKING;
    else if (args == "dma") engine = SpiEngine::DMA;
    else if (args == "lpspi") engine = SpiEngine::LPSPI;
    else return false;
    return true;
  }
  if (name == "spiclock") return parseUint(args, kMinSpiClockHz, kMaxSpiClockHz, value) && spi.setClockHz(value);
  if (name == "channelrepeat") {
    if (!parseUint(args, 1, 3, value)) return false;
    channel_repeat = value; return true;
  }
  if (name == "muxsettle") {
    if (!parseUint(args, 0, kMaxMuxSettleUs, value)) return false;
    settle_us = value; return true;
  }
  if (name == "vmid" || name == "ground") {
    if (args == "true" || args == "7") vmid = true;
    else if (args == "false") vmid = false;
    else return false;
    return true;
  }
  if (name == "run") {
    if (!plan_count || adc1.transferErrors() || adc2.transferErrors()) return false;
    value = 0;
    if (args.length() && !parseUint(args, 1, 3600000, value)) return false;
    parkAll();
    for (uint8_t i = 0; i < 2; ++i) if (!selected(i + 1)) adcs[i]->disable();
    duration_ms = value; run_started_ms = millis(); running = true;
    return true;
  }
  return false;
}

bool capture() {
  uint16_t samples[kMaxRoutes];
  const uint32_t started = micros();
  uint8_t previous_array = 0;
  for (uint8_t i = 0; i < plan_count;) {
    const SensorRoute &r = plan[i];
    // One shared SPI bus: every engine transfers sequentially. Park the
    // outgoing external MUX group before switching ADC ownership.
    if (previous_array && previous_array != r.array)
      adcs[previous_array - 1]->park(settle_us);
    Adc124s101 &adc = *adcs[r.array - 1];
    adc.selectAddress(r.input, settle_us);
    uint8_t end = i + 1;
    while (end < plan_count && plan[end].array == r.array && plan[end].input == r.input) ++end;
    if (!adc.readBatch(plan + i, end - i, channel_repeat, engine, samples + i)) return false;
    if (vmid && !adc.sampleVmid(settle_us, engine)) return false;
    previous_array = r.array;
    i = end;
  }
  // Park the final ADC before the next two-array sweep resumes the first.
  bool both_active = false;
  for (uint8_t i = 0; i < plan_count; ++i)
    if (plan[i].array != previous_array) both_active = true;
  if (both_active) adcs[previous_array - 1]->park(settle_us);
  const uint32_t ended = micros(), average = (ended - started) / plan_count;
  uint8_t frame[4 + kMaxRoutes * 2 + api_protocol::kTrailerBytes];
  uint32_t size = api_protocol::encodeBinaryBlock(frame, sizeof(frame), samples,
      plan_count, average > 65535 ? 65535 : average, started, ended);
  usb.writeBinaryBlock(frame, size);
  ++sweep_count;
  return true;
}
}  // namespace

void setup() {
  usb.begin(kUsbSerialBaud);
  for (uint8_t cs : kCsPins) spi.registerChipSelect(cs);
  spi.begin();
  for (auto adc : adcs) adc->begin();
  for (uint8_t array = 1; array <= 2; ++array)
    for (uint8_t mux = 1; mux <= 4; ++mux)
      for (uint8_t input = 0; input <= (mux == 4 ? 6 : 5); ++input)
        routes[route_count++] = {array, mux, input};
  buildPlan();
  Serial.println("# TestBoard_ADC124");
}

void loop() {
  String line;
  while (usb.readCommand(line)) {
    line.trim();
    if (!line.length()) continue;
    // Commands stop the stream at a complete-frame boundary before text.
    if (running) stop();
    String name, args;
    api_protocol::splitCommand(line, name, args);
    bool success = command(name, args);
    if (!(name == "run" && success)) usb.writeAck(success);
  }
  if (running) {
    if (duration_ms && static_cast<uint32_t>(millis() - run_started_ms) >= duration_ms) stop();
    else if (!capture()) stop();
  }
  yield();
}
