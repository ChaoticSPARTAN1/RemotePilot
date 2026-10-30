"""Local bug reports: written to this computer only, never sent anywhere.

A report is a folder in the private local folder (local/bug-reports/), with
report.md (what the user wrote, and what the viewer knows: preset, device
state, browser, time) and, when asked for and the device is connected, its
screen and log. Nothing goes to GitHub or any other service: the user decides
what to do with the folder. No device address, pairing file or token is
written; a device log is the device's own text and should be read before the
folder is shared with anyone.
"""

from datetime import datetime
from pathlib import Path
import re

FIELDS = (("what", "What happened"), ("steps", "Steps to reproduce"), ("expected", "What was expected"))
MAX_FIELD = 4000
NAME = re.compile(r"[a-z0-9-]{1,40}-\d{8}-\d{6}(-\d{1,2})?\Z")


def clean(text, limit=MAX_FIELD):
    """Printable text with line breaks, bounded."""
    if text is None:
        return ""
    if not isinstance(text, str):
        raise ValueError("Report fields must be text")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return "".join(c for c in text if c == "\n" or c == "\t" or ord(c) >= 32)[:limit].strip()


def _folder(root, preset):
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    for attempt in range(1, 100):
        name = f"{preset}-{stamp}" + (f"-{attempt}" if attempt > 1 else "")
        folder = root / name
        try:
            folder.mkdir(parents=True)
            return folder
        except FileExistsError:
            continue
    raise ValueError("No free report name")


def save(root, manifest, status, fields, browser="", request=None, check_image=None):
    """Writes one report. request(kind, payload) is the device adapter's, or
    None for no screen and log. Returns {"name", "place", "files"}."""
    root = Path(root)
    preset = manifest["id"]
    folder = _folder(root, preset)
    meta = status.get("meta") or {}
    files, notes = ["report.md"], []
    if request is not None and status.get("connected"):
        caps = manifest.get("capabilities", [])
        if "screenshot" in caps:
            try:
                image = request("shot", "-")
                extension = check_image(image) if check_image else "bin"
                (folder / f"screen.{extension}").write_bytes(image)
                files.append(f"screen.{extension}")
            except Exception as exc:
                notes.append(f"The screen couldn't be captured ({type(exc).__name__}).")
        diagnostic = "log" if "log" in caps else "report" if "report" in caps else None
        if diagnostic:
            try:
                text = request(diagnostic, "-")
                if not isinstance(text, str):
                    raise ValueError("not text")
                (folder / f"{diagnostic}.txt").write_text(text, encoding="utf-8")
                files.append(f"{diagnostic}.txt")
            except Exception as exc:
                notes.append(f"The device {diagnostic} couldn't be fetched ({type(exc).__name__}).")
    elif request is not None:
        notes.append("The device wasn't connected, so no screen or log is included.")
    lines = [f"# Bug report: {manifest.get('name', preset)}", ""]
    for key, title in FIELDS:
        lines += [f"## {title}", "", clean(fields.get(key)) or "(not filled in)", ""]
    lines += ["## Environment", "",
              f"- Preset: {preset} ({manifest.get('name', '')})",
              f"- Device: {'connected' if status.get('connected') else 'not connected'}"
              + "".join(f", {clean(str(meta[key]), 60)}" for key in ("label", "state") if meta.get(key)),
              f"- Browser: {clean(browser, 300) or 'unknown'}",
              f"- Saved: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
              f"- Files: {', '.join(files)}", ""]
    if notes:
        lines += ["## Notes", ""] + [f"- {note}" for note in notes] + [""]
    lines += ["This report was saved on this computer only; nothing was sent anywhere.",
              "Read the log before sharing this folder, and never add pairing files",
              "(device.cfg, pairing.json, remotepilot.cfg) or settings backups.", ""]
    (folder / "report.md").write_text("\n".join(lines), encoding="utf-8")
    return {"name": folder.name, "place": str(folder), "files": files}


def saved(root):
    """The reports kept here, newest first."""
    root = Path(root)
    if not root.is_dir():
        return []
    return [{"name": folder.name, "place": str(folder),
             "files": sorted(item.name for item in folder.iterdir() if item.is_file())}
            for folder in sorted(root.iterdir(), key=lambda item: item.stat().st_mtime, reverse=True)
            if folder.is_dir() and NAME.fullmatch(folder.name)][:30]
