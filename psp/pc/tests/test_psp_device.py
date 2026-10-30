"""End to end: the host's RP2 transport against the PSP device code, run as
the desktop simulator (psp/device/build/rp2_sim). Build it first:
    python ../tools/build_sim.py
then, from psp/pc:  python -m unittest tests.test_psp_device -v"""
import hashlib
import json
import os
import secrets
import socket
import struct
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from reference_transport import TransportError, exchange  # noqa: E402

SIM = Path(__file__).resolve().parents[2] / "device" / "build" / ("rp2_sim.exe" if os.name == "nt" else "rp2_sim")
APP = "psp-homebrew"


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@unittest.skipUnless(SIM.exists(), "build the simulator first (psp/tools/build_sim.py)")
class PspDeviceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        root = Path(cls.temp.name) / "stick"
        (root / "halo" / "log").mkdir(parents=True)
        (root / "PSP" / "GAME" / "HOMEBREW_TEST").mkdir(parents=True)
        cls.log = "".join("line %05d power: the sleep switch works\n" % k for k in range(4000)).encode()
        (root / "halo" / "log" / "log.txt").write_bytes(cls.log)
        (root / "PSP" / "GAME" / "HOMEBREW_TEST" / "hce-install.json").write_text('{"files": 11}')
        # a stand-in for the PSP's settings memory: the registry and a theme
        cls.root = root
        cls.flash1 = Path(cls.temp.name) / "flash1"
        cls.settings = {"registry/system.dreg": os.urandom(131072), "registry/system.ireg": os.urandom(2048),
                        "vsh/theme/custom_theme.dat": os.urandom(300000), "vsh/theme/wallpaper.bmp": os.urandom(40000)}
        for name, body in cls.settings.items():
            (cls.flash1 / name).parent.mkdir(parents=True, exist_ok=True)
            (cls.flash1 / name).write_bytes(body)
        (cls.flash1 / "net" / "http").mkdir(parents=True)  # an empty folder
        cls.token = secrets.token_hex(32)
        cls.port = free_port()
        config = f"app_id={APP}\nport={cls.port}\ntoken={cls.token}\nsession=on\n"
        (root / "halo" / "remotepilot.cfg").write_text(config)
        cls.proc = subprocess.Popen([str(SIM), "--config", str(root / "halo" / "remotepilot.cfg"), "--root", str(root),
                                     "--flash1", str(cls.flash1)],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                socket.create_connection(("127.0.0.1", cls.port), timeout=0.2).close()
                break
            except OSError:
                time.sleep(0.05)

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait(5)
        cls.temp.cleanup()

    def ask(self, kind, body=b"", token=None):
        return exchange("127.0.0.1", self.port, token or self.token, APP, kind, body, timeout=10)

    def test_ping_and_meta(self):
        self.assertEqual(self.ask("ping"), b"")
        meta = json.loads(self.ask("meta"))
        self.assertEqual((meta["schemaVersion"], meta["appId"]), (2, APP))

    def test_screenshot_and_stream(self):
        shot = self.ask("shot")
        self.assertEqual(shot[:2], b"BM")
        self.assertEqual(struct.unpack_from("<ii", shot, 18), (480, 272))
        self.assertEqual(len(shot), 54 + 480 * 3 * 272)
        packet = self.ask("stream")
        image, audio = struct.unpack_from("<II", packet)
        self.assertEqual((audio, len(packet)), (0, 8 + image))
        self.assertEqual(struct.unpack_from("<ii", packet, 8 + 18), (240, 136))
        # the pattern moves: two frames differ
        self.assertNotEqual(self.ask("stream")[8 + 54:], packet[8 + 54:])

    def test_log_tail(self):
        tail = self.ask("log")
        self.assertEqual(len(tail), 65536)
        self.assertTrue(self.log.endswith(tail))

    def test_files_and_file(self):
        listing = json.loads(self.ask("files", b"ms0:/halo"))
        names = {item["name"] for item in listing["entries"]}
        self.assertIn("log", names)
        self.assertNotIn("remotepilot.cfg", names)  # the pairing token is never listed
        self.assertEqual(self.ask("file", b"ms0:/halo/log/log.txt"), self.log)
        games = json.loads(self.ask("files", b"ms0:/PSP/GAME"))
        self.assertEqual([e["name"] for e in games["entries"] if e["dir"]], ["HOMEBREW_TEST"])

    def test_refusals(self):
        for path in (b"ms0:/halo/remotepilot.cfg", b"ms0:/HALO/RemotePilot.CFG", b"ms0:/halo/../halo/remotepilot.cfg",
                     b"ms0:/remotepilot/remotepilot.cfg", b"ms0:/REMOTEPILOT/REMOTEPILOT.CFG",
                     b"ms0:/halo/log/", b"ms0:/./halo", b"C:/Windows", b"ms0:/halo\\log", b"ms0://halo",
                     b"ms0:/halo/log/log.txt\x00x"):
            with self.subTest(path=path), self.assertRaises(TransportError):
                self.ask("file", path)
        with self.assertRaises(TransportError):
            self.ask("ping", token="0" * 64)  # wrong pairing: the device's proof fails
        with self.assertRaises(TransportError):
            self.ask("console", b"help")       # not offered on the PSP

    def test_controls(self):
        self.assertEqual(self.ask("gamepad", b'{"buttons":4097,"lx":0.5,"ly":-1,"rx":0,"ry":0,"lt":0,"rt":0,"frames":2}'), b"ok")
        self.assertEqual(self.ask("input", b'{"button":"TRIANGLE","frames":3}'), b"ok")
        for bad in (b'{"buttons":70000,"lx":0,"ly":0,"frames":1}', b'{"buttons":1,"lx":2,"ly":0,"frames":1}',
                    b'{"buttons":1,"lx":0,"ly":0,"frames":nan}', b'{"buttons":nan,"lx":0,"ly":0,"frames":1}',
                    b'{"buttons":1,"lx":0,"ly":0,"frames":9}', b'{"button":"HOME","frames":1}'):
            with self.subTest(bad=bad), self.assertRaises(TransportError):
                self.ask("input" if b"button\"" in bad else "gamepad", bad)

    def request(self, kind, payload):
        """The adapter's request(), straight to the simulator."""
        result = self.ask(kind, b"" if payload in (None, "-") else payload.encode())
        return json.loads(result) if kind in ("backup", "files") else result

    def test_settings_backup_on_the_device(self):
        manifest = json.loads(self.ask("backup"))
        self.assertEqual(manifest["error"], "")
        self.assertTrue(manifest["theme"])
        self.assertEqual(manifest["failed"], 0)
        listed = {item["path"]: item for item in manifest["files"]}
        self.assertEqual(set(listed), set(self.settings))
        folder = self.root / manifest["folder"][len("ms0:/"):]
        for name, body in self.settings.items():
            self.assertEqual(listed[name]["size"], len(body))
            self.assertEqual(listed[name]["sha256"], hashlib.sha256(body).hexdigest())
            self.assertEqual((folder / name).read_bytes(), body)
            # and the viewer can fetch every copy
            self.assertEqual(self.ask("file", f"{manifest['folder']}/{name}".encode()), body)
        self.assertTrue((folder / "net" / "http").is_dir())
        self.assertEqual(json.loads((folder / "manifest.json").read_bytes()), manifest)
        # a second backup never writes into the first one's folder
        again = json.loads(self.ask("backup"))
        self.assertNotEqual(again["folder"], manifest["folder"])
        with self.assertRaises(TransportError):
            self.ask("backup", b"flash0:/")  # no body: what it copies is fixed
        # the network stops at 16 backups on the stick, so it can't fill it
        backups = self.root / "BACKUP"
        made = [backups / f"flash1-20000101-0000{k:02d}" for k in range(16)]
        for folder in made:
            folder.mkdir(exist_ok=True)
        try:
            with self.assertRaises(TransportError):
                self.ask("backup")
        finally:
            for folder in made:
                folder.rmdir()

    def test_settings_backup_fetched_and_checked(self):
        import settings_backup
        with tempfile.TemporaryDirectory() as here:
            result = settings_backup.fetch(self.request, here)
            self.assertTrue(result["checked"] and result["theme"])
            self.assertEqual(result["files"], len(self.settings))
            kept = Path(here) / result["name"]
            for name, body in self.settings.items():
                self.assertEqual((kept / name).read_bytes(), body)
            self.assertEqual(settings_backup.main(["", str(kept)]), 0)
            # the same backup again, now from the card: already here and the same
            again = settings_backup.fetch(self.request, here, f"ms0:/BACKUP/{result['name']}")
            self.assertEqual(again["name"], result["name"])
            listed = settings_backup.local_backups(here)
            self.assertEqual([(item["name"], item["checked"]) for item in listed], [(result["name"], True)])
            # a copy changed here afterwards is reported, not trusted
            (kept / "vsh" / "theme" / "custom_theme.dat").write_bytes(b"changed")
            self.assertFalse(settings_backup.local_backups(here)[0]["checked"])
            self.assertEqual(settings_backup.main(["", str(kept)]), 1)

    def test_settings_backup_refuses_a_bad_copy(self):
        import settings_backup

        def corrupting(kind, payload):
            result = self.request(kind, payload)
            return result[:-1] + bytes([result[-1] ^ 1]) if kind == "file" and payload.endswith(".dat") else result

        with tempfile.TemporaryDirectory() as here:
            with self.assertRaises(settings_backup.BackupError):
                settings_backup.fetch(corrupting, here)
            self.assertEqual(list(Path(here).iterdir()), [])  # nothing half-copied is kept
            with self.assertRaises(settings_backup.BackupError):
                settings_backup.fetch(self.request, here, "ms0:/halo")  # only flash1-… folders
            for name in ("CON", "registry/nul.txt", "Com1"):  # Windows device names
                with self.assertRaises(settings_backup.BackupError):
                    settings_backup._relative(name)

    def test_replay_and_tamper(self):
        """A request signed for one nonce is refused on the next connection."""
        import hashlib
        import hmac
        import re
        key = bytes.fromhex(self.token)

        def connect():
            conn = socket.create_connection(("127.0.0.1", self.port), timeout=5)
            conn.sendall(f"RP2 HELLO {APP}\n".encode())
            line = b""
            while not line.endswith(b"\n"):
                line += conn.recv(1)
            return conn, bytes.fromhex(re.match(rb"RP2 CHALLENGE ([0-9a-f]{32})", line).group(1).decode())

        conn, nonce = connect()
        mac = hmac.new(key, b"request\n" + nonce + b"\n7\nping\n", hashlib.sha256).hexdigest().encode()
        request = b"RP2 REQUEST 7 ping 0 " + mac + b"\n"
        conn.sendall(request)
        self.assertTrue(conn.recv(200).startswith(b"RP2 RESPONSE 7 ping 0 "))
        conn.close()
        conn, _ = connect()
        conn.sendall(request)  # the same bytes, a new nonce
        self.assertEqual(conn.recv(200), b"")
        conn.close()


@unittest.skipUnless(SIM.exists(), "build the simulator first (psp/tools/build_sim.py)")
class NoFlashTest(unittest.TestCase):
    """A PSP that can't read flash1: the backup says so and writes nothing."""

    def test_backup_says_why(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "stick"
            (root / "halo").mkdir(parents=True)
            token, port = secrets.token_hex(32), free_port()
            (root / "halo" / "remotepilot.cfg").write_text(f"app_id={APP}\nport={port}\ntoken={token}\nsession=on\n")
            proc = subprocess.Popen([str(SIM), "--config", str(root / "halo" / "remotepilot.cfg"), "--root", str(root),
                                     "--once"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                deadline = time.monotonic() + 5
                while True:
                    try:
                        manifest = json.loads(exchange("127.0.0.1", port, token, APP, "backup", timeout=10))
                        break
                    except OSError:
                        if time.monotonic() > deadline:
                            raise
                        time.sleep(0.05)
                self.assertEqual((manifest["files"], manifest["error"]), ([], "flash1:/ can't be read here"))
                self.assertFalse((root / "BACKUP").exists())
            finally:
                proc.wait(5)


if __name__ == "__main__":
    unittest.main()
