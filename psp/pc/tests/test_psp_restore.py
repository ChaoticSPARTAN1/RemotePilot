"""The settings restore (psp/device/rp2_restore.c, rp2_flash_copy.c), run by
the desktop simulator's --backup, --check and --restore, as the PSP's own
screen runs them. Build the simulator first: python ../tools/build_sim.py"""
import json
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

SIM = Path(__file__).resolve().parents[2] / "device" / "build" / ("rp2_sim.exe" if os.name == "nt" else "rp2_sim")


@unittest.skipUnless(SIM.exists(), "build the simulator first (psp/tools/build_sim.py)")
class RestoreTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "stick"
        self.root.mkdir()
        self.flash1 = Path(self.temp.name) / "flash1"
        self.settings = {"registry/system.dreg": os.urandom(131072), "registry/system.ireg": os.urandom(14940),
                         "vsh/theme/wallpaper.bmp": os.urandom(302454), "net/http/cookie.dat": os.urandom(900)}
        for name, body in self.settings.items():
            (self.flash1 / name).parent.mkdir(parents=True, exist_ok=True)
            (self.flash1 / name).write_bytes(body)
        manifest = json.loads(self.sim("--backup").stdout)
        self.assertEqual(manifest["firmware"], "6.61")
        self.folder = manifest["folder"]

    def sim(self, *args):
        return subprocess.run([str(SIM), "--root", str(self.root), "--flash1", str(self.flash1), *args],
                              capture_output=True, text=True, timeout=30)

    def report(self, mode):
        out = self.sim(mode, self.folder)
        first = out.stdout.splitlines()[0]
        head = dict(re.findall(r"(\w+)=(\S*)", first.split(" error=")[0]))
        head["error"] = first.split(" error=", 1)[1]
        files = dict(re.findall(r"^file (\S+) state=(\d)", out.stdout, re.M))
        wrote = dict(re.findall(r"^wrote flash1:/(\S+) result=(-?\d)", out.stdout, re.M))
        return out.returncode, head, files, wrote

    def flash(self):
        return {name: (self.flash1 / name).read_bytes() if (self.flash1 / name).exists() else None
                for name in self.settings}

    def test_nothing_to_restore(self):
        code, head, files, wrote = self.report("--check")
        self.assertEqual((code, head["intact"], head["firmware"], head["differ"]), (0, "1", "1", "0"))
        code, head, files, wrote = self.report("--restore")
        self.assertEqual((code, wrote), (0, {}))  # nothing written when nothing differs

    def test_restores_a_reset(self):
        # what a settings reset looks like: new registry, no wallpaper
        (self.flash1 / "registry/system.dreg").write_bytes(os.urandom(131072))
        (self.flash1 / "vsh/theme/wallpaper.bmp").unlink()
        code, head, files, _ = self.report("--check")
        self.assertEqual((code, head["differ"]), (0, "2"))
        self.assertEqual((files["registry/system.dreg"], files["vsh/theme/wallpaper.bmp"],
                          files["registry/system.ireg"]), ("1", "2", "0"))
        code, head, files, wrote = self.report("--restore")
        self.assertEqual(code, 0, head)
        # only what differed, the registry last, each read back the same
        self.assertEqual(list(wrote), ["vsh/theme/wallpaper.bmp", "registry/system.dreg"])
        self.assertEqual(set(wrote.values()), {"0"})
        self.assertEqual(self.flash(), self.settings)
        self.assertEqual(self.report("--check")[1]["differ"], "0")

    def test_damaged_backup_writes_nothing(self):
        (self.flash1 / "registry/system.dreg").write_bytes(b"reset")
        before = self.flash()
        copy = self.root / self.folder[len("ms0:/"):] / "vsh/theme/wallpaper.bmp"
        copy.write_bytes(copy.read_bytes()[:-1] + b"x")
        code, head, _, wrote = self.report("--restore")
        self.assertEqual((code, head["intact"], wrote), (1, "0", {}))
        self.assertIn("differs from its manifest", head["error"])
        self.assertEqual(self.flash(), before)

    def test_other_firmware_refused_unrecorded_allowed(self):
        (self.flash1 / "registry/system.dreg").write_bytes(b"reset")
        manifest_path = self.root / self.folder[len("ms0:/"):] / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest_path.write_text(json.dumps({**manifest, "firmware": "5.00"}, separators=(",", ":")))
        code, head, _, wrote = self.report("--restore")
        self.assertEqual((code, head["firmware"], wrote), (1, "0", {}))
        self.assertEqual((self.flash1 / "registry/system.dreg").read_bytes(), b"reset")
        # a backup from before firmware was recorded (the first ones) may be restored
        del manifest["firmware"]
        manifest_path.write_text(json.dumps(manifest, separators=(",", ":")))
        code, head, _, wrote = self.report("--restore")
        self.assertEqual((code, head["firmware"]), (0, "-1"))
        self.assertEqual(self.flash(), self.settings)

    def test_only_settings_folders_written_and_no_leftovers(self):
        # flash1 has more than settings (fonts, for one): a manifest naming one is
        # refused by the writer itself, and nothing is written
        (self.flash1 / "font").mkdir()
        (self.flash1 / "font/ltn0.pgf").write_bytes(b"font")
        (self.flash1 / "registry/system.dreg").write_bytes(b"reset")
        manifest_path = self.root / self.folder[len("ms0:/"):] / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        copy = self.root / self.folder[len("ms0:/"):] / "font/ltn0.pgf"
        copy.parent.mkdir()
        copy.write_bytes(b"evil")
        import hashlib
        manifest["files"].append({"path": "font/ltn0.pgf", "size": 4, "sha256": hashlib.sha256(b"evil").hexdigest()})
        manifest_path.write_text(json.dumps(manifest, separators=(",", ":")))
        code, head, _, wrote = self.report("--restore")
        self.assertEqual(code, 1)
        self.assertEqual((self.flash1 / "font/ltn0.pgf").read_bytes(), b"font")
        self.assertEqual((self.flash1 / "registry/system.dreg").read_bytes(), b"reset")
        self.assertIn("-1", wrote.values())  # the job refused whole
        # and a good restore leaves no temporary files behind
        manifest["files"].pop()
        manifest_path.write_text(json.dumps(manifest, separators=(",", ":")))
        self.assertEqual(self.report("--restore")[0], 0)
        self.assertEqual(list(self.flash1.rglob("*.rpnew")), [])
        self.assertEqual(self.flash()["registry/system.dreg"], self.settings["registry/system.dreg"])

    def test_manifest_paths_outside_flash1_refused(self):
        manifest_path = self.root / self.folder[len("ms0:/"):] / "manifest.json"
        text = manifest_path.read_text().replace('"path":"net/http/cookie.dat"', '"path":"../flash0/kd/x.prx"')
        manifest_path.write_text(text)
        code, head, _, wrote = self.report("--restore")
        self.assertEqual((code, wrote), (1, {}))
        self.assertIn("isn't one RemotePilot wrote", head["error"])


if __name__ == "__main__":
    unittest.main()
