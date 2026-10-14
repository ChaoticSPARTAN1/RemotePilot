"""Local viewer and bounded adapter host for portable homebrew QA."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
from pathlib import Path
import re
import sqlite3
import struct
import threading
import time
from urllib.parse import parse_qs, urlsplit
import webbrowser

import capture_api
from plugin_runtime import PluginRuntime
from presets import LOCAL, PRESETS, ROOT, all_presets, public_presets, set_theme_override


CAPTURES = LOCAL / "captures"
DATABASE = LOCAL / "activity.sqlite3"
SELECTION = LOCAL / "selection.json"
STATIC = {"/": ("viewer.html", "text/html; charset=utf-8"),
          "/viewer.js": ("viewer.js", "text/javascript; charset=utf-8"),
          "/viewer.css": ("viewer.css", "text/css; charset=utf-8"),
          "/device.css": ("device.css", "text/css; charset=utf-8"),
          "/docs/INTEGRATION.md": ("docs/INTEGRATION.md", "text/plain; charset=utf-8")}
KINDS = {"console", "input", "gamepad", "touch", "shot", "stream", "report", "log", "perf", "preview"}
CAP_FOR = {"shot": "screenshot", "stream": "stream", "gamepad": "controller"}
MAX_IMAGE = 4 * 1024 * 1024
MAX_TEXT = 65536
MAX_BODY = 8192
DB_LOCK = threading.RLock()
STATE_LOCK = threading.RLock()
EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="remote-pilot")
RUNTIMES = {}
FRAMES = {}
AUDIO = {}
STREAM_BUSY = set()
CONTROL = {}
SETUP_FILES = {}
EVENT_SEEN = {}
SELECTED = None
LINK_ENABLED = True


@contextmanager
def _database():
    LOCAL.mkdir(exist_ok=True)
    db = sqlite3.connect(DATABASE, timeout=10)
    db.execute("CREATE TABLE IF NOT EXISTS tasks (id INTEGER PRIMARY KEY, preset TEXT, kind TEXT, "
               "payload TEXT, state TEXT, result TEXT DEFAULT '', created REAL)")
    capture_api.schema(db)
    try:
        with db:
            yield db
    finally:
        db.close()


def _selected():
    global SELECTED
    with STATE_LOCK:
        if SELECTED is None:
            ids = {item["id"] for item in all_presets()}
            try:
                saved = json.loads(SELECTION.read_text(encoding="utf-8")).get("id")
            except (OSError, ValueError, AttributeError):
                saved = None
            SELECTED = saved if saved in ids else "example"
        return SELECTED


def _manifest():
    return next(item for item in public_presets() if item["id"] == _selected())


def _select(preset):
    global SELECTED
    if preset not in {item["id"] for item in all_presets()}:
        raise ValueError("Unknown preset")
    with STATE_LOCK:
        SELECTED = preset
        FRAMES.clear()
        AUDIO.clear()
        LOCAL.mkdir(exist_ok=True)
        temporary = SELECTION.with_suffix(".tmp")
        temporary.write_text(json.dumps({"id": preset}) + "\n", encoding="utf-8")
        temporary.replace(SELECTION)


def _runtime():
    return RUNTIMES.get(_selected())


def _capable(kind):
    caps = _manifest()["capabilities"]
    return CAP_FOR.get(kind, kind) in caps


def _body_image(body):
    if not isinstance(body, bytes) or not 32 <= len(body) <= MAX_IMAGE:
        raise ValueError("Invalid image size")
    if body.startswith(b"\x89PNG\r\n\x1a\n"):
        if len(body) < 24:
            raise ValueError("Truncated PNG")
        width, height = struct.unpack_from(">II", body, 16)
        mime, extension = "image/png", "png"
    elif body.startswith(b"BM"):
        if len(body) < 54 or struct.unpack_from("<I", body, 2)[0] != len(body):
            raise ValueError("Invalid BMP size")
        width, height = struct.unpack_from("<ii", body, 18)
        bits = struct.unpack_from("<H", body, 28)[0]
        offset = struct.unpack_from("<I", body, 10)[0]
        if bits not in (24, 32) or struct.unpack_from("<I", body, 30)[0] != 0:
            raise ValueError("Unsupported BMP format")
        if offset < 54 or offset + ((width * bits + 31) // 32 * 4) * abs(height) > len(body):
            raise ValueError("Truncated BMP pixels")
        mime, extension = "image/bmp", "bmp"
    else:
        raise ValueError("Adapter must return PNG or uncompressed BMP")
    if not 1 <= width <= 2048 or not 1 <= abs(height) <= 2048:
        raise ValueError("Image dimensions exceed limit")
    return mime, extension, width, abs(height)


def _save_artifact(preset, kind, ident, body, extension):
    CAPTURES.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(body).hexdigest()[:12]
    name = f"{preset}-{kind}-{ident}-{digest}.{extension}"
    path = CAPTURES / name
    if not path.exists():
        path.write_bytes(body)
    return name


def _set_task(ident, state, result, filename=None):
    with DB_LOCK, _database() as db:
        db.execute("UPDATE tasks SET state=?, result=? WHERE id=?", (state, result[:512], ident))
        if filename:
            capture_api.record_file(db, ident, filename)
        capture_api.save_manifests(db, CAPTURES)


def _work(preset, kind, payload, ident=None):
    try:
        runtime = RUNTIMES[preset]
        result = runtime.request(kind, payload)
        audio = b""
        if kind == "stream" and isinstance(result, tuple) and len(result) == 2:
            result, audio = result
            if not isinstance(audio, bytes) or len(audio) > 16384 or len(audio) % 2:
                raise ValueError("Invalid audio chunk")
            if audio and "audio" not in next(item["capabilities"] for item in all_presets() if item["id"] == preset):
                raise ValueError("Adapter returned undeclared audio")
        if kind in ("shot", "stream", "preview"):
            mime, extension, width, height = _body_image(result)
            display = next(item["display"] for item in all_presets() if item["id"] == preset)
            if width * display["height"] != height * display["width"]:
                raise ValueError("Image aspect ratio differs from preset display")
            with STATE_LOCK:
                version = FRAMES.get(preset, (0, None, None))[0] + 1
                FRAMES[preset] = (version, mime, result)
                if audio:
                    count = AUDIO.get(preset, (0, None))[0] + 1
                    AUDIO[preset] = (count, audio)
            if ident is not None:
                filename = _save_artifact(preset, kind, ident, result, extension)
                _set_task(ident, "done", filename, filename)
        elif kind in ("report", "log"):
            if not isinstance(result, str) or len(result.encode("utf-8")) > MAX_TEXT:
                raise ValueError("Invalid diagnostic text")
            if ident is not None:
                filename = _save_artifact(preset, kind, ident, result.encode("utf-8"), "txt")
                _set_task(ident, "done", filename, filename)
        elif ident is not None:
            if isinstance(result, dict):
                result = json.dumps(result, ensure_ascii=False)
            if not isinstance(result, str) or len(result.encode("utf-8")) > 4096:
                raise ValueError("Invalid action result")
            _set_task(ident, "done", result)
    except Exception as exc:
        if ident is not None:
            _set_task(ident, "failed", f"Remote action failed ({type(exc).__name__})")
    finally:
        if kind == "stream":
            with STATE_LOCK:
                STREAM_BUSY.discard(preset)


def _queue(kind, payload):
    preset = _selected()
    if not _runtime() or not LINK_ENABLED or not _capable(kind):
        raise ValueError("Action is unavailable for this preset")
    if kind not in KINDS or kind in ("stream", "gamepad", "touch"):
        raise ValueError("Invalid queued action")
    with DB_LOCK, _database() as db:
        count = db.execute("SELECT count(*) FROM tasks WHERE state IN ('queued','sent')").fetchone()[0]
        if count >= 16:
            raise ValueError("Request queue is full")
        ident = db.execute("INSERT INTO tasks (preset,kind,payload,state,created) VALUES (?,?,?,?,?)",
                           (preset, kind, payload[:128], "sent", time.time())).lastrowid
    EXECUTOR.submit(_work, preset, kind, payload, ident)
    return ident


def _capture(diagnostic):
    preset = _selected()
    if not _runtime() or not LINK_ENABLED or not _capable("shot"):
        raise ValueError("Capture is unavailable")
    if diagnostic not in (None, "report", "log"):
        raise ValueError("Invalid diagnostic choice")
    if diagnostic and not _capable(diagnostic):
        diagnostic = None
    with DB_LOCK, _database() as db:
        capture, items = capture_api.create(db, preset, diagnostic, plugin=True)
        for ident, kind in items:
            db.execute("UPDATE tasks SET preset=?, kind=?, created=? WHERE id=?",
                       (preset, kind, time.time(), ident))
    for ident, kind in items:
        EXECUTOR.submit(_work, preset, kind, "-", ident)
    return capture


def _stream():
    preset = _selected()
    if not _runtime() or not LINK_ENABLED or not _capable("stream"):
        raise ValueError("Live preview is unavailable")
    with STATE_LOCK:
        if preset in STREAM_BUSY:
            return False
        STREAM_BUSY.add(preset)
    EXECUTOR.submit(_work, preset, "stream", "-")
    return True


def _device_event(preset, kind, sequence):
    if kind != "capture" or type(sequence) is not int or not 0 < sequence <= 0xffffffff:
        return
    with STATE_LOCK:
        if preset != _selected() or not LINK_ENABLED or EVENT_SEEN.get(preset) == sequence:
            return
        EVENT_SEEN[preset] = sequence
    try:
        manifest = next(item for item in all_presets() if item["id"] == preset)
        diagnostic = "report" if "report" in manifest["capabilities"] else "log" if "log" in manifest["capabilities"] else None
        _capture(diagnostic)
    except (ValueError, KeyError):
        pass


def _control_worker(preset, kind):
    key = (preset, kind)
    while True:
        with STATE_LOCK:
            pending = CONTROL.get(key)
            if pending is None:
                CONTROL.pop(key, None)
                return
            payload, deadline = pending
            CONTROL[key] = None
        if time.monotonic() > deadline or _selected() != preset or not LINK_ENABLED:
            continue
        try:
            RUNTIMES[preset].request(kind, payload)
        except Exception:
            pass


def _set_control(kind, payload):
    preset = _selected()
    if not _runtime() or not LINK_ENABLED or not _capable(kind):
        raise ValueError("Control is unavailable")
    key = (preset, kind)
    with STATE_LOCK:
        working = key in CONTROL
        CONTROL[key] = (payload, time.monotonic() + 0.5)
    if not working:
        EXECUTOR.submit(_control_worker, preset, kind)


def _state():
    preset = _selected()
    manifest = _manifest()
    runtime = _runtime()
    status = runtime.status() if runtime else {"connected": False, "session": False, "host": "",
                                              "discovery": "Example runs locally", "meta": None, "perf": None}
    with DB_LOCK, _database() as db:
        tasks = [dict(id=i, kind=k, state=s, result=r, created=c) for i, k, s, r, c in db.execute(
            "SELECT id,kind,state,result,created FROM tasks WHERE preset=? ORDER BY id DESC LIMIT 30", (preset,))]
        captures = capture_api.list_bundles(db, preset)
    with STATE_LOCK:
        frame_version = FRAMES.get(preset, (0, None, None))[0]
        audio_version = AUDIO.get(preset, (0, None))[0]
    return {"preset": preset, "manifest": manifest, "linkEnabled": LINK_ENABLED,
            "connected": status["connected"], "session": status["session"],
            "discovery": status["discovery"], "host": status["host"],
            "meta": status["meta"], "perf": status["perf"], "tasks": tasks,
            "captures": captures, "frameVersion": frame_version, "audioVersion": audio_version,
            "setupAvailable": bool(runtime and callable(getattr(runtime.adapter, "setup", None))),
            "manualHostAvailable": bool(runtime and callable(getattr(runtime.adapter, "set_host", None)))}


class Handler(BaseHTTPRequestHandler):
    server_version = "RemotePilot"

    def log_message(self, *_args):
        pass

    def _allowed_host(self):
        host = self.headers.get("Host", "")
        return host in (f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}")

    def _authorized(self):
        if not self._allowed_host() or self.client_address[0] not in ("127.0.0.1", "::1"):
            return False
        origin = self.headers.get("Origin")
        if origin and origin not in (f"http://127.0.0.1:{self.server.server_port}",
                                     f"http://localhost:{self.server.server_port}"):
            return False
        return self.headers.get("X-Remote-Pilot-Viewer") == "1"

    def _send(self, status, body=b"", mime="application/json; charset=utf-8", extra=None):
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' data:; "
                         "style-src 'self'; script-src 'self'; connect-src 'self'; "
                         "object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _json(self, obj, status=200):
        self._send(status, json.dumps(obj, ensure_ascii=False, allow_nan=False).encode("utf-8"))

    def _error(self, status, message):
        self._json({"error": message}, status)

    def do_GET(self):
        if not self._allowed_host():
            return self._error(403, "Invalid host")
        path = urlsplit(self.path)
        if path.path in STATIC:
            name, mime = STATIC[path.path]
            return self._send(200, (ROOT / name).read_bytes(), mime)
        if not self._authorized():
            return self._error(403, "Viewer access denied")
        if path.path == "/api/presets":
            return self._json({"selected": _selected(), "presets": public_presets()})
        if path.path == "/api/state":
            return self._json(_state())
        if path.path == "/api/catalog":
            catalog = PRESETS / _selected() / "catalog.json"
            if not catalog.is_file() or catalog.stat().st_size > 65536:
                return self._json({"groups": []})
            return self._send(200, catalog.read_bytes())
        if path.path == "/api/frame":
            with STATE_LOCK:
                frame = FRAMES.get(_selected())
            if not frame:
                return self._send(204)
            return self._send(200, frame[2], frame[1], {"X-Frame-Version": str(frame[0])})
        if path.path == "/api/audio":
            try:
                since = int(parse_qs(path.query).get("since", ["0"])[0])
            except ValueError:
                return self._error(400, "Invalid audio sequence")
            with STATE_LOCK:
                chunk = AUDIO.get(_selected())
            if not chunk or chunk[0] <= since:
                return self._send(204)
            return self._send(200, chunk[1], "application/octet-stream",
                              {"X-Audio-Sequence": str(chunk[0]),
                               "X-Sample-Rate": str(_manifest().get("audioSampleRate", 16000))})
        if path.path.startswith("/api/artifact/"):
            name = path.path.removeprefix("/api/artifact/")
            if not re.fullmatch(r"[a-zA-Z0-9_.-]{1,160}", name):
                return self._error(400, "Invalid artifact name")
            artifact = CAPTURES / name
            if not artifact.is_file() or artifact.is_symlink():
                return self._error(404, "Artifact not found")
            mime = "image/png" if name.endswith(".png") else "image/bmp" if name.endswith(".bmp") else "text/plain; charset=utf-8" if name.endswith(".txt") else "application/json"
            return self._send(200, artifact.read_bytes(), mime,
                              {"Content-Disposition": f'attachment; filename="{name}"'})
        if path.path == "/api/setup/config":
            preset = _selected()
            config = SETUP_FILES.get(preset)
            if config is None or not config.is_file():
                return self._error(404, "Run setup first")
            return self._send(200, config.read_bytes(), "application/octet-stream",
                              {"Content-Disposition": f'attachment; filename="{config.name}"'})
        return self._error(404, "Not found")

    def do_POST(self):
        global LINK_ENABLED
        if not self._authorized():
            return self._error(403, "Viewer access denied")
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 <= length <= MAX_BODY or self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                raise ValueError("Invalid request body")
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError("Expected JSON object")
            path = urlsplit(self.path).path
            if path == "/api/select":
                _select(data.get("id"))
                return self._json({"selected": _selected()})
            if path == "/api/theme":
                colors = set_theme_override(_selected(), data.get("colors"))
                return self._json({"colors": colors})
            if path == "/api/link":
                if type(data.get("enabled")) is not bool:
                    raise ValueError("Invalid link switch")
                LINK_ENABLED = data["enabled"]
                return self._json({"enabled": LINK_ENABLED})
            if path == "/api/retry":
                if not _runtime():
                    raise ValueError("No device adapter is selected")
                _runtime().retry()
                return self._json({"ok": True})
            if path == "/api/setup":
                runtime = _runtime()
                if not runtime:
                    raise ValueError("Select an installed device preset first")
                result = runtime.setup()
                SETUP_FILES[_selected()] = runtime.adapter_local_dir / result["configFile"]
                return self._json(result)
            if path == "/api/setup/host":
                runtime = _runtime()
                if not runtime:
                    raise ValueError("Select an installed device preset first")
                return self._json({"host": runtime.set_host(data.get("host"))})
            if path == "/api/stream":
                return self._json({"queued": _stream()})
            if path == "/api/capture":
                return self._json({"capture": _capture(data.get("diagnostic"))}, 202)
            if path == "/api/control":
                kind = data.get("kind")
                if kind not in ("gamepad", "touch"):
                    raise ValueError("Invalid control kind")
                payload = _validate_action(kind, data.get("payload"))
                _set_control(kind, payload)
                return self._json({"queued": True}, 202)
            if path == "/api/action":
                kind = data.get("kind")
                if kind not in KINDS or kind in ("stream", "gamepad", "touch"):
                    raise ValueError("Invalid action kind")
                payload = _validate_action(kind, data.get("payload"))
                return self._json({"task": _queue(kind, payload)}, 202)
            return self._error(404, "Not found")
        except (ValueError, KeyError, TypeError):
            return self._error(400, "Invalid or unavailable action")
        except Exception as exc:
            return self._error(500, f"Action failed ({type(exc).__name__})")


def _validate_action(kind, payload):
    if kind == "console":
        if not isinstance(payload, str) or not 1 <= len(payload) <= 127 or any(ord(c) < 32 or ord(c) > 126 for c in payload):
            raise ValueError("Invalid console command")
        return payload
    if kind == "preview":
        if not isinstance(payload, str) or not re.fullmatch(r"[a-zA-Z0-9_:/.-]{1,128}", payload):
            raise ValueError("Invalid preview selection")
        return payload
    if kind == "input":
        if not isinstance(payload, dict) or payload.get("button") not in _manifest().get("buttons", []) or type(payload.get("frames")) is not int or not 1 <= payload["frames"] <= 30:
            raise ValueError("Invalid bounded input")
        return json.dumps(payload, separators=(",", ":"))
    if kind == "gamepad":
        if not isinstance(payload, dict) or type(payload.get("buttons")) is not int or not 0 <= payload["buttons"] <= 65535:
            raise ValueError("Invalid gamepad buttons")
        if any(type(payload.get(name)) not in (int, float) or not math.isfinite(payload[name]) or not -1 <= payload[name] <= 1
               for name in ("lx", "ly", "rx", "ry")) or any(
                   type(payload.get(name)) not in (int, float) or not math.isfinite(payload[name]) or not 0 <= payload[name] <= 1
                   for name in ("lt", "rt")):
            raise ValueError("Invalid gamepad axes")
        if type(payload.get("frames")) is not int or not 1 <= payload["frames"] <= 8:
            raise ValueError("Invalid gamepad hold")
        return json.dumps(payload, separators=(",", ":"))
    if kind == "touch":
        region = _manifest()["display"].get("touch")
        if not region or not isinstance(payload, dict) or type(payload.get("x")) is not int or type(payload.get("y")) is not int or type(payload.get("down")) is not bool:
            raise ValueError("Invalid touch sample")
        if not 0 <= payload["x"] < region["deviceWidth"] or not 0 <= payload["y"] < region["deviceHeight"]:
            raise ValueError("Touch coordinates outside device")
        return json.dumps(payload, separators=(",", ":"))
    if payload not in (None, "-"):
        raise ValueError("Unexpected action payload")
    return "-"


def serve(port=0, open_browser=True):
    LOCAL.mkdir(exist_ok=True)
    with _database():
        pass
    for manifest in all_presets():
        if manifest["transport"] == "python-v1":
            runtime = PluginRuntime(manifest, PRESETS, LOCAL,
                                    active=lambda key=manifest["id"]: _selected() == key and LINK_ENABLED,
                                    on_event=_device_event)
            RUNTIMES[manifest["id"]] = runtime
            threading.Thread(target=runtime.run_forever, daemon=True,
                             name=f"remote-pilot-{manifest['id']}").start()
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{server.server_port}/"
    (LOCAL / "viewer.json").write_text(json.dumps({"url": url}) + "\n", encoding="utf-8")
    print(f"Remote Pilot viewer: {url}", flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever(poll_interval=0.2)
    finally:
        server.server_close()
        for runtime in RUNTIMES.values():
            runtime.stop()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--viewer-port", type=int, default=0,
                        help="local viewer port; 0 chooses an available port automatically")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    if not 0 <= args.viewer_port <= 65535:
        parser.error("viewer port must be between 0 and 65535")
    serve(args.viewer_port, not args.no_browser)


if __name__ == "__main__":
    main()
