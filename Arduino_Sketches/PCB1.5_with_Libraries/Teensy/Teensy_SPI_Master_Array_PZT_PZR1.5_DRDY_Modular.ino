#include <Arduino.h>
#include <SPI.h>

#include "libraries/SharedProtocol.h"
#include "libraries/SerialLineParser.h"
#include "libraries/SpiMasterLink.h"
#include "libraries/PztController.h"
#include "libraries/PzrController.h"

enum DeviceMode { MODE_PZT, MODE_PZR };

static DeviceMode current_mode = MODE_PZT;
static SerialLineParser g_parser;
static SpiMasterLink g_spi_link;
static pzt_controller::Runtime g_pzt;
static pzr_controller::Runtime g_pzr;

static bool suppressAck() {
  return current_mode == MODE_PZR && g_pzr.cfg.ascii_output && g_pzr.cfg.running;
}

static void printMcu() {
  Serial.println(F("# Array_PZT_PZR1"));
}

static void printHelp() {
  Serial.println(F("# Commands (* terminated):"));
  Serial.println(F("#   mode PZT|PZR"));
  Serial.println(F("#   mcu"));
  Serial.println(F("#   status"));
  Serial.println(F("#   channels 0,1,2,..."));
  Serial.println(F("#   repeat <n>"));
  Serial.println(F("#   buffer <n>"));
  Serial.println(F("#   run [ms]"));
  Serial.println(F("#   stop"));
  Serial.println(F("# PZT-only: ref, osr, gain, ground"));
  Serial.println(F("# PZR-only: rb, rk, cf, rxmax, ascii"));
}

static bool handleMode(const String &args) {
  String a = args;
  a.trim();
  a.toUpperCase();

  if (a == "PZT") {
    if (current_mode != MODE_PZT) {
      pzr_controller::handleStop(g_pzr);
      current_mode = MODE_PZT;
      Serial.println(F("# Switched to PZT mode"));
    }
    return true;
  }

  if (a == "PZR") {
    if (current_mode != MODE_PZR) {
      pzt_controller::requestStop(g_pzt);
      current_mode = MODE_PZR;
      Serial.println(F("# Switched to PZR mode"));
    }
    return true;
  }

  return false;
}

static void handleLine(const String &line) {
  String cmd;
  String args;
  splitCommand(line, cmd, args);

  bool ok = true;

  if (cmd == "mode") {
    ok = handleMode(args);
    shared_proto::writeHostAck(ok, args, suppressAck());
    return;
  }

  if (cmd == "mcu") {
    printMcu();
    shared_proto::writeHostAck(true, args, suppressAck());
    return;
  }

  if (cmd == "help") {
    printHelp();
    shared_proto::writeHostAck(true, args, suppressAck());
    return;
  }

  if (cmd == "status") {
    Serial.print(F("# Current mode: "));
    Serial.println(current_mode == MODE_PZT ? F("PZT") : F("PZR"));
    if (current_mode == MODE_PZT) {
      pzt_controller::printStatus(g_pzt);
    } else {
      pzr_controller::printStatus(g_pzr);
    }
    shared_proto::writeHostAck(true, args, suppressAck());
    return;
  }

  if (cmd == "stop") {
    if (current_mode == MODE_PZT) {
      pzt_controller::requestStop(g_pzt);
    } else {
      pzr_controller::handleStop(g_pzr);
    }
    shared_proto::writeHostAck(true, args, suppressAck());
    return;
  }

  if (current_mode == MODE_PZT) {
    if (cmd == "channels") {
      ok = pzt_controller::handleChannels(g_pzt, args);
    } else if (cmd == "repeat") {
      ok = pzt_controller::handleRepeat(g_pzt, args);
    } else if (cmd == "buffer") {
      ok = pzt_controller::handleBuffer(g_pzt, args);
    } else if (cmd == "ref") {
      ok = pzt_controller::handleRef(g_pzt, args);
    } else if (cmd == "osr") {
      ok = pzt_controller::handleOsr(g_pzt, args);
    } else if (cmd == "gain") {
      ok = pzt_controller::handleGain(g_pzt, args);
    } else if (cmd == "ground") {
      ok = pzt_controller::handleGround(g_pzt, args);
    } else if (cmd == "run") {
      (void)pzt_controller::runBlocking(g_pzt, args, shared_proto::kCmdTerm);
      return;
    } else {
      ok = false;
    }
  } else {
    if (cmd == "channels") {
      ok = pzr_controller::handleChannels(g_pzr, args);
    } else if (cmd == "repeat") {
      ok = pzr_controller::handleRepeat(g_pzr, args);
    } else if (cmd == "buffer") {
      ok = pzr_controller::handleBuffer(g_pzr, args);
    } else if (cmd == "run") {
      ok = pzr_controller::handleRun(g_pzr, args);
    } else if (cmd == "rb") {
      ok = pzr_controller::handleRb(g_pzr, args);
    } else if (cmd == "rk") {
      ok = pzr_controller::handleRk(g_pzr, args);
    } else if (cmd == "cf") {
      ok = pzr_controller::handleCf(g_pzr, args);
    } else if (cmd == "rxmax") {
      ok = pzr_controller::handleRxMax(g_pzr, args);
    } else if (cmd == "ascii") {
      ok = pzr_controller::handleAscii(g_pzr, args);
    } else {
      ok = false;
    }
  }

  if (!ok) {
    Serial.print(F("# ERROR: unknown or invalid command '"));
    Serial.print(cmd);
    Serial.println(F("'"));
  }
  shared_proto::writeHostAck(ok, args, suppressAck());
}

void setup() {
  Serial.begin(shared_proto::kSerialBaud);
  while (!Serial) {
  }

  g_parser.begin(shared_proto::kCmdTerm, shared_proto::kMaxCmdLen);

  g_spi_link.begin(SPI, 10, 4000000UL, 10);
  pzt_controller::begin(g_pzt, g_spi_link);

  pzr_controller::Pins pins;
  pins.icp_pin = 23;
  pins.mux_a0 = 20;
  pins.mux_a1 = 19;
  pins.mux_a2 = 18;
  pins.mux_a3 = 17;
  pins.mux_en = -1;
  pzr_controller::begin(g_pzr, pins);

  printMcu();
  Serial.println(F("# Default mode: PZT"));
}

void loop() {
  while (Serial.available() > 0) {
    const char c = static_cast<char>(Serial.read());
    String line;
    if (g_parser.feed(c, line)) {
      handleLine(line);
    }
  }

  if (current_mode == MODE_PZR && g_pzr.cfg.running) {
    pzr_controller::doOneBlock(g_pzr);
    if (g_pzr.cfg.timed_run && millis() >= g_pzr.cfg.run_stop_ms) {
      pzr_controller::handleStop(g_pzr);
    }
  }

  yield();
}
