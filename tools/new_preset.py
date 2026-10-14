"""Create an RP2 preset for a homebrew build without embedding pairing details."""

import argparse
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "presets/example/manifest.json"
ADAPTER = "from reference_adapter import ReferenceAdapter\n\n\ndef create_adapter(local_dir, manifest):\n    return ReferenceAdapter(local_dir, manifest)\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--id", required=True, help="lowercase application ID")
    parser.add_argument("--name", required=True, help="viewer label")
    parser.add_argument("--width", required=True, type=int, help="composite frame width")
    parser.add_argument("--height", required=True, type=int, help="composite frame height")
    parser.add_argument("--layout", choices=("screen", "dual-screen"), default="screen",
                        help="viewer presentation; dual-screen splits a stacked frame")
    parser.add_argument("--device-config-path", required=True, help="relative path within the device storage root")
    parser.add_argument("--touch", help="x,y,width,height,deviceWidth,deviceHeight")
    parser.add_argument("--audio-rate", type=int, help="mono PCM16 sample rate, if live audio is available")
    parser.add_argument("--capabilities", default="screenshot",
                        help="comma-separated implemented features; default: screenshot")
    parser.add_argument("--buttons", default="UP,DOWN,LEFT,RIGHT,PRIMARY,SECONDARY,MENU")
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z][a-z0-9-]{1,31}", args.id) or args.id == "example":
        parser.error("Choose a distinct lowercase application ID")
    path = ROOT / "presets" / args.id
    if path.exists():
        parser.error("This preset already exists")
    data = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    capabilities = [value.strip().lower() for value in args.capabilities.split(",") if value.strip()]
    if not capabilities or len(capabilities) != len(set(capabilities)):
        parser.error("Specify each implemented capability once")
    data.update({"id": args.id, "name": args.name, "mark": args.name[:1].upper(), "order": 10,
                 "transport": "python-v1", "capabilities": capabilities,
                 "display": {"width": args.width, "height": args.height, "layout": args.layout},
                 "buttons": [name.strip().upper() for name in args.buttons.split(",") if name.strip()],
                 "setup": {"deviceConfigPath": args.device_config_path}})
    if args.touch:
        try:
            values = [int(item) for item in args.touch.split(",")]
            if len(values) != 6:
                raise ValueError
        except ValueError:
            parser.error("--touch needs six comma-separated integers")
        data["display"]["touch"] = dict(zip(("x", "y", "width", "height", "deviceWidth", "deviceHeight"), values))
        if "touch" not in data["capabilities"]:
            data["capabilities"].append("touch")
    if args.audio_rate:
        data["audioSampleRate"] = args.audio_rate
        for capability in ("stream", "audio"):
            if capability not in data["capabilities"]:
                data["capabilities"].append(capability)
    path.mkdir()
    try:
        (path / "manifest.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        (path / "adapter.py").write_text(ADAPTER, encoding="utf-8")
        from sys import path as sys_path
        sys_path.insert(0, str(ROOT))
        from presets import _manifest
        _manifest(path / "manifest.json")
    except Exception:
        for item in path.iterdir():
            item.unlink()
        path.rmdir()
        raise
    print(f"Preset created: {path}")
    print("Implement RP2 in the homebrew build, restart Remote Pilot, then use Prepare pairing in the viewer.")


if __name__ == "__main__":
    main()
