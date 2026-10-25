"""Prepare generated relay artwork for HOME icons/banner and native RGB565 UI."""
from pathlib import Path
import argparse
import shutil
import wave
import struct
from PIL import Image

ROOT = Path(__file__).resolve().parent
parser = argparse.ArgumentParser()
parser.add_argument('--companion-version', type=int, default=11)
parser.add_argument('--updater-version', type=int, default=10)
args = parser.parse_args()
if not all(0 <= v <= 65535 for v in (args.companion_version, args.updater_version)):
    parser.error('Raw title versions must fit an unsigned 16-bit value')
OUT = ROOT / 'build'
OUT.mkdir(exist_ok=True)
with wave.open(str(OUT / 'silent.wav'), 'wb') as output:
    output.setnchannels(1)
    output.setsampwidth(2)
    output.setframerate(22050)
    output.writeframes(b'\0\0' * 22050)
for folder, version in (('build', args.companion_version), ('build-updater', args.updater_version)):
    target = ROOT / folder
    target.mkdir(exist_ok=True)
    prefix = 'recovery' if folder == 'build-updater' else 'relay'
    image = Image.open(ROOT / f'artwork/{prefix}-icon-v1.png').convert('RGB').resize((48, 48), Image.Resampling.LANCZOS)
    image.save(target / 'icon.png')
    banner = Image.open(ROOT / f'artwork/{prefix}-banner-v1.png').convert('RGB').resize((256, 128), Image.Resampling.LANCZOS)
    banner.save(target / 'banner.png')
    native = banner.resize((200, 100), Image.Resampling.LANCZOS)
    (target / 'screen_banner.bin').write_bytes(b''.join(struct.pack('<H', ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3))
                                                     for r, g, b in native.getdata()))
    header = target / 'build_version.hpp'
    content = f'#pragma once\n#define RPH_BUILD_VERSION {version}\n'
    if not header.exists() or header.read_text() != content:
        header.write_text(content)
