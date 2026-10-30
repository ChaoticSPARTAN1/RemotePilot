"""Local bug reports: written to this computer only, with nothing private."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bug_report  # noqa: E402

MANIFEST = {"id": "psp-homebrew", "name": "PSP · Homebrew (RemotePilot PSP)", "capabilities": ["screenshot", "log"]}
FIELDS = {"what": "Live view froze\r\nafter a sleep", "steps": "1. Sleep\n2. Wake\x07", "expected": ""}


class BugReportTest(unittest.TestCase):
    def test_connected_report_has_screen_and_log(self):
        asked = []

        def request(kind, payload):
            asked.append(kind)
            return b"BM" + bytes(60) if kind == "shot" else "power: the sleep switch works\n"

        with tempfile.TemporaryDirectory() as root:
            status = {"connected": True, "host": "192.0.2.7", "meta": {"label": "RemotePilot PSP", "state": "companion"}}
            result = bug_report.save(root, MANIFEST, status, FIELDS, "TestBrowser/1", request, lambda body: "bmp")
            folder = Path(result["place"])
            self.assertEqual(sorted(result["files"]), ["log.txt", "report.md", "screen.bmp"])
            self.assertEqual(asked, ["shot", "log"])
            text = (folder / "report.md").read_text(encoding="utf-8")
            self.assertIn("Live view froze\nafter a sleep", text)
            self.assertIn("(not filled in)", text)
            self.assertIn("connected, RemotePilot PSP, companion", text)
            self.assertIn("saved on this computer only", text)
            self.assertNotIn("192.0.2.7", text)      # no device address
            self.assertNotIn("\x07", text)           # control characters dropped
            self.assertNotIn("github", text.lower())
            self.assertEqual([item["name"] for item in bug_report.saved(root)], [result["name"]])
            # a second report the same second gets its own folder
            again = bug_report.save(root, MANIFEST, status, FIELDS, "", None)
            self.assertNotEqual(again["name"], result["name"])
            self.assertEqual(again["files"], ["report.md"])

    def test_not_connected_or_failing_device(self):
        def broken(kind, payload):
            raise OSError("no route")

        with tempfile.TemporaryDirectory() as root:
            offline = bug_report.save(root, MANIFEST, {"connected": False}, FIELDS, "", broken)
            self.assertEqual(offline["files"], ["report.md"])
            self.assertIn("wasn't connected", (Path(offline["place"]) / "report.md").read_text(encoding="utf-8"))
            failing = bug_report.save(root, MANIFEST, {"connected": True}, FIELDS, "", broken)
            text = (Path(failing["place"]) / "report.md").read_text(encoding="utf-8")
            self.assertEqual(failing["files"], ["report.md"])
            self.assertIn("couldn't be captured (OSError)", text)
            self.assertIn("couldn't be fetched (OSError)", text)

    def test_clean_bounds_text(self):
        self.assertEqual(len(bug_report.clean("x" * 9000)), bug_report.MAX_FIELD)
        with self.assertRaises(ValueError):
            bug_report.clean(["not text"])


if __name__ == "__main__":
    unittest.main()
