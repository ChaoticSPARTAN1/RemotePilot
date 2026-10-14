import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.request import Request, urlopen
from urllib.error import HTTPError

import performance_capture
from reference_adapter import ReferenceAdapter
from plugin_runtime import PluginRuntime
import server


class PerformanceTests(unittest.TestCase):
    def test_polling_stops_and_restores_without_losing_capture_events(self):
        calls = []
        sequence = 0
        def exchange(_host, _port, _token, _app, kind, **_kwargs):
            calls.append(kind)
            return json.dumps({"schemaVersion": 2, "appId": "sample", "captureSequence": sequence}
                              if kind == "meta" else {"fps": 60, "frameMs": 16.7, "workMs": 10, "timestampMs": 1}).encode()
        with tempfile.TemporaryDirectory() as folder:
            adapter = ReferenceAdapter(folder, {"id": "sample", "capabilities": ["perf"]})
            config = {"token": "0" * 64, "port": 12345}
            events = []
            adapter.set_event_sink(lambda *args: events.append(args))
            with patch("reference_adapter.exchange", exchange):
                adapter._poll("127.0.0.1", config)
                self.assertEqual(calls, ["meta"])
                performance_capture.set_enabled(folder, True)
                adapter._poll("127.0.0.1", config)
                self.assertEqual(calls[-2:], ["meta", "perf"])
                self.assertIsNotNone(adapter.status()["perf"])
                performance_capture.set_enabled(folder, False)
                sequence = 1
                adapter._poll("127.0.0.1", config)
                self.assertEqual(calls, ["meta", "meta", "perf", "meta"])
                self.assertEqual(events, [("capture", 1)])
                self.assertTrue(adapter.status()["connected"])
                self.assertIsNone(adapter.status()["perf"])
                self.assertFalse(ReferenceAdapter(folder, adapter.manifest).performance_enabled())

    def test_api_saves_independent_presets_and_rejects_invalid_values(self):
        httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        worker = threading.Thread(target=httpd.serve_forever, daemon=True)
        worker.start()
        def send(preset, value):
            req = Request(f"http://127.0.0.1:{httpd.server_port}/api/performance",
                          data=json.dumps({"preset": preset, "enabled": value}).encode(),
                          headers={"X-Remote-Pilot-Viewer": "1", "Content-Type": "application/json"})
            with urlopen(req) as response:
                return json.load(response)
        try:
            with tempfile.TemporaryDirectory() as folder, patch.object(server, "LOCAL", Path(folder)), patch.object(server, "all_presets", return_value=[{"id": "one"}, {"id": "two"}]):
                self.assertEqual(send("one", True), {"enabled": True})
                self.assertTrue(performance_capture.enabled(Path(folder) / "one"))
                self.assertFalse(performance_capture.enabled(Path(folder) / "two"))
                self.assertEqual(send("one", False), {"enabled": False})
                for preset, value in [("one", 1), ("one", "false"), ("../escape", True)]:
                    with self.assertRaises(HTTPError) as caught:
                        send(preset, value)
                    self.assertEqual(caught.exception.code, 400)
                    caught.exception.close()
        finally:
            httpd.shutdown()
            httpd.server_close()
            worker.join(timeout=3)

    def test_general_dev_preset_honours_capture_switch(self):
        with tempfile.TemporaryDirectory() as folder:
            runtime = PluginRuntime({"id": "halo3ds", "capabilities": ["perf"]}, server.PRESETS, Path(folder))
            adapter = runtime.adapter
            if adapter is None:
                self.skipTest("Optional Halo3DS preset is not installed")
            class Device:
                perf_calls = 0
                sequence = 0
                def meta(self):
                    return {"bugItSequence": self.sequence, "deviceModel": "new"}
                def perf(self):
                    self.perf_calls += 1
                    return {"fps": 60, "frameMs": 16.7, "workMs": 10, "timestampMs": 1}
            device = Device()
            adapter._client = lambda *_args: device
            events = []
            adapter.set_event_sink(lambda *args: events.append(args))
            adapter._poll("127.0.0.1", {})
            self.assertEqual(device.perf_calls, 0)
            performance_capture.set_enabled(adapter.local_dir, True)
            adapter._poll("127.0.0.1", {})
            self.assertEqual(device.perf_calls, 1)
            performance_capture.set_enabled(adapter.local_dir, False)
            device.sequence = 1
            adapter._poll("127.0.0.1", {})
            self.assertEqual(device.perf_calls, 1)
            self.assertEqual(events, [("capture", 1)])
            self.assertIsNone(adapter.status()["perf"])
