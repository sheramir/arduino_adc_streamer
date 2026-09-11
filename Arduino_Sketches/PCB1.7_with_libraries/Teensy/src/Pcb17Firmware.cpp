#include "Pcb17Firmware.h"

#include <Arduino.h>

#include "../BoardConfig.h"
#include "PzrController.h"
#include "PztController.h"
#include "PztRsController.h"
#include "SerialLineParser.h"
#include "SharedProtocol.h"

namespace pcb17_firmware {

namespace {

enum DeviceMode {
  MODE_PZT,
  MODE_PZR,
  MODE_PZT_RS,
};

static DeviceMode g_current_mode = MODE_PZT;
static SerialLineParser g_parser;

static const __FlashStringHelper *modeName() {
  if (g_current_mode == MODE_PZT_RS) {
    return F("PZT_RS");
  }
  if (g_current_mode == MODE_PZR) {
    return F("PZR");
  }
  return F("PZT");
}

static bool suppressAck() {
  return g_current_mode == MODE_PZR && pzr_controller::asciiOutput() && pzr_controller::isRunning();
}

static void hostAck(bool ok, const String &args = "") {
  shared_proto::writeHostAck(ok, args, suppressAck());
  delay(5);
}

static void printMcu() {
  Serial.println(F("# Array_PZT_PZR1.7"));
}

static bool enterPztLikeMode(DeviceMode new_mode, const __FlashStringHelper *label, bool rs_mux_enable) {
  if (g_current_mode == MODE_PZR) {
    pzr_controller::handleStop();
    pzr_controller::parkMux(15);
  }

  g_current_mode = new_mode;
  pzt_controller::setCombinedMode(new_mode == MODE_PZT_RS);
  pzr_controller::muxDisableAll();
  if (rs_mux_enable) {
    pzr_controller::muxEnable(true);
  }

  Serial.print(F("# Switched to "));
  Serial.print(label);
  Serial.println(F(" mode"));
  return true;
}

static bool handleMode(const String &args) {
  String a = args;
  a.trim();
  a.toUpperCase();

  if (a == "PZT") {
    return enterPztLikeMode(MODE_PZT, F("PZT"), false);
  }

  if (a == "PZT_RS") {
    return enterPztLikeMode(MODE_PZT_RS, F("PZT_RS"), true);
  }

  if (a == "PZR") {
    if (g_current_mode != MODE_PZR) {
      pzt_controller::requestStop();
      pzt_controller::setCombinedMode(false);
      g_current_mode = MODE_PZR;
      pzr_controller::muxDisableAll();
      pzr_controller::muxEnable(true);
      Serial.println(F("# Switched to PZR mode"));
    }
    return true;
  }

  Serial.println(F("# ERROR: mode must be PZT, PZR, or PZT_RS"));
  return false;
}

static void printHelp() {
  Serial.println(F("# Commands (* terminated):"));
  Serial.println(F("#   mode PZT|PZR|PZT_RS  (switch operating mode; default PZT)"));
  Serial.println(F("# -- Shared ----------------------------------------------------"));
  Serial.println(F("#   mcu                   (print device ID)"));
  Serial.println(F("#   status                (show current config)"));
  Serial.println(F("#   channels 0,1,2,...    (MUX channels 0-15)"));
  Serial.println(F("#   repeat <n>            (samples per channel per sweep)"));
  Serial.println(F("#   buffer <n>            (sweeps per binary block)"));
  Serial.println(F("#   run                   (stream until stop*)"));
  Serial.println(F("#   run <ms>              (time-limited run)"));
  Serial.println(F("#   stop"));
  Serial.println(F("# -- PZT / PZT_RS modes ---------------------------------------"));
  Serial.println(F("#   ref 1.2|3.3|vdd"));
  Serial.println(F("#   osr 2|4|8"));
  Serial.println(F("#   gain 1|2|3|4"));
  Serial.println(F("#   ground <ch>|true|false"));
  Serial.println(F("#   pztmuxes mux1,mux2...       (PZT_RS only; one MG24 MUX side per selected PZT sensor)"));
  Serial.println(F("#   rschannels rs1,rs2...       (PZT_RS only; one RS pair per selected PZT sensor)"));
  Serial.println(F("#   PZT_RS binary payload layout per sensor: [PZT_CH1,PZT_CH2,PZT_CH3,PZT_CH4,PZT_CH5,RS1_hold,RS2_hold]"));
  Serial.print(F("#   PZT_RS RS1_hold/RS2_hold are encoded as uint16 scaled-ohms; divide by "));
  Serial.print(pzt_rs_controller::kWireUnitsPerOhm);
  Serial.println(F(" to recover ohms"));
  Serial.println(F("# -- PZR mode only --------------------------------------------"));
  Serial.print(F("#   active 555 source: "));
  Serial.println(board_config::kTimer555Name);
  Serial.println(F("#   PZR samples are Ra=(Rx+Rk) ohms; Rk is not subtracted"));
  Serial.println(F("#   rb <ohms|k|M>         (Rb resistor, e.g. rb 470*)"));
  Serial.println(F("#   rk <ohms|k|M>         (known series resistor; kept for timeout config)"));
  Serial.println(F("#   cf <F|p|n|u|m>        (capacitance for timeout only, e.g. cf 220n*)"));
  Serial.println(F("#   rxmax <ohms|k|M>      (max expected Rx before Rk, for timeouts)"));
  Serial.println(F("#   ascii [1|0|on|off]    (toggle ASCII/binary output; stops streaming)"));
}

static void printStatus() {
  Serial.print(F("# Current mode: "));
  Serial.println(modeName());

  if (g_current_mode == MODE_PZR) {
    pzr_controller::printStatus();
    return;
  }

  pzt_controller::printStatus();
  if (g_current_mode == MODE_PZT_RS) {
    Serial.println(F("# combined stream: enabled (RS hold-last-value between updates)"));
  }
}

static bool handlePztLikeCommand(const String &cmd, const String &args) {
  if (cmd == "channels") {
    return pzt_controller::handleChannels(args);
  }
  if (cmd == "pztmuxes") {
    if (g_current_mode == MODE_PZT_RS) {
      return pzt_controller::handlePztMuxes(args);
    }
    Serial.println(F("# ERROR: pztmuxes is only available in PZT_RS mode."));
    return false;
  }
  if (cmd == "rschannels") {
    if (g_current_mode == MODE_PZT_RS) {
      return pzt_controller::handleRsChannels(args);
    }
    Serial.println(F("# ERROR: rschannels is only available in PZT_RS mode."));
    return false;
  }
  if (cmd == "repeat") {
    return pzt_controller::handleRepeat(args);
  }
  if (cmd == "buffer") {
    return pzt_controller::handleBuffer(args);
  }
  if (cmd == "ref") {
    return pzt_controller::handleRef(args);
  }
  if (cmd == "osr") {
    return pzt_controller::handleOsr(args);
  }
  if (cmd == "gain") {
    return pzt_controller::handleGain(args);
  }
  if (cmd == "ground") {
    return pzt_controller::handleGround(args);
  }
  if (cmd == "run") {
    pzt_controller::handleRun(args);
    return true;
  }
  if ((cmd == "rb" || cmd == "rk" || cmd == "cf" || cmd == "rxmax") && g_current_mode == MODE_PZT_RS) {
    if (cmd == "rb") {
      return pzr_controller::handleRb(args);
    }
    if (cmd == "rk") {
      return pzr_controller::handleRk(args);
    }
    if (cmd == "cf") {
      return pzr_controller::handleCf(args);
    }
    return pzr_controller::handleRxMax(args);
  }
  if (cmd == "rb" || cmd == "rk" || cmd == "cf" || cmd == "rxmax") {
    Serial.println(F("# ERROR: this command is only available in PZR or PZT_RS mode."));
    return false;
  }
  if (cmd == "ascii") {
    Serial.println(F("# ERROR: ascii is only available in PZR mode."));
    return false;
  }

  Serial.print(F("# ERROR: unknown command '"));
  Serial.print(cmd);
  Serial.println(F("'. Type 'help'."));
  return false;
}

static bool handlePzrCommand(const String &cmd, const String &args) {
  if (cmd == "channels") {
    return pzr_controller::handleChannels(args);
  }
  if (cmd == "repeat") {
    return pzr_controller::handleRepeat(args);
  }
  if (cmd == "buffer") {
    return pzr_controller::handleBuffer(args);
  }
  if (cmd == "run") {
    return pzr_controller::handleRun(args);
  }
  if (cmd == "rb") {
    return pzr_controller::handleRb(args);
  }
  if (cmd == "rk") {
    return pzr_controller::handleRk(args);
  }
  if (cmd == "cf") {
    return pzr_controller::handleCf(args);
  }
  if (cmd == "rxmax") {
    return pzr_controller::handleRxMax(args);
  }
  if (cmd == "ascii") {
    return pzr_controller::handleAscii(args);
  }
  if (cmd == "ref" || cmd == "osr" || cmd == "gain" || cmd == "ground") {
    Serial.println(F("# ERROR: this command is only available in PZT or PZT_RS mode."));
    return false;
  }

  Serial.print(F("# ERROR: unknown command '"));
  Serial.print(cmd);
  Serial.println(F("'. Type 'help'."));
  return false;
}

static void handleLine(const String &raw_line) {
  String line = raw_line;
  line.trim();
  if (!line.length()) {
    return;
  }

  String cmd;
  String args;
  splitCommand(line, cmd, args);

  if (cmd == "mode") {
    const bool ok = handleMode(args);
    hostAck(ok, args);
    return;
  }

  if (cmd == "mcu") {
    printMcu();
    hostAck(true, args);
    return;
  }

  if (cmd == "help") {
    printHelp();
    hostAck(true, args);
    return;
  }

  if (cmd == "status") {
    printStatus();
    hostAck(true, args);
    return;
  }

  if (cmd == "stop") {
    if (g_current_mode == MODE_PZR) {
      pzr_controller::handleStop();
    } else {
      pzt_controller::requestStop();
    }
    hostAck(true, args);
    return;
  }

  if (g_current_mode == MODE_PZR) {
    const bool ok = handlePzrCommand(cmd, args);
    hostAck(ok, args);
    return;
  }

  const bool ok = handlePztLikeCommand(cmd, args);
  if (cmd != "run") {
    hostAck(ok, args);
  }
}

}  // namespace

void setupFirmware() {
  Serial.begin(shared_proto::kSerialBaud);
  while (!Serial) {
  }

  g_parser.begin(shared_proto::kCmdTerm, shared_proto::kMaxCmdLen);
  g_current_mode = MODE_PZT;

  pzt_controller::begin();
  pzr_controller::begin();
  pzt_controller::setCombinedMode(false);

  printMcu();
  Serial.println(F("# Default mode: PZT"));
  Serial.println(F("# MUX enables: PZR=pin7, RS=pin8 (active HIGH)"));
  Serial.print(F("# Active 555 source for mode PZR: "));
  Serial.println(board_config::kTimer555Name);
  Serial.print(F("# Active 555 Cf(F): "));
  Serial.println(board_config::kTimer555DefaultCfF, 12);
  Serial.println(F("# PZR output: Ra=(Rx+Rk) ohms; low-cycle source is selected in firmware and both measured/modeled values are logged"));
}

void loopFirmware() {
  String line;
  while (Serial.available() > 0) {
    const char c = static_cast<char>(Serial.read());
    if (g_parser.feed(c, line)) {
      handleLine(line);
    }
  }

  if (g_current_mode == MODE_PZR) {
    if (pzr_controller::timedRunExpired()) {
      return;
    }
    if (pzr_controller::isRunning()) {
      pzr_controller::doOneBlock();
    }
  }

  yield();
}

}  // namespace pcb17_firmware
