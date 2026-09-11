#pragma once

#include <Arduino.h>

namespace pzt_rs_controller {

static const uint8_t kChannelsPerSensor = 5;
static const uint8_t kMaxSensorSlots = 6;
static const uint8_t kRsValuesPerSensor = 2;
static const uint8_t kOutputsPerSensor = kChannelsPerSensor + kRsValuesPerSensor;
static const uint16_t kWireUnitsPerOhm = 100;
static const uint16_t PZT_RS_WIRE_UNITS_PER_OHM = kWireUnitsPerOhm;
static const uint32_t kMaxOutputSamples = 32000UL;
static const uint32_t kMaxBlockBytes = 4UL + kMaxOutputSamples * 2UL + 10UL;

void resetRouting();
void setSensorCount(uint8_t count);
uint8_t sensorCount();
uint8_t sensorMuxCount();
uint8_t rsChannelCount();
uint8_t rsRefreshChannelCount();
uint8_t rsRefreshChannel(uint8_t index);
bool routingReady();

bool handlePztMuxes(const String &args);
bool handleRsChannels(const String &args);

uint32_t outputSamplesPerBlock(uint8_t repeat_count, uint8_t sweeps_per_block);

void resetState();
void stopRefresh();
void serviceRefresh(bool allow_channel_switch = true);
void snapshotHeldValues(uint16_t *dst, uint8_t count = 16);

bool buildCombinedBlock(
    const uint8_t *src,
    uint32_t src_len,
    uint8_t *dst,
    uint32_t &dst_len,
    const uint16_t *held_ra_q_snapshot,
    const uint8_t *logical_channels,
    uint8_t logical_channel_count,
    const uint8_t *physical_channels,
    uint8_t physical_channel_count,
    uint8_t repeat_count);

void printStatusDetails();
void printRefreshDiagnostics(uint8_t ch, const __FlashStringHelper *prefix = nullptr);
void printStreamDiagnostics();

void noteIsrFire();
uint8_t activeChannel();
void noteRise(uint8_t ch);
void noteFall(uint8_t ch);
void notePairReady(uint8_t ch, uint32_t high_cycles, uint32_t low_cycles);

}  // namespace pzt_rs_controller
