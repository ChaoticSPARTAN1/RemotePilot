"""PSP section: the system settings backup, fetched to this computer and checked.

The device's ``backup`` action (psp/device/rp2_backup.c) copies flash1:/ (the
registry and an installed custom theme) into a new ms0:/BACKUP/flash1-<stamp>
folder and answers with its manifest: every file's path, size and SHA-256,
taken from what it read on flash1 and checked against the copy it wrote. Here
each file is fetched over the ``file`` action and must match the manifest
before it is kept, so a copy on this computer is the PSP's settings byte for
byte or isn't kept at all.

A backup holds the PSP's saved Wi-Fi passwords. Copies go to the private
local folder (local/backups, never served by the viewer or put in captures).

    python settings_backup.py <folder>   checks a backup folder copied from the
                                         card by hand (its manifest.json)
"""

import hashlib
import json
from pathlib import Path
import re
import shutil
import sys

DEVICE_ROOT = "ms0:/BACKUP"
NAME = re.compile(r"flash1-\d{8}-\d{6}(-[2-9])?\Z")
PART = re.compile(r"[A-Za-z0-9 _.()+,&-]{1,63}\Z")
MAX_FILES = 256
MAX_FILE = 4 * 1024 * 1024
MAX_TOTAL = 16 * 1024 * 1024
THEME = "vsh/theme/custom_theme.dat"


class BackupError(Exception):
    """Shown to the user as it is: no paths, tokens or addresses."""


# Windows device names, which a path part may not be, with or without an extension
RESERVED = {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$", *(f"COM{n}" for n in range(10)),
            *(f"LPT{n}" for n in range(10))}


def _relative(path):
    if not isinstance(path, str) or len(path) > 120:
        raise BackupError("The manifest has an invalid file path")
    parts = path.split("/")
    if any(not PART.fullmatch(part) or part in (".", "..") or part != part.strip(" ") or part.endswith(".") or
           part.split(".")[0].upper() in RESERVED for part in parts):
        raise BackupError("The manifest has an invalid file path")
    return parts


