"""One back-illumination cycle through the Uno firmware (PC -> Uno -> MAX485 -> SBC-11R4):
home to Near, go down DEPTH mm, light on for TIME s, light off, return to Near, release the motor.

usage: python bl_cycle.py [-d DEPTH_MM] [-t TIME_S] [--port PORT] [--dry-run]
    python bl_cycle.py                 # 130 mm, 5 s
    python bl_cycle.py -d 138 -t 10
    python bl_cycle.py --dry-run       # print the command lines, no serial port

Follows the operation rules in README.md ("Operation"): bounded 0x002B moves only, no
automatic resend of a move, IN soft limit counted from Near, speed <= 16000 step/s rewritten before
every move, lamp watchdog with a stop frame, Near approached at 1 mm/s as a lost-step check.
Ctrl-C (or any error) switches the light off and stops the motor. Needs only pyserial.
"""

import argparse
import sys
import time

STEPS_PER_MM = 1600
IN_LIMIT_MM = 140.0  # never below IN on the instrument: the photo-estimated worm drive is at ~148 mm
MAX_SPEED = 16000  # step/s; 24000 loses steps from the start, 19200 is the highest verified
HOME_SPEED = 3200  # step/s (2 mm/s): the stage stops on the Near switch ~2 mm before the hard stop
SLOW_SPEED = 1600  # step/s (1 mm/s) for the final Near approach
APPROACH_MM = 2.0  # fast return stops this far short of Near; the slow approach covers the rest
APPROACH_TOL_MM = 0.3  # Near must trip within APPROACH_MM +- this, else steps were lost
PING_EVERY_S = 15  # firmware watchdog is 60 s
SLAVE = 1
DEFAULT_PORT = "/dev/cu.usbserial-A5069RR4"  # bench Uno (FT232R)


# ------------------------------------------------------------ SBC-11R4 frames (as sbc_frames.py)
def wr16(reg, val):
    return bytes([SLAVE, 0x06, reg >> 8, reg & 0xFF, val >> 8, val & 0xFF])


def wr32(reg, val):
    return bytes([SLAVE, 0x10, reg >> 8, reg & 0xFF, 0x00, 0x02, 0x04]) + val.to_bytes(4, "big")


def rd(reg, n=1):
    return bytes([SLAVE, 0x03, reg >> 8, reg & 0xFF, n >> 8, n & 0xFF])


def move_word(mm, far):
    """0x002B relative move; only the limit in the direction of travel is enabled (stop on Low)."""
    steps = round(mm * STEPS_PER_MM)
    assert 0 < steps <= 0xFFFFFF
    if far:  # b31 dir Far, b27 IR2 stop-on-Low, b25 IR2 enable
        return (1 << 31) | (1 << 27) | (1 << 25) | steps
    return (1 << 26) | (1 << 24) | steps  # Near: b26 IR1 stop-on-Low, b24 IR1 enable


STOP_HOLD = wr16(0x2D, 0)
RELEASE = wr16(0x2D, 1)


# ------------------------------------------------------------ link to the Uno
class Uno:
    def __init__(self, port, dry_run):
        self.dry = dry_run
        self.t0 = time.time()
        self.last = time.time()
        if dry_run:
            self.sim_mm, self.sim_speed, self.sim_eta = 0.0, HOME_SPEED, 0.0  # simulated stage
            return
        import serial

        self.s = serial.Serial(port, 9600, timeout=1.0)
        time.sleep(2.2)  # opening the port resets the Uno (DTR)
        self.s.reset_input_buffer()

    def log(self, msg):
        print(f"[{time.time() - self.t0:6.1f}] {msg}", flush=True)

    def cmd(self, line, quiet=False):
        if self.dry:
            r = self.simulate(line)
        else:
            self.s.write((line + "\n").encode())
            r = self.s.readline().decode(errors="replace").strip()
        self.last = time.time()
        if not quiet:
            self.log(f"{line:34s} -> {r}")
        return r

    def simulate(self, line):
        """Dry run: track the stage position (mm from Near) and answer like the firmware."""
        if line.startswith("MB 0103002E"):  # 0x002E: 0x0002 = Near pressed, 0x0003 = released
            return "OK 01030200" + ("02" if self.sim_mm <= 0 else "03")
        if line.startswith("MB 01100028"):
            self.sim_speed = int(line[-8:], 16)
        elif line.startswith("MB 0110002B"):
            w = int(line[-8:], 16)
            mm = (w & 0xFFFFFF) / STEPS_PER_MM
            if w >> 31:
                self.sim_mm += mm
            else:
                self.sim_eta = min(mm, self.sim_mm) / (self.sim_speed / STEPS_PER_MM)
                self.sim_mm = max(0.0, self.sim_mm - mm)
        return "OK (dry run)"

    def mb(self, pdu, quiet=False):
        """Send a Modbus frame (the firmware appends the CRC). Never resent: moves are relative."""
        r = self.cmd("MB " + pdu.hex().upper(), quiet)
        if not r.startswith("OK"):
            raise RuntimeError(f"SBC did not answer ({r}); position is invalid, re-home")
        return r

    def limits(self):
        """(near, far) pressed. 0x002E: bit0 = IR1 = Near, bit1 = IR2 = Far, pressed = 0."""
        r = self.mb(rd(0x2E), quiet=True)
        v = int(r.split()[1][6:10], 16)
        return not v & 1, not v & 2

    def wait(self, sec):
        """Sleep, pinging the firmware so its lamp watchdog does not expire."""
        if self.dry:
            self.log(f"(wait {sec:.1f} s)")
            return
        end = time.time() + sec
        while time.time() < end:
            if time.time() - self.last > PING_EVERY_S:
                self.cmd("PING", quiet=True)
            time.sleep(min(0.25, max(0.0, end - time.time())))

    def wait_near(self, tmax):
        """Seconds until Near reads pressed, or None after tmax."""
        if self.dry:
            return self.sim_eta if self.sim_mm <= 0 else None
        t = time.time()
        while time.time() - t < tmax:
            if self.limits()[0]:
                return time.time() - t
            time.sleep(0.05)
        return None

    def move(self, mm, far, speed):
        """Bounded move at speed (step/s); returns once the expected travel time has passed."""
        self.mb(wr32(0x28, speed))  # temporary speed resets to 3200 at SBC power-up: always rewrite
        self.mb(wr32(0x2B, move_word(mm, far)))
        self.wait(mm * STEPS_PER_MM / speed + 1.5)

    def close(self):
        if not self.dry:
            self.s.close()


