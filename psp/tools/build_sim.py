"""Builds the desktop PSP simulator (psp/device/build/rp2_sim) with the host's C compiler.

    python psp/tools/build_sim.py [--cc gcc]

It compiles the same rp2_device.c, rp2_actions.c and rp2_backup.c the PSP
runs, with platform_host.c in place of the PSP's platform layer."""
import argparse
import os
import subprocess
import sys
from pathlib import Path

DEVICE = Path(__file__).resolve().parents[1] / "device"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cc", default="gcc")
    args = parser.parse_args()
    out = DEVICE / "build" / ("rp2_sim.exe" if os.name == "nt" else "rp2_sim")
    out.parent.mkdir(exist_ok=True)
    sources = [DEVICE / name for name in ("platform_host.c", "rp2_device.c", "rp2_actions.c", "rp2_backup.c", "rp2_restore.c", "rp2_flash_copy.c",
                                          "third_party/sha256_hmac.c")]
    libs = ["-lws2_32", "-lbcrypt"] if os.name == "nt" else []
    command = [args.cc, "-std=c99", "-O2", "-Wall", "-Wextra", "-Werror", "-Wno-unused-parameter",
               "-D_POSIX_C_SOURCE=200809L", "-o", str(out), *map(str, sources), *libs]
    print(" ".join(command))
    return subprocess.call(command)


if __name__ == "__main__":
    sys.exit(main())
