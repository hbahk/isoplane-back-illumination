// K-SPEC back-illumination controller: Arduino Nano (ATmega328P, 5 V, USB-powered).
// Reference firmware for circuit v2 (see README.md, "Electronics"). Bench-test before use.
//
// USB serial 9600 8N1, one text command per line, one reply line per command. The host must wait
// for the reply before sending the next line: SoftwareSerial blocks interrupts for ~1 ms per RS-485
// byte, and a low USB baud rate keeps the UART from overrunning during that time.
//   PING                 -> OK PONG
//   L MAIN ON|OFF        -> main backlight relay K1 (D5)
//   L BACKUP ON|OFF      -> backup LED relay K2 (D6)
//   L OFF                -> both off
//   L ?                  -> OK MAIN=0|1 BACKUP=0|1 INTERLOCK=0|1
//   INTERLOCK ON|OFF     -> ON (default): switching one light on switches the other off
//   MB <hex>             -> Modbus RTU pass-through: hex bytes without CRC (e.g. "MB 01030020 0002");
//                           the CRC is appended, the frame sent on RS-485, the reply returned as
//                           OK <hex incl. CRC> | ERR TIMEOUT | ERR CRC <hex>
//   WDT <s>              -> host watchdog, default 60 s, 0 = off. If no command arrives for <s> seconds,
//                           both lights go off and the WDTFRAME (if set) is sent once. The host should
//                           PING well inside the lease (e.g. every 20 s) while a lamp is on, so a crashed
//                           host cannot leave a lamp on into science frames.
//   WDTFRAME <hex>       -> Modbus frame (no CRC) to send on watchdog expiry, e.g. a stop command
//
// Motion logic (register meaning, limit-enable bits, direction) stays on the host, because the
// SBC-11R4 manual has inconsistencies that are settled on the bench. Host rules: home with a bounded
// 0x002B move (never the unbounded 0x002A speed mode), never retry a 0x002B write automatically
// (moves are relative: on a timeout send stop, mark the position invalid and re-home), and enforce the
// IN soft limit in steps counted from the Near limit.

#include <SoftwareSerial.h>
#include "modbus_crc.h"

const uint8_t PIN_RS485_RO = 2;   // MAX485 RO -> Nano RX
const uint8_t PIN_RS485_DI = 3;   // Nano TX -> MAX485 DI
const uint8_t PIN_RS485_DE = 4;   // MAX485 DE + /RE tied together: HIGH = transmit
const uint8_t PIN_K_MAIN = 5;     // relay IN1 (K1, main backlight)
const uint8_t PIN_K_BACKUP = 6;   // relay IN2 (K2, backup LEDs)
const uint8_t RELAY_ON = LOW;     // opto relay module: input LOW energises the coil (check on bench)
const uint8_t RELAY_OFF = HIGH;

const uint16_t MB_TIMEOUT_MS = 300;  // whole reply
const uint8_t MB_GAP_MS = 5;         // > 3.5 characters at 9600 Bd (3.65 ms) ends a frame

SoftwareSerial rs485(PIN_RS485_RO, PIN_RS485_DI);

bool mainOn = false, backupOn = false, interlock = true;
uint32_t wdtMs = 60000UL, lastCmdMs = 0;   // 1 min default lease (was 10 min until 2026-10-15)
bool wdtFired = false;
uint8_t wdtFrame[32];
uint8_t wdtFrameLen = 0;
char line[100];
uint8_t lineLen = 0;

void setRelays() {
  digitalWrite(PIN_K_MAIN, mainOn ? RELAY_ON : RELAY_OFF);
  digitalWrite(PIN_K_BACKUP, backupOn ? RELAY_ON : RELAY_OFF);
}

void setup() {
  // Order matters: latch the OFF level into the output registers before the pins become outputs,
  // otherwise the relays pulse on for a few microseconds at every reset.
  digitalWrite(PIN_K_MAIN, RELAY_OFF);
  digitalWrite(PIN_K_BACKUP, RELAY_OFF);
  pinMode(PIN_K_MAIN, OUTPUT);
  pinMode(PIN_K_BACKUP, OUTPUT);
  // The module pulls DE and /RE up (10 k), i.e. transmit, until we drive them: go to receive now.
  digitalWrite(PIN_RS485_DE, LOW);
  pinMode(PIN_RS485_DE, OUTPUT);
  rs485.begin(9600);
  Serial.begin(9600);
  lastCmdMs = millis();
  Serial.println(F("OK KSPEC-BL v2 ready"));
}

int hexNibble(char c) {
  if (c >= '0' && c <= '9') return c - '0';
  if (c >= 'a' && c <= 'f') return c - 'a' + 10;
  if (c >= 'A' && c <= 'F') return c - 'A' + 10;
  return -1;
}

// Parse hex digits (spaces allowed) into buf; returns the byte count or -1 on a bad string.
int parseHex(const char *s, uint8_t *buf, uint8_t maxLen) {
  int n = 0, hi = -1;
  for (; *s; s++) {
    if (*s == ' ') continue;
    int v = hexNibble(*s);
    if (v < 0) return -1;
    if (hi < 0) {
      hi = v;
    } else {
      if (n >= maxLen) return -1;
      buf[n++] = (uint8_t)((hi << 4) | v);
      hi = -1;
    }
  }
  return hi < 0 ? n : -1;
}