# ------------------------------------------------------------ the cycle
def home(u):
    """Bounded home to Near at 2 mm/s (the full 150 mm stroke + 5 mm)."""
    if u.limits()[0]:
        u.log("already at Near")
        return
    u.log("homing to Near at 2 mm/s")
    u.mb(wr32(0x28, HOME_SPEED))
    u.mb(wr32(0x2B, move_word(155, far=False)))
    th = u.wait_near(155 / (HOME_SPEED / STEPS_PER_MM) + 5)
    if th is None:
        raise RuntimeError("Near not reached while homing")
    u.log(f"home: Near after {th:.1f} s")


def cycle(u, depth, exposure, speed):
    u.cmd("PING")
    u.cmd("WDTFRAME " + STOP_HOLD.hex().upper())  # watchdog expiry also stops the stage (not stored)
    u.cmd("L OFF")
    home(u)

    u.log(f"down {depth:.1f} mm at {speed / STEPS_PER_MM:.1f} mm/s")
    u.move(depth, far=True, speed=speed)
    near, far = u.limits()
    if far:
        raise RuntimeError("Far switch pressed after the move down")
    if near:
        raise RuntimeError("still at Near after the move down: the stage did not move")

    u.cmd("L MAIN ON")
    u.wait(exposure)
    u.cmd("L MAIN OFF")

    u.log(f"up {depth - APPROACH_MM:.1f} mm, then {APPROACH_MM:.0f} mm at 1 mm/s to Near")
    u.move(depth - APPROACH_MM, far=False, speed=speed)
    if u.limits()[0]:
        raise RuntimeError("Near pressed before the slow approach: steps lost on the way down")
    u.mb(wr32(0x28, SLOW_SPEED))
    u.mb(wr32(0x2B, move_word(8, far=False)))
    th = u.wait_near(10)
    if th is None:
        raise RuntimeError("Near not reached on the slow approach: steps lost")
    dist = th * SLOW_SPEED / STEPS_PER_MM
    ok = abs(dist - APPROACH_MM - 0.1) <= APPROACH_TOL_MM
    u.log(f"Near after ~{dist:.2f} mm (expect ~2.1) -> {'no lost steps' if ok else 'WARNING: lost steps, re-home'}")

    u.mb(wr32(0x28, MAX_SPEED))
    u.mb(RELEASE)  # the lead screw is not back-drivable: release at rest
    u.cmd("L ?")
    return ok


def find_port():
    """The one USB serial port that looks like an Uno (FTDI, CH340 or Arduino), else the bench default."""
    try:
        from serial.tools import list_ports
    except ImportError:
        return DEFAULT_PORT
    vids = {0x0403, 0x1A86, 0x2341, 0x2A03}
    ports = [p.device for p in list_ports.comports() if p.vid in vids]
    if len(ports) == 1:
        return ports[0]
    if ports:
        sys.exit(f"several candidate ports {ports}: pick one with --port")
    return DEFAULT_PORT


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("-d", "--depth", type=float, default=130.0,
                    help=f"travel down from Near in mm (default 130, max {IN_LIMIT_MM:.0f})")
    ap.add_argument("-t", "--time", type=float, default=5.0,
                    help="light-on time in s (default 5)")
    ap.add_argument("--speed", type=float, default=10.0,
                    help=f"travel speed in mm/s (default 10, max {MAX_SPEED / STEPS_PER_MM:.0f})")
    ap.add_argument("--port", help="serial port of the Uno (default: auto-detect)")
    ap.add_argument("--dry-run", action="store_true", help="print the commands, open no port")
    a = ap.parse_args()

    if not 5.0 <= a.depth <= IN_LIMIT_MM:
        ap.error(f"--depth must be 5 to {IN_LIMIT_MM:.0f} mm (IN soft limit)")
    if a.time <= 0:
        ap.error("--time must be positive")
    speed = round(a.speed * STEPS_PER_MM)
    if not SLOW_SPEED <= speed <= MAX_SPEED:
        ap.error(f"--speed must be 1 to {MAX_SPEED / STEPS_PER_MM:.0f} mm/s")

    port = a.port or ("(dry run)" if a.dry_run else find_port())
    print(f"port {port}: depth {a.depth:.1f} mm, light {a.time:.1f} s, speed {a.speed:.1f} mm/s", flush=True)
    u = Uno(port, a.dry_run)
    ok = False
    try:
        ok = cycle(u, a.depth, a.time, speed)
    except BaseException as e:  # Ctrl-C included: light off, stage stopped
        u.log(f"ABORT: {e!r}")
        if not u.dry:
            u.s.reset_input_buffer()  # drop a reply cut off by Ctrl-C
        for line in ("L OFF", "MB " + STOP_HOLD.hex().upper()):
            try:
                u.cmd(line)
            except Exception:
                pass
        u.log("light off, stage stopped and held; position invalid: the next run re-homes")
    finally:
        u.close()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
