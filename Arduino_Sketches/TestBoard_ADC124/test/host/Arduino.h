#pragma once
#include <stdint.h>
#include <stddef.h>
static constexpr int LOW = 0, HIGH = 1, OUTPUT = 1;
void digitalWrite(uint8_t pin, int value);
void pinMode(uint8_t pin, int mode);
void delayNanoseconds(uint32_t ns);
void delayMicroseconds(uint32_t us);
uint32_t micros();
void yield();
