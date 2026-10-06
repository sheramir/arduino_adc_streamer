#pragma once
#include <algorithm>
#include <cctype>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>
#include <cassert>
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

struct FakeSerial {
  std::vector<uint8_t> bytes;
  size_t write_limit = static_cast<size_t>(-1);
  void begin(uint32_t) {}
  int available() { return 0; }
  int read() { return -1; }
  void flush() {}
  template <typename T> void print(T) {}
  template <typename T> void println(T) {}
  void println() {}
  size_t write(const uint8_t *p, size_t n) {
    n = min(n, write_limit); bytes.insert(bytes.end(), p, p + n); return n;
  }
};
extern FakeSerial Serial;
extern uint32_t fake_us;
extern int pin_values[64];
inline uint32_t micros() { return ++fake_us; }
inline uint32_t millis() { return fake_us / 1000; }
inline void yield() { ++fake_us; }
inline bool isDigit(char c) { return std::isdigit(static_cast<unsigned char>(c)); }
inline void pinMode(uint8_t, int) {}
inline void digitalWriteFast(uint8_t pin, int value) { pin_values[pin] = value; }
inline void delayNanoseconds(uint32_t) {}
