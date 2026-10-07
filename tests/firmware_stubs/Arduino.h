#pragma once
#include <algorithm>
#include <cctype>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>
#include <cassert>
#include <sstream>
#include <type_traits>
using std::min;
#define DMAMEM
#define HIGH 1
#define LOW 0
#define OUTPUT 1
struct __FlashStringHelper {};
#define F(value) reinterpret_cast<const __FlashStringHelper *>(value)

// Only the Arduino interfaces needed to execute the real 7953 controllers.
class String {
 public:
  String(const char *s = "") : value(s) {}
  String(std::string s) : value(std::move(s)) {}
  size_t length() const { return value.size(); }
  void reserve(size_t n) { value.reserve(n); }
  char charAt(size_t n) const { return value[n]; }
  int indexOf(char c, int start = 0) const {
    auto pos = value.find(c, start); return pos == std::string::npos ? -1 : static_cast<int>(pos);
  }
  String substring(size_t start, size_t end = std::string::npos) const {
    return value.substr(start, end == std::string::npos ? end : end - start);
  }
  void trim() {
    auto first = value.find_first_not_of(" \t\r\n");
    value = first == std::string::npos ? "" : value.substr(first, value.find_last_not_of(" \t\r\n") - first + 1);
  }
  void toLowerCase() { for (char &c : value) c = static_cast<char>(std::tolower(c)); }
  long toInt() const { return std::strtol(value.c_str(), nullptr, 10); }
  bool endsWith(const char *s) const {
    size_t n = std::strlen(s); return value.size() >= n && value.compare(value.size() - n, n, s) == 0;
  }
  void remove(size_t start) { value.erase(start); }
  void toCharArray(char *out, size_t n) const {
    if (n) { std::strncpy(out, value.c_str(), n); out[n - 1] = 0; }
  }
  String &operator+=(char c) { value += c; return *this; }
  bool operator==(const char *s) const { return value == s; }
  std::string value;
};

extern uint32_t fake_us;
struct FakeSerial {
  std::vector<uint8_t> bytes;
  std::string text;
  size_t write_limit = static_cast<size_t>(-1);
  int write_capacity = 2048;
  uint32_t write_delay_us = 0;
  unsigned live_write_calls = 0;
  bool connected = true;
  void begin(uint32_t) {}
  int available() { return 0; }
  int read() { return -1; }
  void flush() {}
  int availableForWrite() { return write_capacity; }
  void print(const __FlashStringHelper *s) { text += reinterpret_cast<const char *>(s); }
  void print(const String &value) { text += value.value; }
  template <typename T> void print(T value) {
    std::ostringstream out;
    if constexpr (std::is_same_v<T, uint8_t> || std::is_same_v<T, int8_t>) out << int(value);
    else out << value;
    text += out.str();
  }
  template <typename T> void println(T value) { print(value); println(); }
  void println() { text += '\n'; }
  size_t write(const uint8_t *p, size_t n) {
    fake_us += write_delay_us;
    n = min(n, write_limit); bytes.insert(bytes.end(), p, p + n); return n;
  }
};
extern FakeSerial Serial;
extern uint32_t fake_us;
inline uint32_t F_CPU_ACTUAL = 600000000;
inline uint32_t fake_cycle_offset = 0;
inline uint32_t fake_cycles() { return fake_us * (F_CPU_ACTUAL / 1000000) + fake_cycle_offset++; }
#define ARM_DWT_CYCCNT fake_cycles()
extern int pin_values[64];
inline unsigned fake_micros_reads = 0, fake_yield_calls = 0;
// Model atomic GPIO set/clear writes immediately, just like the Teensy ports.
struct FakeGpioRegister {
  uint8_t pin;
  int value;
  void operator=(uint32_t mask) { if (mask) pin_values[pin] = value; }
};
inline FakeGpioRegister fake_gpio_set[64], fake_gpio_clear[64];
inline unsigned fake_gpio_lookups = 0;
inline FakeGpioRegister *portSetRegister(uint8_t pin) {
  ++fake_gpio_lookups;
  fake_gpio_set[pin].pin = pin; fake_gpio_set[pin].value = HIGH;
  return &fake_gpio_set[pin];
}
inline FakeGpioRegister *portClearRegister(uint8_t pin) {
  ++fake_gpio_lookups;
  fake_gpio_clear[pin].pin = pin; fake_gpio_clear[pin].value = LOW;
  return &fake_gpio_clear[pin];
}
inline uint32_t digitalPinToBitMask(uint8_t) { return 1u; }
inline uint32_t micros() { ++fake_micros_reads; return ++fake_us; }
inline uint32_t millis() { return fake_us / 1000; }
inline void yield() { ++fake_yield_calls; ++fake_us; }
inline bool isDigit(char c) { return std::isdigit(static_cast<unsigned char>(c)); }
inline void pinMode(uint8_t, int) {}
inline void digitalWriteFast(uint8_t pin, int value) { pin_values[pin] = value; }
inline void delayNanoseconds(uint32_t) {}
