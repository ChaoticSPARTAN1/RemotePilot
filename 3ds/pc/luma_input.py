"""Separate Luma InputRedirection UDP encoder. No firmware changes or discovery.

Wire layout documented by Luma3DS input_redirection.c at
144f55305ec3e62b6e25207865df527b31abae1e. No Luma code is copied.
UDP delivery and console releases cannot be acknowledged by this protocol.
"""
import socket
import struct
import threading
import time
from homebrew_protocol import private_host

BUTTONS = {name: 1 << bit for bit, name in enumerate(
    ("A", "B", "SELECT", "START", "RIGHT", "LEFT", "UP", "DOWN", "R", "L", "X", "Y"))}


def packet(button="NONE", home=False, touch=None):
    if button not in (*BUTTONS, "NONE") or type(home) is not bool:
        raise ValueError("Unsupported system button")
    hid = 0xfff ^ BUTTONS.get(button, 0)
    ts = 0x02000000
    if touch is not None:
        x, y = touch
        if type(x) is not int or type(y) is not int or not 0 <= x <= 319 or not 0 <= y <= 239:
            raise ValueError("Invalid system touch coordinates")
        # Match the original TuxSH client's pixel-to-raw mapping.
        ts = (x * 4095 // 320) | ((y * 4095 // 240) << 12) | 0x01000000
    return struct.pack("<5I", hid, ts, 0x007ff7ff, 0x80800081, int(home))


class LumaInput:
    def __init__(self, allowed):
        self.allowed = allowed
        self.lock = threading.RLock()
        self.host = None
        self.owner = None
        self.expiry = 0
        self.version = ""

    def arm(self, host, owner, version):
        import re
        if not self.allowed() or not isinstance(owner, str) or not re.fullmatch(r"[0-9a-f]{32}", owner) \
                or not isinstance(version, str) or not re.fullmatch(r"[0-9]{1,2}\.[0-9]{1,2}(?:\.[0-9]{1,2})?", version):
            raise ValueError("Select 3DS Homebrew, enable the link and confirm the installed Luma version")
        with self.lock:
            if self.owner not in (None, owner) and time.monotonic() < self.expiry:
                raise ValueError("System controls are armed in another tab")
            self.host = private_host(host)
            self.owner, self.version, self.expiry = owner, version, time.monotonic() + 1.5

    def release(self):
        with self.lock:
            self.owner, self.expiry = None, 0
            if self.host:
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                    for _ in range(3):
                        try:
                            sock.sendto(packet(), (self.host, 4950))
                        except OSError:
                            pass  # best effort; this transport cannot acknowledge release

    def pulse(self, owner, button="NONE", home=False, touch=None, milliseconds=100):
        if type(milliseconds) is not int or not 20 <= milliseconds <= 250:
            raise ValueError("System presses must last 20..250 ms")
        with self.lock:
            if not self.allowed() or owner != self.owner or time.monotonic() >= self.expiry:
                raise ValueError("Arm system controls in this focused tab first")
            data = packet(button, home, touch)
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                try:
                    sock.sendto(data, (self.host, 4950))
                    time.sleep(milliseconds / 1000)
                except OSError:
                    raise ValueError("System UDP send failed; use the console's physical stop") from None
                finally:
                    for _ in range(3):
                        try:
                            sock.sendto(packet(), (self.host, 4950))
                        except OSError:
                            pass
        return {"ok": True, "delivery": "unacknowledged", "homeVisible": None}

    def status(self):
        return {"armed": bool(self.allowed() and self.owner and time.monotonic() < self.expiry),
                "version": self.version, "hardwareVerified": False, "delivery": "unacknowledged"}
