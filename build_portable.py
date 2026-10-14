"""Build a deterministic source-only bundle from an explicit safe file list."""

import argparse
import hashlib
import json
from pathlib import Path
import zipfile


ROOT = Path(__file__).resolve().parent
FILES = (
    ".gitignore", "LICENSE", "README.md", "run.cmd", "run.sh", "server.py",
    "presets.py", "plugin_runtime.py", "performance_capture.py", "capture_api.py", "reference_adapter.py",
    "reference_transport.py", "viewer.html", "viewer.css", "device.css", "viewer.js",
    "build_portable.py", "tools/new_preset.py", "presets/example/manifest.json",
    "docs/INTEGRATION.md", "docs/PROTOCOL.md", "docs/SECURITY.md",
    "docs/EXAMPLE_PROMPT.md",
)


def build(output):
    output = Path(output).resolve()
    files = {}
    for name in FILES:
        source = ROOT / name
        if not source.is_file() or source.is_symlink() or not source.resolve().is_relative_to(ROOT):
            raise ValueError(f"Missing or unsafe bundle file: {name}")
        files[name] = source.read_bytes()
    manifest = {"format": 1, "presets": ["example"],
                "files": {name: {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}
                          for name, data in sorted(files.items())}}
    files["bundle-manifest.json"] = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in sorted(files.items()):
            info = zipfile.ZipInfo(f"RemotePilot/{name}", date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = (0o100755 if name == "run.sh" else 0o100644) << 16
            archive.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    temporary.replace(output)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist/RemotePilot-portable.zip")
    args = parser.parse_args()
    output = build(args.output)
    print(f"Portable bundle: {output} ({output.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
