"""Validate local preset manifests before the viewer or adapter can use them."""

import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parent
PRESETS = ROOT / "presets"
LOCAL = ROOT / "local"
OVERRIDES = LOCAL / "themes.json"
THEME_FIELDS = ("background", "surface", "surface2", "line", "text", "muted", "accent", "accent2", "glow")
CAPABILITIES = {"screenshot", "stream", "audio", "controller", "console", "input",
                "report", "log", "perf", "catalog", "preview", "touch"}
ID = re.compile(r"[a-z][a-z0-9-]{1,31}\Z")
COLOR = re.compile(r"#[0-9a-fA-F]{6}\Z")
BUTTON = re.compile(r"[A-Z][A-Z0-9_]{0,23}\Z")


def _size(value):
    return type(value) is int and 1 <= value <= 2048


def _manifest(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("id"), str) or not ID.fullmatch(data["id"]):
        raise ValueError(f"Invalid preset ID: {path}")
    if data["id"] != path.parent.name or not isinstance(data.get("name"), str) or not 1 <= len(data["name"]) <= 60:
        raise ValueError(f"Invalid preset name: {path}")
    if not isinstance(data.get("mark"), str) or not 1 <= len(data["mark"]) <= 3:
        raise ValueError(f"Invalid preset mark: {path}")
    if type(data.get("order", 100)) is not int:
        raise ValueError(f"Invalid preset order: {path}")
    if data.get("transport") not in ("example-offline", "python-v1"):
        raise ValueError(f"Unsupported transport: {path}")
    if data["transport"] == "python-v1" and not (path.parent / "adapter.py").is_file():
        raise ValueError(f"Adapter missing: {path}")
    if data["transport"] == "example-offline" and data["id"] != "example":
        raise ValueError(f"Offline transport reserved for Example: {path}")
    caps = data.get("capabilities")
    if not isinstance(caps, list) or len(set(caps)) != len(caps) or set(caps) - CAPABILITIES:
        raise ValueError(f"Invalid capabilities: {path}")
    if "audio" in caps and "stream" not in caps:
        raise ValueError(f"Audio requires stream: {path}")
    display = data.get("display")
    if not isinstance(display, dict) or not _size(display.get("width")) or not _size(display.get("height")):
        raise ValueError(f"Invalid display: {path}")
    if display.get("layout", "screen") not in ("screen", "dual-screen"):
        raise ValueError(f"Invalid display layout: {path}")
    touch = display.get("touch")
    if touch is not None:
        if "touch" not in caps or not isinstance(touch, dict):
            raise ValueError(f"Invalid touch region: {path}")
        fields = ("x", "y", "width", "height", "deviceWidth", "deviceHeight")
        if any(type(touch.get(k)) is not int for k in fields) or any(not _size(touch[k]) for k in fields[2:]):
            raise ValueError(f"Invalid touch size: {path}")
        if touch["x"] < 0 or touch["y"] < 0 or touch["x"] + touch["width"] > display["width"] or touch["y"] + touch["height"] > display["height"]:
            raise ValueError(f"Touch region exceeds display: {path}")
    buttons = data.get("buttons", [])
    if not isinstance(buttons, list) or len(buttons) > 32 or len(set(buttons)) != len(buttons) or any(
            not isinstance(item, str) or not BUTTON.fullmatch(item) for item in buttons):
        raise ValueError(f"Invalid button list: {path}")
    theme = data.get("theme")
    if not isinstance(theme, dict) or set(theme) != set(THEME_FIELDS) or any(
            not isinstance(value, str) or not COLOR.fullmatch(value) for value in theme.values()):
        raise ValueError(f"Invalid theme: {path}")
    if "audio" in caps:
        rate = data.get("audioSampleRate")
        if type(rate) is not int or not 8000 <= rate <= 48000:
            raise ValueError(f"Invalid audio sample rate: {path}")
    setup = data.get("setup")
    if setup is not None:
        if not isinstance(setup, dict) or not isinstance(setup.get("deviceConfigPath"), str) or not 1 <= len(setup["deviceConfigPath"]) <= 160:
            raise ValueError(f"Invalid setup information: {path}")
        relative = re.sub(r"^[a-zA-Z][a-zA-Z0-9_-]*:/", "", setup["deviceConfigPath"])
        pieces = relative.split("/")
        if not pieces or any(not re.fullmatch(r"[a-zA-Z0-9_.-]+", part) or part in (".", "..") for part in pieces):
            raise ValueError(f"Unsafe device config path: {path}")
    return data


def all_presets():
    result = [_manifest(path) for path in sorted(PRESETS.glob("*/manifest.json"))]
    if not any(item["id"] == "example" for item in result):
        raise ValueError("Example preset is required")
    return sorted(result, key=lambda item: (item.get("order", 100), item["id"]))


def _overrides():
    if not OVERRIDES.exists():
        return {}
    data = json.loads(OVERRIDES.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or any(not isinstance(v, dict) or any(
            k not in THEME_FIELDS or not isinstance(c, str) or not COLOR.fullmatch(c)
            for k, c in v.items()) for v in data.values()):
        raise ValueError("Invalid local theme overrides")
    return data


def public_presets():
    overrides = _overrides()
    return [{**preset, "theme": {**preset["theme"], **overrides.get(preset["id"], {})}}
            for preset in all_presets()]


def set_theme_override(preset_id, colors):
    if preset_id not in {item["id"] for item in all_presets()}:
        raise ValueError("Unknown preset")
    if not isinstance(colors, dict) or any(k not in THEME_FIELDS or not isinstance(v, str) or not COLOR.fullmatch(v)
                                             for k, v in colors.items()):
        raise ValueError("Invalid theme colors")
    values = _overrides()
    if colors:
        values[preset_id] = colors
    else:
        values.pop(preset_id, None)
    LOCAL.mkdir(exist_ok=True)
    temporary = OVERRIDES.with_suffix(".tmp")
    temporary.write_text(json.dumps(values, indent=2) + "\n", encoding="utf-8")
    temporary.replace(OVERRIDES)
    return values.get(preset_id, {})
