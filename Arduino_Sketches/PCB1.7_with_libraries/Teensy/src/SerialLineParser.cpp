#include "SerialLineParser.h"

void SerialLineParser::begin(char term, uint16_t max_line_len) {
  terminator = term;
  max_len = max_line_len;
  line = "";
}

bool SerialLineParser::feed(char c, String &out_line) {
  if (c == '\r' || c == '\n') {
    return false;
  }

  if (c == terminator) {
    out_line = line;
    line = "";
    out_line.trim();
    return out_line.length() > 0;
  }

  line += c;
  if (line.length() > max_len) {
    line = "";
  }
  return false;
}

void SerialLineParser::clear() {
  line = "";
}

void splitCommand(const String &line, String &out_cmd, String &out_args) {
  const int sp = line.indexOf(' ');
  if (sp < 0) {
    out_cmd = line;
    out_args = "";
  } else {
    out_cmd = line.substring(0, sp);
    out_args = line.substring(sp + 1);
  }
  out_cmd.trim();
  out_args.trim();
  out_cmd.toLowerCase();
}
