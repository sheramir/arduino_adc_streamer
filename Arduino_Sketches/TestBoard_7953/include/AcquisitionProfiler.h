#pragma once
#include <Arduino.h>
#include <string.h>

#ifndef TESTBOARD_PROFILE
#define TESTBOARD_PROFILE 0
#endif

#if TESTBOARD_PROFILE
// Bounded storage; no allocation or text during capture. Per-phase cycle deltas
// are modulo uint32. Foreground intervals that may span a full wrap are rejected.
class AcquisitionProfiler {
 public:
  enum Phase : uint8_t {
    Prepare, Session, Transfer, Validate, Encode, Capacity, UsbWrite,
    Acquisition, Foreground, Bookkeeping, Period, Gap, RunPrepare, PhaseCount
  };
  static constexpr uint8_t kEdges = 16;
  static constexpr uint32_t kBoundsUs[kEdges] = {
      1, 2, 4, 8, 16, 32, 64, 100, 128, 256, 512, 1000,
      2000, 4000, 16000, 64000};
  struct Stats {
    uint32_t count = 0, bins[kEdges + 1] = {}, over100 = 0, over1000 = 0;
    uint64_t total = 0, maximum = 0;
    void add(uint64_t ticks, uint32_t hz) {
      ++count;
      total += ticks;
      if (ticks > maximum) maximum = ticks;
      uint8_t bin = 0;
      while (bin < kEdges && ticks * 1000000ULL > uint64_t(kBoundsUs[bin]) * hz) ++bin;
      ++bins[bin];
      if (ticks * 1000000ULL > uint64_t(100) * hz) ++over100;
      if (ticks * 1000000ULL > uint64_t(1000) * hz) ++over1000;
    }
  };
  class Sweep {
   public:
    explicit Sweep(AcquisitionProfiler &owner) : owner_(owner) { owner_.beginSweep(); }
    ~Sweep() { owner_.endSweep(written_, discarded_); }
    void written(bool value, bool discarded = false) { written_ = value; discarded_ = discarded; }
   private:
    AcquisitionProfiler &owner_;
    bool written_ = false;
    bool discarded_ = false;
  };
  class Scope {
   public:
    Scope(AcquisitionProfiler &owner, Phase phase)
        : owner_(owner), phase_(phase), started_(owner.enabled_ ? cycles() : 0) {}
    ~Scope() {
      if (owner_.enabled_) {
        owner_.pending_[phase_] += uint32_t(cycles() - started_);
        owner_.observed_[phase_] = true;
      }
    }
   private:
    AcquisitionProfiler &owner_;
    Phase phase_;
    uint32_t started_;
  };
  bool setEnabled(const String &value) {
    if (!(value == "on") && !(value == "off")) return false;
    enabled_ = value == "on";
    return true;
  }
  bool enabled() const { return enabled_; }
  uint32_t stamp() const { return enabled_ ? cycles() : 0; }
  void runPrepared(uint32_t started) {
    if (enabled_) stats_[RunPrepare].add(uint32_t(cycles() - started), clock_hz_);
  }
  void reset() {
    for (auto &s : stats_) s = Stats{};
    attempts_ = written_ = discarded_ = invalid_foreground_ = frequency_changes_ = 0;
    have_previous_ = false;
    write_calls_ = capacity_low_ = 0;
    capacity_min_ = UINT32_MAX;
    capacity_max_ = 0;
    clock_hz_ = F_CPU_ACTUAL;
    tail_count_ = 0;
    memset(tails_, 0, sizeof(tails_));
    probe_min_ = UINT32_MAX;
    probe_max_ = 0;
    if (!enabled_) return;
    // Adjacent read calibration is not the cost of all instrumentation.
    for (uint8_t i = 0; i < 32; ++i) {
      const uint32_t a = cycles(), b = cycles();
      const uint32_t delta = b - a;
      if (delta < probe_min_) probe_min_ = delta;
      if (delta > probe_max_) probe_max_ = delta;
    }
  }
  void acquisitionBegin(uint32_t started_us) {
    if (!enabled_) return;
    acquisition_cycle_ = cycles();
    if (have_previous_) {
      const uint32_t period = started_us - previous_start_us_;
      const uint32_t gap = started_us - previous_end_us_;
      pending_period_us_ = period;
      pending_gap_us_ = gap;
      if (uint64_t(gap) * clock_hz_ >= (uint64_t(1) << 32) * 1000000ULL) {
        foreground_valid_ = false;
      } else {
        foreground_valid_ = true;
      }
    }
    current_start_us_ = started_us;
  }
  void acquisitionEnd(uint32_t ended_us) {
    if (!enabled_) return;
    pending_[Acquisition] = uint32_t(cycles() - acquisition_cycle_);
    observed_[Acquisition] = true;
    current_end_us_ = ended_us;
  }
  void noteCapacity(int available, uint32_t frame_bytes) {
    if (!enabled_) return;
    const uint32_t value = available < 0 ? 0 : uint32_t(available);
    ++write_calls_;
    if (value < capacity_min_) capacity_min_ = value;
    if (value > capacity_max_) capacity_max_ = value;
    if (value < frame_bytes) ++capacity_low_;
  }
  void printStatus(bool running) const {
    Serial.println(F("# profile_available=true"));
    Serial.print(F("# profile_enabled=")); Serial.println(enabled_ ? F("true") : F("false"));
    if (running || !enabled_) return;
    Serial.println(F("# profile_version=2"));
    printValue("clock_hz", clock_hz_);
    printValue("attempts", attempts_);
    printValue("written", written_);
    printValue("discarded", discarded_);
    printValue("aborted", attempts_ - written_ - discarded_);
    printValue("invalid_foreground", invalid_foreground_);
    printValue("frequency_changes", frequency_changes_);
    printValue("probe_cycles_min", probe_min_ == UINT32_MAX ? 0 : probe_min_);
    printValue("probe_cycles_max", probe_max_);
    printValue("write_calls", write_calls_);
    printValue("capacity_min", write_calls_ ? capacity_min_ : 0);
    printValue("capacity_max", capacity_max_);
    printValue("capacity_below_frame", capacity_low_);
    Serial.print(F("# profile_bounds_us="));
    for (uint8_t i = 0; i < kEdges; ++i) {
      if (i) Serial.print(',');
      Serial.print(kBoundsUs[i]);
    }
    Serial.println();
    static const char *names[] = {"prepare", "session", "transfer", "validate",
        "encode", "capacity", "usb_write", "acquisition", "foreground",
        "bookkeeping", "period", "gap", "run_prepare"};
    for (uint8_t p = 0; p < PhaseCount; ++p) {
      const Stats &s = stats_[p];
      Serial.print(F("# profile_")); Serial.print(names[p]); Serial.print('=');
      Serial.print(s.count); Serial.print(','); Serial.print(s.total); Serial.print(',');
      Serial.print(s.maximum); Serial.print(','); Serial.print(s.over100); Serial.print(',');
      Serial.print(s.over1000);
      for (uint8_t i = 0; i <= kEdges; ++i) { Serial.print(','); Serial.print(s.bins[i]); }
      Serial.println();
    }
    for (uint8_t i = 0; i < tail_count_; ++i) {
      Serial.print(F("# profile_tail")); Serial.print(i); Serial.print('=');
      for (uint8_t v = 0; v < 8; ++v) {
        if (v) Serial.print(',');
        Serial.print(tails_[i][v]);
      }
      Serial.println();
    }
  }
 private:
  static uint32_t cycles() {
    asm volatile("" ::: "memory");
    const uint32_t value = ARM_DWT_CYCCNT;
    asm volatile("" ::: "memory");
    return value;
  }
  static void printValue(const char *name, uint64_t value) {
    Serial.print(F("# profile_")); Serial.print(name); Serial.print('='); Serial.println(value);
  }
  void beginSweep() {
    if (!enabled_) return;
    const uint32_t now = cycles();
    foreground_cycles_ = now - previous_finish_cycle_;
    memset(pending_, 0, sizeof(pending_));
    memset(observed_, 0, sizeof(observed_));
    ++attempts_;
  }
  void endSweep(bool written, bool discarded) {
    if (!enabled_) return;
    const uint32_t began = cycles();
    if (F_CPU_ACTUAL != clock_hz_) ++frequency_changes_;
    if (have_previous_) {
      stats_[Period].add(pending_period_us_, 1000000);
      stats_[Gap].add(pending_gap_us_, 1000000);
      if (foreground_valid_) stats_[Foreground].add(foreground_cycles_, clock_hz_);
      else ++invalid_foreground_;
      // Retain the eight longest >100 us periods and their preceding gap costs.
      // This ties a long period to measured phases instead of comparing unrelated
      // phase maxima. uint32 wire intervals remain valid through cycle wraps.
      if (pending_period_us_ > 100) {
        uint8_t slot = 0;
        if (tail_count_ < 8) slot = tail_count_++;
        else {
          for (uint8_t i = 1; i < 8; ++i) if (tails_[i][0] < tails_[slot][0]) slot = i;
        }
        if (pending_period_us_ >= tails_[slot][0]) {
          const uint64_t values[] = {pending_period_us_, pending_gap_us_,
              previous_acquisition_, previous_encode_, previous_capacity_,
              previous_write_, previous_bookkeeping_,
              foreground_valid_ ? foreground_cycles_ : 0};
          memcpy(tails_[slot], values, sizeof(values));
        }
      }
    }
    for (uint8_t p = 0; p < PhaseCount; ++p) {
      if (observed_[p]) stats_[p].add(pending_[p], clock_hz_);
    }
    if (written) ++written_;
    if (discarded) ++discarded_;
    have_previous_ = written || discarded;
    previous_start_us_ = current_start_us_;
    previous_end_us_ = current_end_us_;
    previous_acquisition_ = pending_[Acquisition];
    previous_encode_ = pending_[Encode];
    previous_capacity_ = pending_[Capacity];
    previous_write_ = pending_[UsbWrite];
    previous_bookkeeping_ = uint32_t(cycles() - began);
    stats_[Bookkeeping].add(previous_bookkeeping_, clock_hz_);
    previous_finish_cycle_ = cycles();
  }
  bool enabled_ = false, have_previous_ = false;
  Stats stats_[PhaseCount];
  uint64_t pending_[PhaseCount] = {};
  bool observed_[PhaseCount] = {};
  uint32_t clock_hz_ = 0, attempts_ = 0, written_ = 0, discarded_ = 0;
  uint32_t invalid_foreground_ = 0, frequency_changes_ = 0;
  uint32_t acquisition_cycle_ = 0, current_start_us_ = 0, current_end_us_ = 0;
  uint32_t previous_start_us_ = 0, previous_end_us_ = 0;
  uint32_t previous_finish_cycle_ = 0, foreground_cycles_ = 0;
  uint32_t pending_period_us_ = 0, pending_gap_us_ = 0;
  bool foreground_valid_ = false;
  uint64_t tails_[8][8] = {};
  uint8_t tail_count_ = 0;
  uint64_t previous_acquisition_ = 0, previous_encode_ = 0, previous_capacity_ = 0;
  uint64_t previous_write_ = 0, previous_bookkeeping_ = 0;
  uint32_t probe_min_ = 0, probe_max_ = 0;
  uint32_t write_calls_ = 0, capacity_min_ = 0, capacity_max_ = 0, capacity_low_ = 0;
};
#define TB_PROFILE_SCOPE(name, phase) AcquisitionProfiler::Scope name(profile_, AcquisitionProfiler::phase)
#else
#define TB_PROFILE_SCOPE(name, phase)
#endif
