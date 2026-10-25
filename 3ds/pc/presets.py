"""Validated, file-based game presets and user theme overrides."""

import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent
PRESETS = ROOT / "presets"
LOCAL = ROOT / "local"
OVERRIDES = LOCAL / "themes.json"
THEME_FIELDS = ("background", "surface", "surface2", "line", "text", "muted", "accent", "accent2", "glow")
HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
CAPABILITIES = {"screenshot", "stream", "audio", "controller", "console", "input",
                "report", "log", "perf", "catalog", "preview", "touch",
                "diagnostics", "data-transfer", "homebrew", "upload", "install", "titles", "launch", "system-input"}


def all_presets():
    result = []
    for path in sorted(PRESETS.glob("*/manifest.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not re.fullmatch(r"[a-z][a-z0-9-]{1,31}", data.get("id", "")):
            raise ValueError(f"Invalid preset id: {path}")
        if path.parent.name != data["id"] or not isinstance(data.get("name"), str) \
                or not 1 <= len(data["name"]) <= 60 or not isinstance(data.get("mark"), str) \
                or not 1 <= len(data["mark"]) <= 3:
            raise ValueError(f"Invalid preset manifest: {path}")
        if not isinstance(data.get("order", 100), int) or not re.fullmatch(
                r"[a-z][a-z0-9-]{1,31}", data.get("transport", "")):
            raise ValueError(f"Invalid preset transport or order: {path}")
        if data["transport"] == "python-v1" and not (path.parent / "adapter.py").is_file():
            raise ValueError(f"Python transport needs adapter.py: {path}")
        caps = data.get("capabilities")
        if not isinstance(caps, list) or any(cap not in CAPABILITIES for cap in caps) or len(set(caps)) != len(caps):
            raise ValueError(f"Invalid preset capabilities: {path}")
        if "audio" in caps and "stream" not in caps:
            raise ValueError(f"Audio preview requires stream capability: {path}")
        if 'maxLiveAudioBytes' in data and (type(data['maxLiveAudioBytes']) is not int or data['maxLiveAudioBytes'] not in (16384,32768,65536)):
            raise ValueError(f"Invalid preset live audio limit: {path}")
        for field in ("analogInput", "controllerOriginalFull", "remoteReport", "remoteLog", "manualInputRequiresArm"):
            if field in data and type(data[field]) is not bool:
                raise ValueError(f"Invalid preset {field}: {path}")
        if data.get("controllerOriginalFull") and "controller" not in caps:
            raise ValueError(f"Controller model mapping requires controller capability: {path}")
        models = data.get("models")
        if not isinstance(models, list) or not models or any(model not in ("original", "new-xl") for model in models):
            raise ValueError(f"Invalid preset models: {path}")
        if data.get("styleSheet") not in (None, f"/presets/{data['id']}/theme.css"):
            raise ValueError(f"Invalid preset stylesheet: {path}")
        theme = data.get("theme", {})
        if not isinstance(theme, dict) or set(theme) != set(THEME_FIELDS) or any(
                key not in THEME_FIELDS or not isinstance(value, str) or not HEX_COLOR.fullmatch(value)
               for key, value in theme.items()):
            raise ValueError(f"Invalid preset theme: {path}")
        result.append(data)
    return sorted(result, key=lambda preset: (preset.get("order", 100), preset["id"]))


def theme_overrides():
    if not OVERRIDES.exists():
        return {}
    data = json.loads(OVERRIDES.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Invalid local theme overrides")
    if any(not isinstance(colors, dict) or any(key not in THEME_FIELDS
           or not isinstance(value, str) or not HEX_COLOR.fullmatch(value)
           for key, value in colors.items()) for colors in data.values()):
        raise ValueError("Invalid local theme overrides")
    return data


def set_theme_override(preset_id, colors):
    if preset_id not in {preset["id"] for preset in all_presets()}:
        raise ValueError("Unknown preset")
    if not isinstance(colors, dict) or any(key not in THEME_FIELDS or not isinstance(value, str)
                                             or not HEX_COLOR.fullmatch(value) for key, value in colors.items()):
        raise ValueError("Theme colors must be six-digit hex values")
    data = theme_overrides()
    if colors:
        data[preset_id] = colors
    else:
        data.pop(preset_id, None)
    LOCAL.mkdir(parents=True, exist_ok=True)
    temporary = OVERRIDES.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    temporary.replace(OVERRIDES)
    return data.get(preset_id, {})


def public_presets():
    overrides = theme_overrides()
    return [{**preset, "theme": {**preset.get("theme", {}), **overrides.get(preset["id"], {})}}
            for preset in all_presets()]
