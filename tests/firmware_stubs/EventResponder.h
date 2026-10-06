#pragma once
class EventResponder {
 public:
  void clearEvent() { ready = false; }
  explicit operator bool() const { return ready; }
  bool ready = false;
};
