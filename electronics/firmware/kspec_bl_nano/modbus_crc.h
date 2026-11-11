// CRC-16/MODBUS (poly 0xA001 reflected, init 0xFFFF). Low byte is sent first.
#pragma once
#include <stdint.h>
#include <stddef.h>

static inline uint16_t modbus_crc16(const uint8_t *buf, size_t len) {
  uint16_t crc = 0xFFFF;
  for (size_t i = 0; i < len; i++) {
    crc ^= buf[i];
    for (uint8_t b = 0; b < 8; b++) crc = (crc & 1) ? (crc >> 1) ^ 0xA001 : crc >> 1;
  }
  return crc;
}
