"""Explicit homebrew-v1 action capabilities, separate from every game parser."""
ACTION_CAPABILITIES = {
    "status": "homebrew", "configure": "homebrew", "inspect": "homebrew",
    "download": "upload", "update": "upload", "cancel": "upload", "titles": "titles", "launch": "launch",
    "system-arm": "system-input", "system-input": "system-input", "system-release": "system-input",
}


def runtime(runtimes):
    value = runtimes.get("homebrew")
    if value is None or "homebrew" not in value.capabilities:
        raise ValueError("3DS Homebrew adapter is unavailable")
    return value


def release(runtimes):
    value = runtimes.get("homebrew")
    if value and value.adapter:
        value.adapter.disconnect()