void printHex(const uint8_t *buf, uint8_t len) {
  for (uint8_t i = 0; i < len; i++) {
    if (buf[i] < 0x10) Serial.print('0');
    Serial.print(buf[i], HEX);
  }
}

// Send frame (CRC appended here) and collect the reply. Returns the reply length, 0 on timeout.
uint8_t modbusTransact(const uint8_t *pdu, uint8_t len, uint8_t *reply, uint8_t maxReply) {
  uint8_t frame[34];
  memcpy(frame, pdu, len);
  uint16_t crc = modbus_crc16(frame, len);
  frame[len] = crc & 0xFF;
  frame[len + 1] = crc >> 8;
  while (rs485.available()) rs485.read();  // drop stale bytes
  digitalWrite(PIN_RS485_DE, HIGH);
  delayMicroseconds(100);
  rs485.write(frame, len + 2);  // SoftwareSerial TX is blocking: the stop bit is out on return
  digitalWrite(PIN_RS485_DE, LOW);
  rs485.listen();
  uint8_t n = 0;
  uint32_t t0 = millis(), tLast = 0;
  while (millis() - t0 < MB_TIMEOUT_MS) {
    if (rs485.available()) {
      uint8_t b = rs485.read();
      if (n < maxReply) reply[n++] = b;
      tLast = millis();
    } else if (n > 0 && millis() - tLast > MB_GAP_MS) {
      break;
    }
  }
  return n;
}

void cmdModbus(const char *arg, bool quiet = false) {
  uint8_t pdu[32], reply[64];
  int len = parseHex(arg, pdu, sizeof(pdu));
  if (len < 2) {
    if (!quiet) Serial.println(F("ERR HEX"));
    return;
  }
  uint8_t n = modbusTransact(pdu, len, reply, sizeof(reply));
  if (quiet) return;
  if (n == 0) {
    Serial.println(F("ERR TIMEOUT"));
  } else if (n < 4 || modbus_crc16(reply, n - 2) != (uint16_t)(reply[n - 2] | (reply[n - 1] << 8))) {
    Serial.print(F("ERR CRC "));
    printHex(reply, n);
    Serial.println();
  } else {
    Serial.print(F("OK "));
    printHex(reply, n);
    Serial.println();
  }
}

void printLights() {
  Serial.print(F("OK MAIN="));
  Serial.print(mainOn);
  Serial.print(F(" BACKUP="));
  Serial.print(backupOn);
  Serial.print(F(" INTERLOCK="));
  Serial.println(interlock);
}

void handle(char *cmd) {
  if (!strcmp(cmd, "PING")) {
    Serial.println(F("OK PONG"));
  } else if (!strcmp(cmd, "L MAIN ON")) {
    if (interlock) backupOn = false;
    mainOn = true;
    setRelays();
    printLights();
  } else if (!strcmp(cmd, "L MAIN OFF")) {
    mainOn = false;
    setRelays();
    printLights();
  } else if (!strcmp(cmd, "L BACKUP ON")) {
    if (interlock) mainOn = false;
    backupOn = true;
    setRelays();
    printLights();
  } else if (!strcmp(cmd, "L BACKUP OFF")) {
    backupOn = false;
    setRelays();
    printLights();
  } else if (!strcmp(cmd, "L OFF")) {
    mainOn = backupOn = false;
    setRelays();
    printLights();
  } else if (!strcmp(cmd, "L ?")) {
    printLights();
  } else if (!strcmp(cmd, "INTERLOCK ON")) {
    interlock = true;
    if (mainOn && backupOn) backupOn = false;
    setRelays();
    printLights();
  } else if (!strcmp(cmd, "INTERLOCK OFF")) {
    interlock = false;
    printLights();
  } else if (!strncmp(cmd, "MB ", 3)) {
    cmdModbus(cmd + 3);
  } else if (!strncmp(cmd, "WDT ", 4)) {
    wdtMs = 1000UL * (uint32_t)atol(cmd + 4);
    wdtFired = false;
    Serial.print(F("OK WDT="));
    Serial.println(wdtMs / 1000);
  } else if (!strncmp(cmd, "WDTFRAME ", 9)) {
    int n = parseHex(cmd + 9, wdtFrame, sizeof(wdtFrame));
    wdtFrameLen = n > 1 ? n : 0;
    Serial.println(n > 1 ? F("OK WDTFRAME") : F("ERR HEX"));
  } else {
    Serial.println(F("ERR UNKNOWN"));
  }
}

void loop() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\r') continue;
    if (c == '\n') {
      line[lineLen] = 0;
      if (lineLen) handle(line);
      lineLen = 0;
      lastCmdMs = millis();
      wdtFired = false;
    } else if (lineLen < sizeof(line) - 1) {
      line[lineLen++] = (c >= 'a' && c <= 'z') ? c - 32 : c;  // case-insensitive
    }
  }
  if (wdtMs && !wdtFired && millis() - lastCmdMs > wdtMs) {
    wdtFired = true;
    mainOn = backupOn = false;
    setRelays();
    if (wdtFrameLen) {
      uint8_t reply[16];
      modbusTransact(wdtFrame, wdtFrameLen, reply, sizeof(reply));
    }
    Serial.println(F("WARN WDT lights off"));
  }
}
