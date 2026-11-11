"""SBC-11R4 Modbus RTU frame builder and manual-example CRC check.

CRC-16/Modbus: poly 0xA001 (reflected 0x8005), init 0xFFFF, sent low byte first.
Bit layout of 0x002B (manual p.4, confirmed on the bench 2026-10-14): b31 dir
(0 = Near / motor side, 1 = Far), b27 IR2 polarity, b26 IR1 polarity, b25 IR2 enable,
b24 IR1 enable, b23..0 step count (1600 steps = 1 mm). Polarity 0 = stop when input
reads "High", 1 = stop when "Low"; the NO limit switches read Low when pressed, so use 1.
"""


def crc16_modbus(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def frame(pdu: bytes) -> bytes:
    c = crc16_modbus(pdu)
    return pdu + bytes([c & 0xFF, c >> 8])


def hx(b: bytes) -> str:
    return " ".join(f"{x:02X}" for x in b)


def rd(slave, reg, n=1):
    return frame(bytes([slave, 0x03, reg >> 8, reg & 0xFF, n >> 8, n & 0xFF]))


def wr16(slave, reg, val):
    return frame(bytes([slave, 0x06, reg >> 8, reg & 0xFF, val >> 8, val & 0xFF]))


def wr32(slave, reg, val):
    return frame(bytes([slave, 0x10, reg >> 8, reg & 0xFF, 0x00, 0x02, 0x04])
                 + val.to_bytes(4, "big"))


def pos_word(steps, forward, ir1=False, ir2=False, ir1_low=False, ir2_low=False):
    assert 0 < steps <= 0xFFFFFF
    return ((forward << 31) | (ir2_low << 27) | (ir1_low << 26)
            | (ir2 << 25) | (ir1 << 24) | steps)


def speed_word(forward, ir1=False, ir2=False, ir1_low=False, ir2_low=False):
    return (forward << 4) | (ir2_low << 3) | (ir1_low << 2) | (ir2 << 1) | ir1


# ---------------------------------------------------------------- manual examples
MANUAL = [  # (page, description, printed hex)
    (2, "0x0020 write addr 0->1 (send)", "00 06 00 20 00 01 48 11"),
    (2, "0x0020 write addr (reply)", "01 06 00 20 00 01 49 C0"),
    (3, "0x0021 baud 9600 (send)", "01 10 00 21 00 02 04 00 00 25 80 2B 4B"),
    (3, "0x0021 baud (reply)", "01 10 00 21 00 02 11 C2"),
    (3, "0x0026 run speed 3200 (send)", "01 10 00 26 00 02 04 00 00 0C 80 75 3D"),
    (3, "0x0026 (reply)", "01 10 00 26 00 02 A0 03"),
    (3, "0x0028 temp speed 3200 (send)", "01 10 00 28 00 02 04 00 00 0C 80 F4 B1"),
    (3, "0x0028 (reply, as printed: reg 0x0024)", "01 10 00 24 00 02 01 C3"),
    (4, "0x002A speed mode 0x0001 (send=reply)", "01 06 00 2A 00 01 69 C2"),
    (4, "0x002B 51200 steps (send)", "01 10 00 2B 00 02 04 00 00 C8 00 E7 C4"),
    (4, "0x002B (reply)", "01 10 00 2B 00 02 31 C0"),
    (5, "0x002D stop/lock (send=reply)", "01 06 00 2D 00 00 19 C3"),
    (5, "0x002E read IR (send)", "01 03 00 2E 00 01 E4 03"),
    (5, "0x002E (reply 0x0003)", "01 03 02 00 03 F8 45"),
]


def check_manual():
    print("== manual examples: printed CRC vs computed ==")
    for page, desc, s in MANUAL:
        b = bytes.fromhex(s.replace(" ", ""))
        pdu, printed = b[:-2], b[-2:]
        good = frame(pdu)[-2:]
        st = "OK" if good == printed else f"MISMATCH (computed {hx(good)})"
        print(f"p{page} {desc:40s} {s:42s} {st}")
    # what the 0x0028 reply should be
    print("   0x0028 reply if reg were 0x0028:", hx(frame(bytes.fromhex("011000280002"))))


def build():
    N = 1600  # 1 mm at 2 mm lead, 3200 steps/rev
    H = 155 * 1600  # bounded homing: full 150 mm stroke + 5 mm
    rows = [
        ("Read address 0x0020 @slave 0", rd(0, 0x0020)),
        ("Read address 0x0020 @slave 1 (after change)", rd(1, 0x0020)),
        ("Write address 1 (0x06 @slave 0)", wr16(0, 0x0020, 1)),
        ("Temp speed 3200 step/s (0x0028)", wr32(1, 0x0028, 3200)),
        ("Read run speed 0x0026 (2 regs) - identify meaning", rd(1, 0x0026, 2)),
    ]
    for low in (False, True):
        tag = "stop-on-Low" if low else "stop-on-High"
        rows += [
            (f"+N fwd toward Far, IR2 only, {tag}",
             wr32(1, 0x002B, pos_word(N, 1, ir2=True, ir2_low=low))),
            (f"-N rev toward Near, IR1 only, {tag}",
             wr32(1, 0x002B, pos_word(N, 0, ir1=True, ir1_low=low))),
            (f"Speed-mode home rev, IR1 stop, {tag}",
             wr16(1, 0x002A, speed_word(0, ir1=True, ir1_low=low))),
            (f"Bounded home -155 mm rev, IR1 stop, {tag}",
             wr32(1, 0x002B, pos_word(H, 0, ir1=True, ir1_low=low))),
        ]
    rows += [
        ("Stop & hold 0x002D=0", wr16(1, 0x002D, 0)),
        ("Stop & release 0x002D=1", wr16(1, 0x002D, 1)),
        ("Read limits 0x002E", rd(1, 0x002E)),
        ("Read limits 0x002E @slave 0", rd(0, 0x002E)),
    ]
    print("\n== frames (slave 1 unless noted) ==")
    for d, f in rows:
        print(f"{d:52s} {hx(f)}")
    print("\nvalues: +N IR2/High 0x%08X, -N IR1/High 0x%08X, home 0x%08X"
          % (pos_word(N, 1, ir2=True), pos_word(N, 0, ir1=True), pos_word(H, 0, ir1=True)))


if __name__ == "__main__":
    assert crc16_modbus(b"123456789") == 0x4B37  # CRC-16/MODBUS check value
    check_manual()
    build()