def check_manifest(manifest):
    """The device's answer, as a dict the rest can trust the shape of."""
    if not isinstance(manifest, dict):
        raise BackupError("The PSP's answer isn't a backup manifest")
    error = manifest.get("error", "")
    if not isinstance(error, str) or len(error) > 80:
        raise BackupError("The PSP's answer isn't a backup manifest")
    folder = manifest.get("folder", "")
    files = manifest.get("files")
    if not isinstance(files, list) or len(files) > MAX_FILES or not isinstance(folder, str):
        raise BackupError("The PSP's answer isn't a backup manifest")
    if not files:
        raise BackupError(f"The PSP couldn't make a backup: {error or 'no files'}")
    if not folder.startswith(DEVICE_ROOT + "/") or not NAME.fullmatch(folder[len(DEVICE_ROOT) + 1:]):
        raise BackupError("The manifest names an unexpected folder")
    seen, total = set(), 0
    for item in files:
        if not isinstance(item, dict) or type(item.get("size")) is not int or not 0 <= item["size"] <= MAX_FILE \
                or not isinstance(item.get("sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", item["sha256"]):
            raise BackupError("The manifest has an invalid entry")
        _relative(item.get("path"))
        if item["path"].lower() in seen:
            raise BackupError("The manifest lists a file twice")
        seen.add(item["path"].lower())
        total += item["size"]
    if total > MAX_TOTAL:
        raise BackupError("The manifest is larger than any PSP's settings")
    failed = manifest.get("failed", 0)
    # the firmware it was made on: the PSP's restore refuses another one's
    firmware, made = manifest.get("firmware", ""), manifest.get("made", "")
    return {"folder": folder, "name": folder[len(DEVICE_ROOT) + 1:], "files": files,
            "failed": failed if type(failed) is int and failed >= 0 else 0, "error": error,
            "firmware": firmware if isinstance(firmware, str) and len(firmware) <= 15 else "",
            "made": made if isinstance(made, str) and len(made) <= 23 else ""}


def summary(manifest, place):
    files = manifest["files"]
    return {"name": manifest["name"], "files": len(files), "bytes": sum(item["size"] for item in files),
            "failed": manifest["failed"], "theme": any(item["path"].lower() == THEME for item in files),
            "checked": True, "place": place}


def fetch(request, local_root, folder=None, progress=lambda step: None):
    """Makes a backup on the device (folder None) or takes one already on its
    card, fetches every file, checks each against the manifest, and keeps it in
    local_root/<name>. request(kind, payload) is the adapter's. Returns the
    summary; raises BackupError when anything doesn't match."""
    local_root = Path(local_root)
    if folder is None:
        progress("The PSP is copying its settings to ms0:/BACKUP")
        manifest = check_manifest(request("backup", "-"))
    else:
        if not isinstance(folder, str) or not folder.startswith(DEVICE_ROOT + "/") or \
                not NAME.fullmatch(folder[len(DEVICE_ROOT) + 1:]):
            raise BackupError("Choose a flash1-… folder in ms0:/BACKUP")
        progress("Reading the backup's manifest on the card")
        try:
            manifest = json.loads(request("file", folder + "/manifest.json"))
        except ValueError:
            raise BackupError("That folder's manifest.json can't be read") from None
        manifest = check_manifest(manifest)
        if manifest["folder"] != folder:
            raise BackupError("That folder's manifest names another folder")
    target = local_root / manifest["name"]
    if target.exists():
        # already here: keep it only if it is this backup
        verify_folder(target, manifest)
        return summary(manifest, str(target))
    local_root.mkdir(parents=True, exist_ok=True)
    partial = local_root / (manifest["name"] + ".partial")
    if partial.exists():
        shutil.rmtree(partial)
    partial.mkdir()
    try:
        for count, item in enumerate(manifest["files"], 1):
            progress(f"Copying file {count} of {len(manifest['files'])} to this computer")
            body = request("file", f"{manifest['folder']}/{item['path']}")
            if not isinstance(body, bytes) or len(body) != item["size"] or \
                    hashlib.sha256(body).hexdigest() != item["sha256"]:
                raise BackupError(f"{item['path']} didn't arrive as the PSP read it; nothing was kept")
            destination = partial.joinpath(*_relative(item["path"]))
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(body)
        # the device's own manifest fields, so the copy can go back on a card and be restored
        keep = {"folder": manifest["folder"], "source": "flash1:/", "made": manifest["made"],
                "firmware": manifest["firmware"], "files": manifest["files"], "failed": manifest["failed"],
                "error": manifest["error"]}
        (partial / "manifest.json").write_text(json.dumps(keep, separators=(",", ":")) + "\n", encoding="ascii")
        progress("Checking the copies on this computer")
        verify_folder(partial, manifest)
        partial.rename(target)
    except BaseException:
        shutil.rmtree(partial, ignore_errors=True)
        raise
    return summary(manifest, str(target))


def verify_folder(path, manifest=None):
    """Every file in the manifest is in path with its size and SHA-256 (the
    folder's own manifest.json when none is given). Returns the manifest."""
    path = Path(path)
    if manifest is None:
        try:
            manifest = check_manifest(json.loads((path / "manifest.json").read_text(encoding="utf-8")))
        except (OSError, ValueError):
            raise BackupError("The folder has no readable manifest.json") from None
    for item in manifest["files"]:
        local = path.joinpath(*_relative(item["path"]))
        if not local.is_file() or local.stat().st_size != item["size"] or \
                hashlib.sha256(local.read_bytes()).hexdigest() != item["sha256"]:
            raise BackupError(f"{item['path']} is missing or differs from the PSP's")
    return manifest


def local_backups(local_root):
    """The backups kept here, newest first, each checked again."""
    found = []
    root = Path(local_root)
    if not root.is_dir():
        return found
    for folder in sorted(root.iterdir(), reverse=True):
        if not folder.is_dir() or not NAME.fullmatch(folder.name):
            continue
        try:
            found.append(summary(verify_folder(folder), str(folder)))
        except BackupError as exc:
            found.append({"name": folder.name, "checked": False, "problem": str(exc), "place": str(folder)})
    return found


def main(argv):
    if len(argv) != 2:
        print("usage: python settings_backup.py <backup folder copied from ms0:/BACKUP>")
        return 2
    try:
        manifest = verify_folder(argv[1])
    except BackupError as exc:
        print(f"NOT OK: {exc}")
        return 1
    result = summary(manifest, argv[1])
    print(f"OK: {result['files']} files, {result['bytes']} bytes, each matches the PSP's; custom theme "
          f"{'included' if result['theme'] else 'not installed'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
