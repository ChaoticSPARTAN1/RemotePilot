"""Draws RemotePilot PSP's screens on this PC (psp/device/ui/render_screens.c,
the same drawing code the PSP runs) into PNGs and one contact sheet.

    python psp/tools/render_screens.py [--cc gcc] [--out <folder>]

The default output is psp/device/build/screens/ (ignored by git).
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path

from PIL import Image

DEVICE = Path(__file__).resolve().parents[1] / "device"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cc", default="gcc")
    parser.add_argument("--out", default=str(DEVICE / "build" / "screens"))
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    exe = DEVICE / "build" / ("render_screens.exe" if os.name == "nt" else "render_screens")
    sources = [DEVICE / "ui" / name for name in ("render_screens.c", "screens.c", "ui.c", "ui_fonts.c", "ui_backdrop.c")]
    subprocess.run([args.cc, "-std=c99", "-O2", "-Wall", "-Wextra", "-Werror", "-Wno-unused-parameter",
                    "-o", str(exe), *map(str, sources), "-lm"], check=True)
    subprocess.run([str(exe), str(out)], check=True)
    shots = sorted(out.glob("*.ppm"))
    sheet = Image.new("RGB", (2 * 480 + 30, ((len(shots) + 1) // 2) * 282 + 10), (20, 20, 24))
    for k, shot in enumerate(shots):
        image = Image.open(shot)
        image.save(shot.with_suffix(".png"))
        shot.unlink()
        sheet.paste(image, (10 + (k % 2) * 490, 10 + (k // 2) * 282))
    sheet.save(out / "contact-sheet.png")
    print(f"{len(shots)} screens in {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
