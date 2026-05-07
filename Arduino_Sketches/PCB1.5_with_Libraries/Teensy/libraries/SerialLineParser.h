#pragma once

#include <Arduino.h>

struct SerialLineParser {
  String line;
  char terminator;
  uint16_t max_len;

  void begin(char term, uint16_t max_line_len);
  bool feed(char c, String &out_line);
  void clear();
};

void splitCommand(const String &line, String &out_cmd, String &out_args);
