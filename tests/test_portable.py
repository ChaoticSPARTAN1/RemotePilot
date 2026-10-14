import hashlib
import hmac
import json
from pathlib import Path
import socket
import struct
import tempfile
import threading
import unittest
from unittest.mock import patch

import presets
from build_portable import FILES
import reference_transport as rp
from reference_adapter import ReferenceAdapter
from plugin_runtime import PluginRuntime
import server


class PortableTests(unittest.TestCase):
    def test_checked_in_presets_and_manifest(self):
        self.assertEqual([path for path in FILES if path.startswith("presets/")],
                         ["presets/example/manifest.json"])
        self.assertIn("example", [item["id"] for item in presets.all_presets()])
        self.assertFalse((presets.PRESETS / "example" / "adapter.py").exists())
        self.assertEqual(presets.all_presets()[0]["display"]["layout"], "dual-screen")

    def test_pairing_is_private_and_reusable(self):
        manifest = {"id": "sample", "capabilities": []}
        with tempfile.TemporaryDirectory() as directory:
            adapter = ReferenceAdapter(directory, manifest)
            first = adapter.setup()
            config = Path(first["configPath"])
            original = config.read_bytes()
            self.assertIn(b"app_id=sample\n", original)
            self.assertIn(b"session=on\n", original)
            self.assertEqual(len(adapter._config()["token"]), 64)
            self.assertEqual(adapter.setup(), first)
            self.assertEqual(config.read_bytes(), original)
            with self.assertRaises(ValueError):
                adapter.set_host("192.0.2.1")
            self.assertEqual(adapter.set_host("127.0.0.1"), "127.0.0.1")
            self.assertEqual(adapter._config()["host"], "127.0.0.1")
            self.assertEqual(adapter.set_host("auto"), "auto")

    def test_installed_preset_one_step_setup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            preset = root / "presets" / "sample"
            preset.mkdir(parents=True)
            (preset / "adapter.py").write_text(
                "from reference_adapter import ReferenceAdapter\n"
                "def create_adapter(local_dir, manifest):\n"
                "    return ReferenceAdapter(local_dir, manifest)\n", encoding="utf-8")
            manifest = {"id": "sample", "capabilities": ["screenshot"],
                        "setup": {"deviceConfigPath": "device/private.cfg"}}
            runtime = PluginRuntime(manifest, root / "presets", root / "local")
            result = runtime.setup()
            self.assertEqual(result["deviceConfigPath"], "device/private.cfg")
            self.assertEqual(runtime.set_host("auto"), "auto")
            config = runtime.adapter_local_dir / result["configFile"]
            self.assertTrue(config.is_file())
            self.assertTrue(config.read_bytes().startswith(b"app_id=sample\n"))

    def test_rp2_authentication_and_tamper_rejection(self):
        token = "3a" * 32
        nonce = bytes.fromhex("12" * 16)
        key = bytes.fromhex(token)

        def serve_once(listener, corrupt):
            with listener.accept()[0] as conn:
                hello = b""
                while not hello.endswith(b"\n"):
                    hello += conn.recv(1)
                self.assertEqual(hello, b"RP2 HELLO sample\n")
                proof = hmac.new(key, b"device\nsample\n" + nonce, hashlib.sha256).hexdigest()
                conn.sendall(f"RP2 CHALLENGE {nonce.hex()} {proof}\n".encode())
                header = b""
                while not header.endswith(b"\n"):
                    header += conn.recv(1)
                fields = header.decode().split()
                self.assertEqual(fields[:2], ["RP2", "REQUEST"])
                ident, kind, size = int(fields[2]), fields[3], int(fields[4])
                body = b""
                while len(body) < size:
                    body += conn.recv(size - len(body))
                self.assertEqual(fields[5].encode(), rp._mac(key, b"request", nonce, ident, kind, body))
                answer = b"ready"
                mac = rp._mac(key, b"response", nonce, ident, kind, answer)
                if corrupt:
                    mac = b"0" * 64
                conn.sendall(f"RP2 RESPONSE {ident} {kind} {len(answer)} ".encode() + mac + b"\n" + answer)

        for corrupt in (False, True):
            with socket.socket() as listener:
                listener.bind(("127.0.0.1", 0))
                listener.listen(1)
                worker = threading.Thread(target=serve_once, args=(listener, corrupt))
                worker.start()
                try:
                    if corrupt:
                        with self.assertRaises(rp.TransportError):
                            rp.exchange("127.0.0.1", listener.getsockname()[1], token, "sample", "meta")
                    else:
                        self.assertEqual(rp.exchange("127.0.0.1", listener.getsockname()[1], token, "sample", "meta"), b"ready")
                finally:
                    worker.join(timeout=3)
                    self.assertFalse(worker.is_alive())

    def test_browser_and_action_guards(self):
        httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        from urllib.request import Request, urlopen
        from urllib.error import HTTPError
        base = f"http://127.0.0.1:{httpd.server_port}"
        try:
            with urlopen(base + "/") as response:
                self.assertEqual(response.status, 200)
                self.assertIn("img-src 'self' data: blob:", response.headers["Content-Security-Policy"])
            for request in (base + "/api/state", Request(base + "/api/state", headers={
                    "X-Remote-Pilot-Viewer": "1", "Origin": "http://example.invalid"})):
                try:
                    urlopen(request)
                    self.fail("Expected a forbidden response")
                except HTTPError as error:
                    self.assertEqual(error.code, 403)
                    error.close()
            with urlopen(Request(base + "/api/presets", headers={"X-Remote-Pilot-Viewer": "1"})) as response:
                self.assertIn("example", [p["id"] for p in json.load(response)["presets"]])
            selected = server._selected()
            with server.STATE_LOCK:
                server.FRAMES[selected] = (2, "image/bmp", b"BMtest")
            with urlopen(Request(base + "/api/frame?since=2", headers={"X-Remote-Pilot-Viewer": "1"})) as response:
                self.assertEqual(response.status, 204)
            with urlopen(Request(base + "/api/frame?since=1", headers={"X-Remote-Pilot-Viewer": "1"})) as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(response.headers["X-Frame-Version"], "2")
            with self.assertRaises(ValueError):
                server._validate_action("gamepad", {"buttons": 0, "lx": 0, "ly": 0, "rx": 0, "ry": 0, "lt": -1, "rt": 0, "frames": 1})
        finally:
            server.FRAMES.pop(server._selected(), None)
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=3)

    def test_frame_bounds(self):
        body = bytearray(54 + 4 * 8)
        body[:2] = b"BM"
        struct.pack_into("<I", body, 2, len(body))
        struct.pack_into("<I", body, 10, 54)
        struct.pack_into("<ii", body, 18, 2, 4)
        struct.pack_into("<H", body, 28, 24)
        self.assertEqual(server._body_image(bytes(body))[2:], (2, 4))
        with self.assertRaises(ValueError):
            server._body_image(bytes(body[:-1]))

    def test_capture_and_stream_replace_the_current_frame(self):
        first = bytearray(54 + 4 * 8)
        first[:2] = b"BM"
        struct.pack_into("<I", first, 2, len(first))
        struct.pack_into("<I", first, 10, 54)
        struct.pack_into("<ii", first, 18, 2, 4)
        struct.pack_into("<H", first, 28, 24)
        second = bytearray(first)
        second[-1] = 1

        class SyntheticDevice:
            def request(self, kind, payload):
                return bytes(first if kind == "shot" else second)

        manifest = {"id": "synthetic", "display": {"width": 2, "height": 4},
                    "capabilities": ["screenshot", "stream"]}
        server.RUNTIMES["synthetic"] = SyntheticDevice()
        try:
            with patch.object(server, "all_presets", return_value=[manifest]):
                server._work("synthetic", "shot", "-")
                self.assertEqual(server.FRAMES["synthetic"][0], 1)
                self.assertEqual(server.FRAMES["synthetic"][2], bytes(first))
                server._work("synthetic", "stream", "-")
                self.assertEqual(server.FRAMES["synthetic"][0], 2)
                self.assertEqual(server.FRAMES["synthetic"][2], bytes(second))
        finally:
            server.RUNTIMES.pop("synthetic", None)
            server.FRAMES.pop("synthetic", None)


if __name__ == "__main__":
    unittest.main()
