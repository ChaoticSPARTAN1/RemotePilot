#!/usr/bin/env python3
"""Private, opt-in LAN QA viewer and device receiver. Python standard library only."""

import argparse
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import closing, nullcontext
import hashlib
import hmac
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import secrets
import socket
import sqlite3
import struct
import sys
import threading
import time
import zlib
from urllib.parse import parse_qs
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from presets import public_presets, set_theme_override, PRESETS
from plugin_runtime import PluginRuntime
import legacy_transport as legacy
import capture_api
import touch_api
import telemetry_api
import performance_capture
import homebrew_api

HERE = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
LOCAL = (Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else HERE) / "local"
SECRET = LOCAL / "token"
DB = LOCAL / "queue.sqlite3"
CAPTURES = LOCAL / "captures"
CONFIG = LOCAL / "receiver.cfg"
LAST_DEVICE = LOCAL / "last-device.json"
SELECTED_PRESET = LOCAL / "selected-preset.json"
MAX_REPORT = 65536
MAX_SHOT = 600000
MAX_STREAM = 180000
KEYS = {
    "A": 0, "B": 1, "SELECT": 2, "START": 3, "RIGHT": 4, "LEFT": 5, "UP": 6,
    "DOWN": 7, "R": 8, "L": 9, "X": 10, "Y": 11, "ZL": 14, "ZR": 15,
}
last_device_contact = 0.0
live_lock = threading.Lock()
live_frame = b""
live_version = 0
live_audio = b""
live_audio_version = 0
device_perf = None
device_perf_at = 0.0
live_audio_chunks = deque(maxlen=32)
stream_transfer_ms = deque(maxlen=30)
stream_stage_ms = deque(maxlen=30)
pad_payload = ""
pad_revision = 0
pad_delivered = 0
pad_updated = 0.0
touch_payload = ''
touch_revision = 0
touch_delivered = 0
touch_updated = 0.0
last_live_input = 'touch'
stream_pending = False
stream_requested = 0.0
perf_pending = False
perf_requested = 0.0
last_aux = ""
link_enabled = True
reverse_stage = "idle"
discovery_status = "idle"
retry_generation = 0
paired_device_host = ""
viewer_pin = ""
viewer_sessions = {}
viewer_attempts = {}
viewer_auth_lock = threading.Lock()
selection_lock = threading.Lock()
selected_preset = None
plugin_runtimes = {}
plugin_frames = {}
plugin_versions = {}
plugin_audio_chunks = {}
plugin_audio_versions = {}
plugin_stream_busy = set()
plugin_stream_errors = {}
plugin_input_arms = {}
plugin_pad_states = {}
plugin_pad_errors = {}


def current_preset():
    global selected_preset
    with selection_lock:
        if selected_preset is None:
            ids = [preset["id"] for preset in public_presets()]
            saved = ""
            try:
                saved = json.loads(SELECTED_PRESET.read_text(encoding="utf-8"))["id"]
            except (OSError, ValueError, KeyError):
                pass
            selected_preset = saved if saved in ids else ids[0]
        return selected_preset


def select_preset(preset_id):
    global selected_preset, pad_delivered, touch_delivered, stream_pending
    if preset_id not in {preset["id"] for preset in public_presets()}:
        raise ValueError("Unknown preset")
    homebrew_api.release(plugin_runtimes)
    with selection_lock:
        selected_preset = preset_id
        local()
        temporary = SELECTED_PRESET.with_suffix(".tmp")
        temporary.write_text(json.dumps({"id": preset_id}) + "\n", encoding="utf-8")
        temporary.replace(SELECTED_PRESET)
    with live_lock:
        plugin_input_arms.clear()
        pad_delivered = pad_revision
        touch_delivered = touch_revision
        stream_pending = False
        for state in plugin_pad_states.values():
            state['delivered'] = state['revision']
    return preset_id


def active_plugin():
    return plugin_runtimes.get(current_preset())


def plugin_poll_active(preset_id):
    # Halo's top-screen badge reflects recent authenticated PC traffic. Stop
    # those polls when the viewer disconnects so the badge can leave LIVE.
    return current_preset() == preset_id and (preset_id not in ("halo", "waw-zombies-3ds", "homebrew") or link_enabled)


def plugin_audio_limit(preset_id):
    manifest=next((item for item in public_presets() if item['id']==preset_id),{})
    return manifest.get('maxLiveAudioBytes',16384)


def input_arm_required(preset_id):
    return next((p for p in public_presets() if p['id']==preset_id),{}).get('manualInputRequiresArm',False)


def require_input_arm(preset_id, owner):
    if not input_arm_required(preset_id):return
    with live_lock:
        lease=plugin_input_arms.get(preset_id)
        valid=bool(link_enabled and lease and lease[0]==owner and time.monotonic()<lease[1])
    if not valid:raise ValueError('Enable remote controls in this focused tab before sending WaW input')


def set_input_arm(preset_id, data):
    if not input_arm_required(preset_id):raise ValueError('This preset does not use manual input arming')
    owner=data.get('owner');enabled=data.get('enabled')
    if not isinstance(owner,str) or not re.fullmatch('[0-9a-f]{32}',owner) or type(enabled) is not bool:
        raise ValueError('Invalid control lease')
    runtime=plugin_runtimes.get(preset_id)
    if enabled and (not link_enabled or not runtime or not runtime.status()['connected'] or not runtime.status()['session']):
        raise ValueError('Connect the device before enabling remote controls')
    with live_lock:
        prior=plugin_input_arms.get(preset_id)
        if enabled:
            if prior and prior[0]!=owner and time.monotonic()<prior[1]:raise ValueError('Another tab has remote controls enabled')
            plugin_input_arms[preset_id]=(owner,time.monotonic()+1.5)
        elif prior and prior[0]==owner:plugin_input_arms.pop(preset_id,None)
    return {'armed':enabled}


def plugin_action(preset_id, kind, payload, ident, input_owner=None):
    """Run one local adapter request with the same capture and queue limits."""
    try:
        if kind=='input':require_input_arm(preset_id,input_owner)
        result = plugin_runtimes[preset_id].request(kind, payload)
        if kind in ("shot", "stream", "preview"):
            audio = b""
            if kind == "stream" and isinstance(result, tuple) and len(result) == 2:
                result, audio = result
                if not isinstance(audio, bytes) or len(audio) > plugin_audio_limit(preset_id) or len(audio) % 2:
                    raise ValueError("Adapter returned invalid live audio")
            image_kind = "shot" if kind == "preview" else kind
            if not isinstance(result, bytes) or not valid_bmp(image_kind, result):
                raise ValueError("Adapter returned an invalid stacked screen image")
            if kind != "stream":
                local()
                digest = hashlib.sha256(result).hexdigest()[:16]
                destination = CAPTURES / f"{preset_id}-shot-{ident}-{digest}.bmp"
                destination.write_bytes(result)
                with closing(database()) as db, db:
                    capture_api.record_file(db, ident, destination.name)
                result = f"{'3D preview' if kind == 'preview' else 'Screen capture'} saved: {destination.name}"
            else:
                with live_lock:
                    plugin_frames[preset_id] = result
                    plugin_versions[preset_id] = plugin_versions.get(preset_id, 0) + 1
                    plugin_stream_errors.pop(preset_id, None)
                    if audio:
                        version = plugin_audio_versions.get(preset_id, 0) + 1
                        plugin_audio_versions[preset_id] = version
                        plugin_audio_chunks.setdefault(preset_id, deque(maxlen=32)).append((version, audio))
                result = "Preview updated"
        elif kind in ("report", "log"):
            if not isinstance(result, str) or len(result.encode("utf-8")) > MAX_REPORT:
                raise ValueError("Adapter returned an invalid diagnostic report")
            local()
            body = result.encode("utf-8")
            digest = hashlib.sha256(body).hexdigest()[:16]
            destination = CAPTURES / f"{preset_id}-{kind}-{ident}-{digest}.txt"
            if body:
                destination.write_bytes(body)
                with closing(database()) as db, db:
                    capture_api.record_file(db, ident, destination.name)
                result = f"{kind.title()} saved: {destination.name}"
            else:
                result = 'Build logs unavailable'
        elif not isinstance(result, str) or len(result.encode("utf-8")) > 4096:
            raise ValueError("Adapter returned an invalid action result")
        if ident:
            with closing(database()) as db, db:
                db.execute("UPDATE tasks SET state='done', result=? WHERE id=?", (result[:4096], ident))
    except Exception as exc:
        if kind == 'stream':
            with live_lock:plugin_stream_errors[preset_id] = str(exc)[:160]
        if ident:
            with closing(database()) as db, db:
                db.execute("UPDATE tasks SET state='failed', result=? WHERE id=?",
                           (f"{type(exc).__name__}: {exc}"[:300], ident))
    finally:
        if ident:
            with closing(database()) as db, db:
                capture_api.save_manifests(db, CAPTURES)
        if kind == "stream":
            with live_lock:
                plugin_stream_busy.discard(preset_id)


def plugin_event(preset_id, kind, sequence):
    """Convert an authenticated in-game Bug It press into visible local tasks."""
    if kind != "bug-it" or type(sequence) is not int or sequence <= 0 or \
            preset_id != current_preset() or not link_enabled:
        return

    def collect():
        # The device poll can observe the event just before PluginRuntime has
        # published its connected status. Give that status a bounded moment to
        # catch up without stalling subsequent device polls.
        for _ in range(8):
            try:
                request_capture(preset_id, diagnostic='report')
                return
            except ValueError:
                if preset_id != current_preset() or not link_enabled:
                    return
                time.sleep(0.5)

    threading.Thread(target=collect, daemon=True).start()


def request_capture(preset_id=None, diagnostic=None):
    """The same capture API and artifact grouping serve both bundled games."""
    preset_id = preset_id or current_preset()
    if preset_id == 'example':
        raise ValueError('Example is a local preview with no device connection')
    if preset_id != current_preset() or not link_enabled:
        raise ValueError("PC link is disconnected")
    runtime = plugin_runtimes.get(preset_id)
    if runtime:
        status = runtime.status()
        if not status['connected'] or not status['session']:
            raise ValueError('Paired device is not connected')
    elif not receiver_on() or (reverse_mode() and not device_connected()):
        raise ValueError('Paired device is not connected')
    manifest = next(item for item in public_presets() if item['id'] == preset_id)
    diagnostic = diagnostic or ('log' if runtime and manifest.get('remoteLog') else 'report' if manifest.get('remoteReport') else None)
    with closing(database()) as db, db:
        for bundle in capture_api.list_bundles(db, preset_id):
            if any(item['state'] in ('queued', 'sent') for item in bundle['items']):
                return {'capture': bundle['id'], 'id': bundle['items'][0]['task'],
                        'tasks': [item['task'] for item in bundle['items']]}
        capture, items = capture_api.create(db, preset_id, diagnostic, plugin=bool(runtime))
        capture_api.save_manifests(db, CAPTURES)
    if runtime:
        def collect():
            for ident, kind in items:
                plugin_action(preset_id, kind, '-', ident)
        threading.Thread(target=collect, daemon=True).start()
    return {'capture': capture, 'id': items[0][0], 'tasks': [ident for ident, kind in items]}


def capture_bundles(preset):
    with closing(database()) as db, db:
        capture_api.save_manifests(db, CAPTURES)
        return capture_api.list_bundles(db, preset)


def plugin_enqueue(kind, payload, input_owner=None):
    preset_id = current_preset()
    runtime = plugin_runtimes.get(preset_id)
    if not runtime or not runtime.status()["connected"] or not runtime.status()["session"] or not link_enabled:
        raise ValueError("Paired device is not connected")
    capability = "screenshot" if kind == "shot" else kind
    manifest = next((item for item in public_presets() if item["id"] == preset_id), None)
    if not manifest or capability not in manifest["capabilities"]:
        raise ValueError("Action is unavailable for this preset")
    if kind=='input':require_input_arm(preset_id,input_owner)
    with closing(database()) as db, db:
        pending = db.execute("SELECT count(*) FROM tasks WHERE state IN ('queued', 'sent')").fetchone()[0]
        if pending >= 16:
            raise ValueError("Queue full; wait for the device")
        cur = db.execute("INSERT INTO tasks (kind, payload, state) VALUES (?, ?, 'sent')",
                         (f"plugin:{preset_id}:{kind}", payload))
        ident = cur.lastrowid
    threading.Thread(target=plugin_action, args=(preset_id, kind, payload, ident, input_owner), daemon=True).start()
    return ident


def plugin_request_stream():
    preset_id = current_preset()
    runtime = plugin_runtimes.get(preset_id)
    if not runtime or not runtime.status()["connected"] or not runtime.status()["session"] or not link_enabled:
        raise ValueError("Paired device is not connected")
    manifest = next((item for item in public_presets() if item["id"] == preset_id), None)
    if not manifest or "stream" not in manifest["capabilities"]:
        raise ValueError("Preview is unavailable for this preset")
    with live_lock:
        if preset_id in plugin_stream_busy:
            return
        plugin_stream_busy.add(preset_id)
    threading.Thread(target=plugin_action, args=(preset_id, "stream", "-", 0), daemon=True).start()


def encode_gamepad(data):
    """One complete standard controller snapshot, with quantized axes."""
    mask = data.get("padMask")
    frames = data.get("frames", 8)
    if type(mask) is not int or not 0 <= mask <= 0xffff:
        raise ValueError("Controller button mask must be 0..65535")
    if type(frames) is not int or not 1 <= frames <= 30:
        raise ValueError("Controller frames must be 1..30")
    values = []
    for key in ("moveX", "moveY", "lookX", "lookY", "lt", "rt"):
        value = data.get(key, 0)
        minimum = 0 if key in ("lt", "rt") else -1
        if isinstance(value, bool) or not isinstance(value, (int, float)) \
                or not math.isfinite(value) or not minimum <= value <= 1:
            raise ValueError(f"Invalid controller {key}")
        values.append(round(value * 1000))
    lx, ly, rx, ry, lt, rt = values
    return (f"buttons={mask:04x},lx={lx},ly={ly},rx={rx},ry={ry},"
            f"lt={lt},rt={rt},frames={frames}")


def plugin_pad_worker(preset_id, kind='gamepad', key=None):
    """Send only the freshest controller state, never retry a gameplay action."""
    key = key or preset_id
    while True:
        with live_lock:
            state = plugin_pad_states[key]
            if state["delivered"] == state["revision"] or time.monotonic() - state["updated"] > .3 \
                    or current_preset() != preset_id or not link_enabled:
                state["busy"] = False
                return
            revision, payload = state["revision"], state["payload"]
        try:
            result = plugin_runtimes[preset_id].request(kind, payload)
            if not isinstance(result, str) or len(result) > 80:
                raise ValueError("Invalid controller acknowledgment")
            plugin_pad_errors[preset_id] = ""
        except Exception as exc:
            plugin_pad_errors[preset_id] = f"{type(exc).__name__}: {exc}"[:160]
        with live_lock:
            state["delivered"] = max(state["delivered"], revision)


def plugin_set_gamepad(data, kind='gamepad'):
    preset_id = current_preset()
    manifest = next((item for item in public_presets() if item["id"] == preset_id), None)
    runtime = plugin_runtimes.get(preset_id)
    capability = 'touch' if kind == 'touch' else 'controller'
    if not manifest or capability not in manifest["capabilities"]:
        raise ValueError("Controller bridge is unavailable for this preset")
    if not runtime or not runtime.status()["connected"] or not runtime.status()["session"] or not link_enabled:
        raise ValueError("Paired device is not connected")
    payload = touch_api.encode_sample(data) if kind == 'touch' else encode_gamepad(data)
    key = preset_id + ':touch' if kind == 'touch' else preset_id
    with live_lock:
        state = plugin_pad_states.setdefault(key, {
            "payload": "", "revision": 0, "delivered": 0, "updated": 0.0, "busy": False})
        state["payload"] = payload
        state["revision"] += 1
        state["updated"] = time.monotonic()
        start = not state["busy"]
        state["busy"] = True
    if start:
        threading.Thread(target=plugin_pad_worker, args=(preset_id, kind, key), daemon=True).start()


def active_transport_preset():
    return next((preset["id"] for preset in public_presets()
                 if preset.get("transport") == "legacy-reverse-v1"), None)


def selected_device_connected():
    return current_preset() == active_transport_preset() and device_connected()


class ReverseLink:
    """Keep one authenticated socket for disposable preview and idle polls."""

    def __init__(self):
        self.conn = None
        self.nonce = None
        self.sequence = 0

    def close(self):
        if self.conn is not None:
            self.conn.close()
        self.conn = None
        self.nonce = None
        self.sequence = 0


def valid_bmp(kind, body):
    """Accept only the two exact uncompressed formats generated by the game."""
    width, height = (400, 480) if kind == "shot" else (200, 240)
    expected = 54 + width * height * 3
    if len(body) != expected or body[:2] != b"BM":
        return False
    return (struct.unpack_from("<I", body, 2)[0] == expected
            and struct.unpack_from("<I", body, 10)[0] == 54
            and struct.unpack_from("<I", body, 14)[0] == 40
            and struct.unpack_from("<II", body, 18) == (width, height)
            and struct.unpack_from("<HH", body, 26) == (1, 24)
            and struct.unpack_from("<I", body, 30)[0] == 0
            and struct.unpack_from("<I", body, 34)[0] == width * height * 3)


def decode_stream(kind, body):
    """Bound decompression to one preview frame before handing it to the viewer."""
    if kind == "streamav":
        if len(body) < 12 or body[:4] != b"MWAV":
            return None
        frame_size, samples = struct.unpack_from("<II", body, 4)
        if not 8 <= frame_size <= MAX_STREAM or samples > 8192 \
                or len(body) != 12 + frame_size + samples * 2:
            return None
        return decode_stream("streamz", body[12:12 + frame_size])
    if kind == "stream":
        return body if valid_bmp("stream", body) else None
    if kind != "streamz" or len(body) < 10 or body[:4] not in (b"MWZ1", b"MWZ2"):
        return None
    rgb565 = body[:4] == b"MWZ2"
    expected = 200 * 240 * 2 if rgb565 else 54 + 200 * 240 * 3
    if struct.unpack_from("<I", body, 4)[0] != expected:
        return None
    try:
        decoder = zlib.decompressobj()
        frame = decoder.decompress(body[8:], expected + 1)
    except zlib.error:
        return None
    if len(frame) != expected or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
        return None
    if rgb565:
        bmp = bytearray(54 + 200 * 240 * 3)
        bmp[:2] = b"BM"
        struct.pack_into("<I", bmp, 2, len(bmp))
        struct.pack_into("<I", bmp, 10, 54)
        struct.pack_into("<I", bmp, 14, 40)
        struct.pack_into("<II", bmp, 18, 200, 240)
        struct.pack_into("<HH", bmp, 26, 1, 24)
        struct.pack_into("<I", bmp, 34, len(bmp) - 54)
        for i, (color,) in enumerate(struct.iter_unpack("<H", frame)):
            offset = 54 + i * 3
            bmp[offset] = (color & 31) << 3
            bmp[offset + 1] = ((color >> 5) & 63) << 2
            bmp[offset + 2] = ((color >> 11) & 31) << 3
        frame = bytes(bmp)
    return frame if valid_bmp("stream", frame) else None


def decode_audio(kind, body):
    if kind != "streamav":
        return b""
    frame_size, samples = struct.unpack_from("<II", body, 4)
    return body[12 + frame_size:12 + frame_size + samples * 2]


def next_live_action():
    """Keep only the newest controller state and one pending preview frame."""
    global pad_delivered, touch_delivered, stream_pending, last_aux, last_live_input, perf_pending
    with live_lock:
        now = time.monotonic()
        if perf_pending:
            perf_pending = False
            if now - perf_requested < 2.5:
                last_aux = 'perf'
                return b'0\nperf\n-\n'
        pad_ready = pad_revision > pad_delivered and now - pad_updated < 1.5
        touch_ready = touch_revision > touch_delivered and now - touch_updated < 1.5
        frame_ready = stream_pending and now - stream_requested < 2.5
        if frame_ready and last_aux in ('pad', 'touch'):
            stream_pending = False
            last_aux = "stream"
            return b"0\nstream\n-\n"
        if touch_ready and (not pad_ready or last_live_input != 'touch'):
            touch_delivered = touch_revision
            last_live_input = last_aux = 'touch'
            return f'0\ntouch\n{touch_payload}\n'.encode('ascii')
        if pad_ready:
            pad_delivered = pad_revision
            last_live_input = last_aux = "pad"
            return f"0\npad\n{pad_payload}\n".encode("ascii")
        if frame_ready:
            stream_pending = False
            last_aux = 'stream'
            return b'0\nstream\n-\n'
    return b"0\nnone\n\n"


def local():
    LOCAL.mkdir(mode=0o700, parents=True, exist_ok=True)
    CAPTURES.mkdir(mode=0o700, exist_ok=True)
    try:
        os.chmod(LOCAL, 0o700)
        os.chmod(CAPTURES, 0o700)
    except OSError:
        pass


def database():
    local()
    db = sqlite3.connect(DB, timeout=10)
    db.execute("CREATE TABLE IF NOT EXISTS tasks (id INTEGER PRIMARY KEY, kind TEXT NOT NULL, payload TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'queued', result TEXT NOT NULL DEFAULT '')")
    db.commit()
    return db


def private_host(host):
    addr = ipaddress.ip_address(host)
    if addr.version != 4 or not (addr in ipaddress.ip_network("10.0.0.0/8")
            or addr in ipaddress.ip_network("172.16.0.0/12")
            or addr in ipaddress.ip_network("192.168.0.0/16")):
        raise ValueError("Host must be this PC's private IPv4 address")
    return str(addr)


def local_pc_host():
    for host in socket.gethostbyname_ex(socket.gethostname())[2]:
        try:
            return private_host(host)
        except ValueError:
            pass
    raise ValueError("No private PC IPv4 address found; pass --pc-host")


def serving_pc_host(explicit, configured, reverse, offline_ok=False):
    """Use the current PC's LAN in reverse mode; the SD config may be from another PC."""
    if explicit:
        return private_host(explicit)
    if reverse or not configured:
        try:
            return local_pc_host()
        except ValueError:
            if offline_ok:
                return None
            raise
    return private_host(configured)


def refresh_network_adapters(host):
    """Keep game adapters on the current private LAN when a laptop changes networks."""
    for runtime in plugin_runtimes.values():
        runtime.set_network_host(host)


def paired_challenge(host, port, token, timeout=0.8):
    """Identify a paired device without sending it a command or disclosing the key."""
    with socket.create_connection((host, port), timeout=timeout) as conn:
        conn.settimeout(timeout)
        conn.sendall(legacy.HELLO)
        line = bytearray()
        while len(line) < 128:
            part = conn.recv(1)
            if not part:
                return False
            line += part
            if part == b"\n":
                break
        parts = bytes(line).strip().split(b" ")
        if len(parts) != 4 or tuple(parts[:2]) != legacy.CHALLENGE_PREFIX:
            return False
        try:
            nonce = bytes.fromhex(parts[2].decode("ascii"))
            proof = bytes.fromhex(parts[3].decode("ascii"))
        except (ValueError, UnicodeDecodeError):
            return False
        if len(nonce) != 16 or len(proof) != 32:
            return False
        expected = hmac.new(bytes.fromhex(token), nonce + b"server\n", hashlib.sha256).digest()
        return hmac.compare_digest(proof, expected)


def discover_paired_host(pc_host, port, token, subnet=None):
    """Search one bounded private LAN subnet for the paired device."""
    global discovery_status, paired_device_host
    if len(token) != 64 or any(c not in "0123456789abcdef" for c in token):
        raise ValueError("Invalid private pairing token")
    network = ipaddress.ip_network(subnet or f"{private_host(pc_host)}/24", strict=False)
    if not network.is_private or network.num_addresses > 1024:
        raise ValueError("Discovery is limited to a private subnet of at most 1024 addresses")
    discovery_status = "scanning"
    candidates = []
    if LAST_DEVICE.exists():
        try:
            cached = json.loads(LAST_DEVICE.read_text(encoding="utf-8"))["host"]
            if ipaddress.ip_address(cached) in network:
                candidates.append(cached)
        except (OSError, ValueError, KeyError):
            pass
    for cached in candidates:
        try:
            if paired_challenge(cached, port, token):
                paired_device_host = cached
                discovery_status = "paired"
                return cached
        except OSError:
            pass
    hosts = [str(ip) for ip in network.hosts() if str(ip) != pc_host and str(ip) not in candidates]
    def probe(host):
        try:
            return host if paired_challenge(host, port, token) else None
        except OSError:
            return None
    pool = ThreadPoolExecutor(max_workers=48)
    try:
        futures = [pool.submit(probe, host) for host in hosts]
        for future in as_completed(futures):
            found = future.result()
            if found:
                paired_device_host = found
                discovery_status = "paired"
                LAST_DEVICE.write_text(json.dumps({"host": found}) + "\n", encoding="utf-8")
                return found
    finally:
        # A match should connect at once; slower probes for other LAN addresses
        # need not hold the discovered connection open until they time out.
        pool.shutdown(wait=False, cancel_futures=True)
    paired_device_host = ""
    discovery_status = "waiting"
    return None


def setup(host, port, session=False, reverse=False):
    host = private_host(host)
    if reverse and not session:
        raise ValueError("PC-initiated mode requires an explicitly armed --session")
    if not 1024 <= port <= 65535:
        raise ValueError("Port must be 1024..65535")
    local()
    if not SECRET.exists():
        SECRET.write_text(secrets.token_hex(32), encoding="ascii")
        try:
            os.chmod(SECRET, 0o600)
        except OSError:
            pass
    token = SECRET.read_text(encoding="ascii").strip()
    CONFIG.write_text(f"host={host}\nport={port}\ntoken={token}\nsession={'on' if session else 'off'}\n"
                      + ("mode=reverse\n" if reverse else ""), encoding="ascii")
    try:
        os.chmod(CONFIG, 0o600)
    except OSError:
        pass
    with closing(database()) as db, db:
        db.execute("UPDATE tasks SET state='cancelled' WHERE state IN ('queued', 'sent')")
    print(f"Private SD config: {CONFIG}")
    print(f"Copy it to {legacy.SD_CONFIG}. Never commit it or share the token.")
    print("Remote commands are " + ("ON" if session else "OFF")
          + ("; PC-initiated transfer needs this armed session." if reverse
             else "; manual Bug It transfer works in either mode."))


class Receiver(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"
    server_version = "RemotePilot/1"

    def setup(self):
        super().setup()
        self.connection.settimeout(5)

    def log_message(self, fmt, *args):
        # Request headers contain a secret; never log them.
        print("request", self.client_address[0], fmt % args, file=sys.stderr)

    def authorized(self):
        global last_device_contact
        given = self.headers.get(legacy.TOKEN_HEADER, "")
        expected = SECRET.read_text(encoding="ascii").strip()
        accepted = hmac.compare_digest(given, expected)
        if accepted:
            last_device_contact = time.monotonic()
        return accepted

    def response(self, code, body=b""):
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_GET(self):
        if not self.authorized():
            self.response(403)
            return
        if self.path == "/ping":
            self.response(200, b"ready\n")
            return
        if self.path != "/next":
            self.response(404)
            return
        if "session=on" not in CONFIG.read_text(encoding="ascii").splitlines():
            self.response(403)
            return
        if not link_enabled or current_preset() != active_transport_preset():
            self.response(200, b"0\nnone\n\n")
            return
        with closing(database()) as db, db:
            row = db.execute("SELECT id, kind, payload FROM tasks WHERE state='queued' ORDER BY id LIMIT 1").fetchone()
            if row:
                db.execute("UPDATE tasks SET state='sent' WHERE id=?", (row[0],))
        if row:
            body = f"{row[0]}\n{row[1]}\n{row[2]}\n".encode("ascii")
        else:
            body = next_live_action()
        self.response(200, body)

    def do_POST(self):
        if not self.authorized():
            self.response(403)
            return
        try:
            length = int(self.headers.get("Content-Length", "-1"))
            ident = int(self.headers.get(legacy.ID_HEADER, "0"))
        except ValueError:
            self.response(400)
            return
        kind = self.headers.get(legacy.TYPE_HEADER, "")
        limit = MAX_SHOT if kind == "shot" else MAX_STREAM if kind in ("stream", "streamz", "streamav") else MAX_REPORT
        if length < 0 or length > limit or ident < 0:
            self.response(413)
            return
        if self.path == "/bug-it":
            kind = "report"
        elif self.path == "/upload" and kind not in ("shot", "stream", "streamz", "streamav", "report"):
            self.response(400)
            return
        elif self.path == "/result" and (kind != "text" or ident == 0 or length > 2048):
            self.response(400)
            return
        elif self.path not in ("/upload", "/bug-it", "/result"):
            self.response(404)
            return
        body = self.rfile.read(length)
        if len(body) != length:
            self.response(400)
            return
        if self.path == "/result":
            result = body.decode("utf-8", errors="replace")
            with closing(database()) as db, db:
                count = db.execute("UPDATE tasks SET state='done', result=? WHERE id=? AND state='sent'", (result, ident)).rowcount
            self.response(200 if count else 404)
            return
        if kind == "shot" and not valid_bmp(kind, body):
            self.response(400)
            return
        frame = decode_stream(kind, body) if kind in ("stream", "streamz", "streamav") else None
        if kind in ("stream", "streamz", "streamav") and frame is None:
            self.response(400)
            return
        if frame is not None:
            global live_frame, live_version, live_audio, live_audio_version
            with live_lock:
                live_frame = frame
                live_version += 1
                live_audio = decode_audio(kind, body)
                live_audio_version = live_version
                if live_audio:
                    live_audio_chunks.append((live_audio_version, live_audio))
            self.response(201)
            return
        digest = hashlib.sha256(body).hexdigest()[:16]
        suffix = "bmp" if kind == "shot" else "txt"
        destination = CAPTURES / f"{kind}-{ident or 'manual'}-{digest}.{suffix}"
        destination.write_bytes(body)
        with closing(database()) as db, db:
            capture_api.record_file(db, ident, destination.name)
            if ident:
                db.execute("UPDATE tasks SET state='done', result=? WHERE id=? AND kind=?",
                           ('Capture artifact saved on PC', ident, kind))
            capture_api.save_manifests(db, CAPTURES)
        print(f"Saved {destination} ({len(body)} bytes)")
        self.response(201)


def reverse_action():
    """Take one bounded queued command, or the newest viewer input/preview request."""
    if not receiver_on() or not link_enabled or not device_connected() or current_preset() != active_transport_preset():
        return 0, "none", "-"
    with closing(database()) as db:
        # A shot is acknowledged before its BMP arrives. Keep subsequent
        # commands queued while polling for that file; sending one alongside
        # the capture can leave it marked sent before the device executes it.
        capture = db.execute("SELECT 1 FROM tasks WHERE kind IN ('shot', 'report') AND state='sent' LIMIT 1").fetchone()
        if capture:
            return 0, "none", "-"
        row = db.execute("SELECT id, kind, payload FROM tasks WHERE state='queued' "
                         "AND kind IN ('console', 'input', 'shot', 'report') ORDER BY id LIMIT 1").fetchone()
    if row:
        return row
    raw = next_live_action().decode("ascii").splitlines()
    return int(raw[0]), raw[1], raw[2] or "-"


def reverse_exchange(host, port, link=None):
    """One PC-originated request; the 3DS never opens a socket to Windows."""
    global last_device_contact, live_frame, live_version, live_audio, live_audio_version, reverse_stage, device_perf, device_perf_at
    host = private_host(host)
    ident, kind, payload = reverse_action()
    if kind not in ("none", "console", "input", "pad", "touch", "shot", "report", "stream", "perf"):
        raise ValueError("Unsupported reverse action")
    if any(c in payload for c in "\r\n") or len(payload) > 127:
        raise ValueError("Reverse action is too long")
    token = SECRET.read_text(encoding="ascii").strip()
    if len(token) != 64 or any(c not in "0123456789abcdef" for c in token):
        raise ValueError("Invalid private pairing token")
    action = f"{ident} {kind} {payload}\n".encode("ascii")
    exchange_started = time.monotonic()
    new_socket = link is None or link.conn is None
    reverse_stage = "connect" if new_socket else "reuse"
    conn = socket.create_connection((host, port), timeout=2.0) if new_socket else link.conn
    if link is not None and new_socket:
        link.conn = conn
    with (conn if link is None else nullcontext(conn)):
        if new_socket:
            conn.settimeout(6.0)
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            connected_at = time.monotonic()
            reverse_stage = "hello"
            conn.sendall(legacy.HELLO)
            challenge = bytearray()
            while len(challenge) < 128:
                part = conn.recv(1)
                if not part:
                    raise ConnectionError("3DS closed the pairing challenge")
                challenge += part
                if part == b"\n":
                    break
            else:
                raise ValueError("Oversized 3DS challenge")
            parts = bytes(challenge).strip().split(b" ")
            if len(parts) != 4 or tuple(parts[:2]) != legacy.CHALLENGE_PREFIX \
                    or len(parts[2]) != 32 or len(parts[3]) != 64:
                raise ValueError("Invalid 3DS challenge")
            try:
                nonce = bytes.fromhex(parts[2].decode("ascii"))
            except (ValueError, UnicodeDecodeError) as exc:
                raise ValueError("Invalid 3DS challenge") from exc
            secret = bytes.fromhex(token)
            server_mac = hmac.new(secret, nonce + b"server\n", hashlib.sha256).hexdigest().encode()
            if not hmac.compare_digest(parts[3], server_mac):
                raise ValueError("3DS pairing proof failed")
            challenge_at = time.monotonic()
        else:
            connected_at = challenge_at = exchange_started
            nonce = link.nonce
            secret = bytes.fromhex(token)
        sequence = link.sequence if link is not None else 0
        mac = hmac.new(secret, nonce + (struct.pack("<I", sequence) if sequence else b"") + action,
                       hashlib.sha256).hexdigest()
        request = f"{legacy.MAGIC} {mac} ".encode("ascii") + action
        reverse_stage = f"action {kind}"
        conn.sendall(request)
        header = bytearray()
        while len(header) < 96:
            part = conn.recv(1)
            if not part:
                raise ConnectionError("3DS closed the exchange")
            header += part
            if part == b"\n":
                break
        else:
            raise ValueError("Oversized 3DS header")
        try:
            magic, outgoing_kind, outgoing_id, length = header.decode("ascii").split()
            outgoing_id, length = int(outgoing_id), int(length)
        except (ValueError, UnicodeDecodeError) as exc:
            raise ValueError("Invalid 3DS header") from exc
        limits = {"none": 0, "result": 2048, "stream": MAX_STREAM, "streamz": MAX_STREAM, "streamav": MAX_STREAM,
                  "shot": MAX_SHOT, "report": MAX_REPORT, "perf": 1024}
        if magic != legacy.MAGIC or outgoing_kind not in limits or outgoing_id < 0 \
                or length < 0 or length > limits[outgoing_kind]:
            raise ValueError("Invalid 3DS transfer length or type")
        header_at = time.monotonic()
        last_device_contact = header_at
        body = bytearray()
        reverse_stage = f"receive {outgoing_kind}"
        receive_started = time.monotonic()
        while len(body) < length:
            try:
                part = conn.recv(min(8192, length - len(body)))
            except OSError as exc:
                # Some 3DS Wi-Fi stacks reset immediately after send/close,
                # dropping only the tail of a disposable preview frame.
                if outgoing_kind == "stream" and length - len(body) <= 8192 and body[:2] == b"BM":
                    body.extend(bytes(length - len(body)))
                    break
                raise ConnectionError(f"3DS {outgoing_kind} stopped after {len(body)}/{length} bytes in "
                                      f"{time.monotonic() - receive_started:.1f}s: {exc}") from exc
            if not part:
                if outgoing_kind == "stream" and length - len(body) <= 8192 and body[:2] == b"BM":
                    body.extend(bytes(length - len(body)))
                    break
                raise ConnectionError("3DS transfer ended early")
            body += part
            # An authenticated capture that is still making progress is a
            # live device, even when the whole transfer takes over eight seconds.
            last_device_contact = time.monotonic()
        body_at = time.monotonic()
    if link is not None:
        keep = outgoing_kind not in ("result", "shot", "report") and sequence < 0xFFFFFFFF
        if keep and new_socket:
            # The previous 3DS build half-closes every exchange. Detect that
            # once, then continue using one-shot connections with it.
            conn.settimeout(0.03)
            try:
                keep = conn.recv(1, socket.MSG_PEEK) != b""
            except socket.timeout:
                keep = True
            except OSError:
                keep = False
            conn.settimeout(6.0)
        if keep:
            link.nonce = nonce
            link.sequence = sequence + 1
        else:
            link.close()
    closed_at = time.monotonic()
    reverse_stage = "complete"
    last_device_contact = time.monotonic()
    if ident:
        with closing(database()) as db, db:
            db.execute("UPDATE tasks SET state='sent' WHERE id=? AND state='queued'", (ident,))
    if outgoing_kind == "result":
        with closing(database()) as db, db:
            result = body.decode("utf-8", errors="replace")
            db.execute("UPDATE tasks SET state=CASE WHEN kind IN ('shot', 'report') AND ? IN (?, ?) THEN 'sent' ELSE 'done' END, "
                       "result=? WHERE id=? AND state='sent'",
                       (result, "screenshot saved on SD, queued for PC", "logs saved on SD, queued for PC", result, outgoing_id))
            capture_api.save_manifests(db, CAPTURES)
    elif outgoing_kind == 'perf':
        sample = telemetry_api.decode_morrowind(body)
        with live_lock:
            device_perf = sample
            device_perf_at = time.monotonic()
    elif outgoing_kind in ("shot", "report", "stream", "streamz", "streamav"):
        if outgoing_kind == "shot" and not valid_bmp(outgoing_kind, body):
            raise ValueError("Invalid 3DS BMP transfer")
        frame = decode_stream(outgoing_kind, body) if outgoing_kind in ("stream", "streamz", "streamav") else None
        if outgoing_kind in ("stream", "streamz", "streamav") and frame is None:
            raise ValueError("Invalid 3DS preview transfer")
        if frame is not None:
            with live_lock:
                live_frame = frame
                live_version += 1
                stream_transfer_ms.append(round((closed_at - exchange_started) * 1000))
                stream_stage_ms.append(tuple(round((b - a) * 1000) for a, b in (
                    (exchange_started, connected_at), (connected_at, challenge_at),
                    (challenge_at, header_at), (header_at, body_at), (body_at, closed_at))))
                live_audio = decode_audio(outgoing_kind, body)
                live_audio_version = live_version
                if live_audio:
                    live_audio_chunks.append((live_audio_version, live_audio))
        else:
            digest = hashlib.sha256(body).hexdigest()[:16]
            suffix = "bmp" if outgoing_kind == "shot" else "txt"
            destination = CAPTURES / f"{outgoing_kind}-{outgoing_id or 'manual'}-{digest}.{suffix}"
            destination.write_bytes(body)
            print(f"Saved {destination} ({len(body)} bytes)")
            # A full BMP can keep the 3DS busy beyond the eight-second link
            # timeout. The authenticated file itself proves that a late shot
            # completed, even if its queued task was cancelled meanwhile.
            if outgoing_kind in ('shot', 'report') and outgoing_id:
                with closing(database()) as db, db:
                    db.execute("UPDATE tasks SET state='done', result=? WHERE id=? AND kind=? "
                               "AND state IN ('sent', 'cancelled', 'done')",
                               ("screenshot saved on SD and PC" if outgoing_kind == 'shot' else 'logs saved on SD and PC', outgoing_id, outgoing_kind))
                    capture_api.record_file(db, outgoing_id, destination.name)
                    capture_api.save_manifests(db, CAPTURES)
    return outgoing_kind


def reverse_loop(host, port, pc_host=None, subnet=None, auto_pc_host=False):
    global discovery_status, paired_device_host
    last_error = ""
    link = ReverseLink()
    cancel_pending()
    was_connected = False
    target = host if host != "auto" else None
    last_discovery = 0.0
    last_host_check = 0.0
    connect_failures = 0
    retry_seen = retry_generation
    while True:
        if current_preset() != active_transport_preset():
            link.close()
            time.sleep(.2)
            continue
        if auto_pc_host and time.monotonic() - last_host_check >= 2:
            last_host_check = time.monotonic()
            try:
                current_host = local_pc_host()
            except ValueError:
                current_host = None
            if current_host != pc_host:
                pc_host = current_host
                refresh_network_adapters(pc_host)
        if retry_seen != retry_generation:
            retry_seen = retry_generation
            link.close()
            target = host if host != "auto" else None
            last_discovery = 0.0
            connect_failures = 0
            paired_device_host = ""
            discovery_status = "retrying"
        if host == "auto" and target is None:
            if time.monotonic() - last_discovery < 3:
                time.sleep(0.2)
                continue
            last_discovery = time.monotonic()
            if pc_host is None and subnet is None:
                paired_device_host = ""
                discovery_status = "waiting for private LAN"
                time.sleep(1)
                continue
            target = discover_paired_host(pc_host, port, SECRET.read_text(encoding="ascii").strip(), subnet)
            if target is None:
                time.sleep(1)
                continue
        if was_connected and not device_connected():
            cancel_pending()
            was_connected = False
        # The 3DS polls once per rendered frame. A fixed 100 ms sleep capped
        # the preview below 10 fps even when the link had spare bandwidth.
        preview_active = time.monotonic() - stream_requested < 2.5
        delay = (0.001 if link.conn else 0.005) if preview_active else 0.05
        try:
            reverse_exchange(target, port, link)
            last_error = ""
            was_connected = True
            connect_failures = 0
        except (OSError, ValueError, ConnectionError) as exc:
            link.close()
            # One line per distinct failure; the local viewer reports connection state.
            message = f"3DS link waiting at {reverse_stage}: {type(exc).__name__}: {exc}"
            if message != last_error:
                print(message, file=sys.stderr)
                last_error = message
            connect_failures += 1
            if host == "auto" and connect_failures >= 3:
                target = None
                connect_failures = 0
            delay = 0.5
        time.sleep(delay)


def enqueue(kind, payload):
    if current_preset() != active_transport_preset():
        raise ValueError("Selected preset has no active device adapter")
    if not receiver_on():
        raise ValueError("Remote session is off; run setup --session and copy its config to the SD")
    if not link_enabled:
        raise ValueError("PC link is disconnected; reconnect in the viewer")
    if reverse_mode() and not device_connected():
        raise ValueError("Paired 3DS is not connected")
    with closing(database()) as db, db:
        pending = db.execute("SELECT count(*) FROM tasks WHERE state IN ('queued', 'sent')").fetchone()[0]
        if pending >= 16:
            raise ValueError("Queue full; wait for the 3DS or cancel old requests")
        cur = db.execute("INSERT INTO tasks (kind, payload) VALUES (?, ?)", (kind, payload))
    print(f"Queued {kind} #{cur.lastrowid}")
    return cur.lastrowid


def receiver_on():
    return CONFIG.exists() and "session=on" in CONFIG.read_text(encoding="ascii").splitlines()


def reverse_mode():
    return CONFIG.exists() and "mode=reverse" in CONFIG.read_text(encoding="ascii").splitlines()


def device_connected():
    return time.monotonic() - last_device_contact < 8


def cancel_pending():
    with closing(database()) as db, db:
        db.execute("UPDATE tasks SET state='cancelled' WHERE state IN ('queued', 'sent') "
                   "AND kind IN ('console', 'input', 'shot', 'report')")


def encode_input(buttons, frames, axes):
    if not isinstance(frames, int) or isinstance(frames, bool) or not 1 <= frames <= 30:
        raise ValueError("Frames must be 1..30")
    if not isinstance(buttons, str):
        raise ValueError("Buttons must be comma-separated names")
    names = [v.strip().upper() for v in buttons.split(",")]
    if not names or any(n not in KEYS for n in names if n != "NONE"):
        raise ValueError("Unknown button")
    if len(axes) != 4 or any(not isinstance(v, (int, float)) or not math.isfinite(v) or not -1 <= v <= 1 for v in axes):
        raise ValueError("Motion axes must be -1..1")
    bits = sum(1 << KEYS[name] for name in set(names) if name != "NONE")
    return f"{bits:x} {frames} {axes[0]:.3f} {axes[1]:.3f} {axes[2]:.3f} {axes[3]:.3f}"


def latest_capture():
    selected = current_preset()
    if selected == 'example': return None
    pattern = f"{selected}-shot-*.bmp" if selected in plugin_runtimes else "shot-*.bmp"
    shots = list(CAPTURES.glob(pattern)) if CAPTURES.exists() else []
    return max(shots, key=lambda p: p.stat().st_mtime_ns) if shots else None


def viewer_state():
    selected = current_preset()
    if selected == 'example':
        return {'preset':selected,'connected':False,'transportConnected':False,'session':False,
                'linkEnabled':False,'discovery':'local example','pairedDeviceAddress':None,
                'tasks':[],'captures':[],'captureVersion':None,'captureAtMs':None,
                'streamVersion':0,'audioVersion':0,'streamTransferMs':None,'streamStagesMs':None,
                'perf':None,'perfEnabled':performance_capture.enabled(LOCAL / selected),'deviceMeta':None,'controllerError':''}
    with closing(database()) as db:
        if selected in plugin_runtimes:
            prefix = f"plugin:{selected}:"
            rows = db.execute("SELECT * FROM tasks WHERE substr(kind, 1, ?) = ? ORDER BY id DESC LIMIT 20",
                              (len(prefix), prefix))
        else:
            rows = db.execute("SELECT * FROM tasks WHERE substr(kind, 1, 7) != 'plugin:' "
                              "ORDER BY id DESC LIMIT 20")
        tasks = [dict(id=i, kind=k, payload=p, state=s, result=r) for i, k, p, s, r in rows]
    shot = latest_capture()
    plugin = plugin_runtimes.get(selected)
    adapter = plugin.status() if plugin else None
    with live_lock:
        frame_version = plugin_versions.get(selected, 0) if plugin else live_version
        audio_version = plugin_audio_versions.get(selected, 0) if plugin else live_audio_version
        mean_stream_ms = round(sum(stream_transfer_ms) / len(stream_transfer_ms)) if stream_transfer_ms else None
        stage_ms = [round(sum(row[i] for row in stream_stage_ms) / len(stream_stage_ms))
                    for i in range(5)] if stream_stage_ms else None
        timing = device_perf if device_connected() and time.monotonic() - device_perf_at < 5 else None
        input_lease = plugin_input_arms.get(selected)
        input_armed = bool(input_lease and time.monotonic() < input_lease[1])
    return {
        "connected": adapter["connected"] and link_enabled if plugin else selected_device_connected(),
        "transportConnected": adapter["connected"] if plugin else device_connected(),
        "preset": selected,
        "discovery": adapter["discovery"] if plugin else discovery_status,
        "pairedDeviceAddress": adapter["host"] if plugin else paired_device_host if device_connected() else None,
        "session": adapter["session"] if plugin else receiver_on(),
        "linkEnabled": link_enabled,
        "tasks": tasks,
        "captures": capture_bundles(selected),
        "captureVersion": shot.stat().st_mtime_ns if shot else None,
        "captureAtMs": shot.stat().st_mtime_ns // 1000000 if shot else None,
        "streamVersion": frame_version,
        "streamError": plugin_stream_errors.get(selected, '') if plugin else '',
        "inputArmed": input_armed,
        "audioVersion": audio_version,
        "streamTransferMs": mean_stream_ms,
        "streamStagesMs": stage_ms,
        "perf": (adapter["perf"] if plugin else timing) if performance_capture.enabled(LOCAL / selected) else None,
        "perfEnabled": performance_capture.enabled(LOCAL / selected),
        "deviceMeta": adapter["meta"] if plugin else None,
        "controllerError": plugin_pad_errors.get(selected, "") if plugin else "",
    }


class Viewer(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"
    io_timeout = 15

    def setup(self):
        super().setup()
        self.connection.settimeout(self.io_timeout)

    def log_message(self, fmt, *args):
        pass

    def valid_origin(self):
        # Numeric private Host and same Origin prevent DNS rebinding and
        # cross-site requests to the LAN viewer.
        port = self.server.server_port
        host = self.headers.get("Host", "")
        if not host.endswith(f":{port}"):
            return False
        try:
            host_ip = ipaddress.IPv4Address(host.rsplit(":", 1)[0])
            peer_ip = ipaddress.IPv4Address(self.client_address[0])
        except ipaddress.AddressValueError:
            return False
        private = lambda ip: ip.is_loopback or any(ip in ipaddress.ip_network(net) for net in
            ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))
        if not private(host_ip) or not private(peer_ip):
            return False
        if not getattr(self.server, "lan_enabled", False) and (not host_ip.is_loopback or not peer_ip.is_loopback):
            return False
        origin = f"http://{host}"
        return self.headers.get("Origin", origin) == origin

    def authorized_viewer(self):
        if self.client_address[0] == "127.0.0.1":
            return True
        if not getattr(self.server, "lan_enabled", False):
            return False
        cookie = self.headers.get("Cookie", "")
        token = next((part.split("=", 1)[1] for part in cookie.split("; ")
                      if part.startswith("REMOTE_PILOT_VIEWER=")), "")
        with viewer_auth_lock:
            expiry = viewer_sessions.get(token, 0)
        return bool(token and expiry > time.monotonic())

    def pair_page(self):
        body = ("<!doctype html><meta name='viewport' content='width=device-width,initial-scale=1'>"
                "<link rel='stylesheet' href='/viewer.css'><title>Remote Pilot Pairing</title>"
                "<main><h1>Remote Pilot</h1><p>Enter the six-digit code shown by the receiver.</p>"
                "<form method='post' action='/pair'><label>Pairing code "
                "<input name='pin' inputmode='numeric' pattern='[0-9]{6}' maxlength='6' required></label> "
                "<button type='submit'>Connect</button></form></main>").encode()
        self.response(200, body, "text/html; charset=utf-8")

    def response(self, code, body=b"", content_type="text/plain; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'self'")
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_GET(self):
        if not self.valid_origin():
            self.response(403)
            return
        if self.path == "/viewer.css":
            self.response(200, (HERE / "viewer.css").read_bytes(), "text/css; charset=utf-8")
            return
        if not self.authorized_viewer():
            self.pair_page() if self.path == "/" else self.response(403)
            return
        paths = {"/": (HERE / "viewer.html", "text/html; charset=utf-8"),
                 "/homebrew.js": (HERE / "homebrew.js", "text/javascript; charset=utf-8"),
                 "/diagnostics_ui.js": (HERE / "diagnostics_ui.js", "text/javascript; charset=utf-8"),
                 "/data_transfer_ui.js": (HERE / "data_transfer_ui.js", "text/javascript; charset=utf-8"),
                 "/homebrew_flow.js": (HERE / "homebrew_flow.js", "text/javascript; charset=utf-8"),
                 "/viewer.js": (HERE / "viewer.js", "text/javascript; charset=utf-8"),
                 "/themes.css": (HERE / "themes.css", "text/css; charset=utf-8")}
        if self.path in paths:
            file, content_type = paths[self.path]
            self.response(200, file.read_bytes(), content_type)
        elif self.path in ("/theme/menu-frame.png", "/theme/menu-head.png"):
            image = LOCAL / "theme" / self.path.rsplit("/", 1)[1]
            self.response(200, image.read_bytes(), "image/png") if image.is_file() else self.response(404)
        elif self.path.startswith("/presets/") and self.path.endswith("/theme.css"):
            parts = self.path.split("/")
            stylesheet = PRESETS / parts[2] / "theme.css" if len(parts) == 4 and parts[2] in {
                preset["id"] for preset in public_presets()} else None
            self.response(200, stylesheet.read_bytes(), "text/css; charset=utf-8") \
                if stylesheet and stylesheet.is_file() else self.response(404)
        elif self.path == "/api/homebrew/status":
            try:
                value = homebrew_api.runtime(plugin_runtimes).homebrew_request("status", {})
                handoff = value.get("handoff")
                if handoff and not value.get('connected') and handoff.get("preset") == current_preset():
                    state = viewer_state()
                    adapter = homebrew_api.runtime(plugin_runtimes).adapter
                    elapsed = time.monotonic() - getattr(adapter, 'handoff_at', time.monotonic())
                    fresh = (last_device_contact > getattr(adapter, 'handoff_at', time.monotonic())
                             if current_preset() == 'morrowind' else elapsed > 3)
                    if state.get("connected") and state.get("session") and fresh:
                        value['state'] = 'game-connected'
                        handoff["state"] = "game-connected"
                        handoff["detail"] = "Selected game's paired transport is connected"
                    elif elapsed > 60:
                        value['state'] = 'unavailable'
                        handoff["state"] = "unavailable"
                        handoff["detail"] = "Game transport not confirmed; inspect the console and reopen companion if needed"
                self.response(200, json.dumps(value).encode(), "application/json; charset=utf-8")
            except ValueError as exc:
                self.response(400, str(exc).encode())
        elif self.path == "/api/state":
            self.response(200, json.dumps(viewer_state()).encode(), "application/json; charset=utf-8")
        elif self.path == "/api/presets":
            self.response(200, json.dumps({"selected": current_preset(), "presets": public_presets()}).encode(),
                          "application/json; charset=utf-8")
        elif self.path == "/api/catalog":
            catalog = PRESETS / current_preset() / "catalog.json"
            self.response(200, catalog.read_bytes(), "application/json; charset=utf-8") \
                if catalog.is_file() and catalog.stat().st_size <= 65536 else self.response(404)
        elif self.path.startswith('/captures/'):
            name = self.path.removeprefix('/captures/')
            safe = bool(re.fullmatch(r'[a-zA-Z0-9_.-]+\.(bmp|txt|json)', name))
            file = CAPTURES / name
            self.response(200, file.read_bytes(), 'image/bmp' if name.endswith('.bmp') else
                          'application/json; charset=utf-8' if name.endswith('.json') else 'text/plain; charset=utf-8') \
                if safe and file.is_file() else self.response(404)
        elif self.path.startswith("/latest.bmp"):
            shot = latest_capture()
            self.response(200, shot.read_bytes(), "image/bmp") if shot else self.response(404)
        elif self.path.startswith("/live.bmp"):
            with live_lock:
                selected = current_preset()
                frame = b'' if selected == 'example' else plugin_frames.get(selected, b"") if selected in plugin_runtimes else live_frame
            self.response(200, frame, "image/bmp") if frame else self.response(404)
        elif self.path.startswith("/live.pcm"):
            with live_lock:
                selected = current_preset()
                if selected == 'example':
                    samples = b''
                elif selected in plugin_runtimes:
                    chunks = plugin_audio_chunks.get(selected)
                    samples = chunks[-1][1] if chunks else b""
                else:
                    samples = live_audio
            self.response(200, samples, "application/octet-stream") if samples else self.response(404)
        elif self.path.startswith("/live-audio.pcm?since="):
            try:
                since = int(self.path.partition("?since=")[2])
                if since < 0 or since > 0xffffffff:
                    raise ValueError()
            except ValueError:
                self.response(400)
                return
            with live_lock:
                selected = current_preset()
                if selected == 'example':
                    version, chunks = 0, b''
                elif selected in plugin_runtimes:
                    version = plugin_audio_versions.get(selected, 0)
                    chunks = b"".join(samples for number, samples in
                                      plugin_audio_chunks.get(selected, ()) if number > since)
                else:
                    version = live_audio_version
                    chunks = b"".join(samples for number, samples in live_audio_chunks if number > since)
            # Keep playback close to the game after a long network gap.
            limit = plugin_audio_limit(selected) if selected in plugin_runtimes else 16364
            if limit == 16384: limit = 16364  # Preserve the existing presets' half-second trim.
            chunks = chunks[-limit:]
            self.response(200, struct.pack("<I", version & 0xffffffff) + chunks,
                          "application/octet-stream")
        else:
            self.response(404)

    def do_POST(self):
        global link_enabled, pad_payload, pad_delivered, touch_payload, touch_revision, touch_delivered, touch_updated, stream_pending, retry_generation, perf_pending, perf_requested
        if not self.valid_origin():
            self.response(403)
            return
        if self.path == "/pair" and getattr(self.server, "lan_enabled", False):
            self.pair_post()
            return
        if not self.authorized_viewer() or self.headers.get("X-Remote-Pilot-Viewer") != "1":
            self.response(403)
            return
        try:
            length = int(self.headers.get("Content-Length", "-1"))
            if self.path == "/api/homebrew/file":
                if not link_enabled:
                    raise ValueError("Enable the PC link before deployment")
                runtime = homebrew_api.runtime(plugin_runtimes)
                if "upload" not in runtime.capabilities:
                    raise ValueError("Adapter does not advertise upload")
                if self.headers.get("X-Install", "0") not in ("0", "1"):
                    raise ValueError("X-Install must be 0 or 1")
                if self.headers.get("X-Install") == "1" and "install" not in runtime.capabilities:
                    raise ValueError("Adapter does not advertise install")
                if self.headers.get("Content-Type") != "application/octet-stream":
                    raise ValueError("Expected a CIA byte stream")
                self.connection.settimeout(15)
                value = runtime.adapter.receive_file(self.rfile, length,
                    self.headers.get("X-File-Sha256"), self.headers.get("X-Title-Id"),
                    self.headers.get("X-Install") == "1")
                self.response(202, json.dumps(value).encode(), "application/json; charset=utf-8")
                return
            if length < 0 or length > (4096 if self.path.startswith('/api/homebrew/') else 512):
                raise ValueError("Request too large")
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError("Object expected")
            if self.path.startswith('/api/homebrew/'):
                action = self.path.removeprefix('/api/homebrew/')
                if not link_enabled and action not in ('status', 'configure', 'system-release', 'cancel', 'inspect'):
                    raise ValueError("Enable the PC link before homebrew actions")
                runtime = homebrew_api.runtime(plugin_runtimes)
                value = runtime.homebrew_request(action, data)
                if action == 'launch' and value.get('preset'):
                    select_preset(value['preset'])
                self.response(200, json.dumps(value).encode(), 'application/json; charset=utf-8')
                return
            if current_preset() == 'example' and self.path not in ('/api/preset','/api/theme'):
                raise ValueError('Example is a local preview with no device connection')
            if self.path == "/api/preset":
                preset_id = data.get("id")
                if not isinstance(preset_id, str):
                    raise ValueError("Preset id must be a string")
                self.response(200, json.dumps({"selected": select_preset(preset_id)}).encode(),
                              "application/json; charset=utf-8")
                return
            elif self.path == "/api/theme":
                preset_id = data.get("id")
                colors = data.get("colors")
                if not isinstance(preset_id, str):
                    raise ValueError("Preset id must be a string")
                self.response(200, json.dumps({"id": preset_id, "colors": set_theme_override(preset_id, colors)}).encode(),
                              "application/json; charset=utf-8")
                return
            elif self.path == "/api/console":
                value = data.get("text", "")
                if not isinstance(value, str) or not 1 <= len(value) <= 127 or any(ord(c) < 32 or ord(c) > 126 for c in value):
                    raise ValueError("Console command must be printable ASCII, up to 127 characters")
                ident = plugin_enqueue("console", value) if active_plugin() else enqueue("console", value)
            elif self.path == "/api/input":
                payload = encode_input(data.get("buttons", "NONE"), data.get("frames", 1),
                                       [data.get(k, 0) for k in ("moveX", "moveY", "lookX", "lookY")])
                if active_plugin():
                    manifest = next(item for item in public_presets() if item["id"] == current_preset())
                    buttons = {name.strip().upper() for name in data.get("buttons", "NONE").split(",")}
                    if buttons - {"NONE"} - set(manifest.get("inputButtons", [])):
                        raise ValueError("Button is unavailable for this preset")
                    if not manifest.get("analogInput", False) and any(float(axis) for axis in payload.split()[2:]):
                        raise ValueError("This preset accepts button input only")
                    ident = plugin_enqueue("input", payload, data.get('owner'))
                else:
                    ident = enqueue("input", payload)
            elif self.path == '/api/control-arm':
                self.response(200,json.dumps(set_input_arm(current_preset(),data)).encode(),'application/json; charset=utf-8')
                return
            elif self.path == "/api/gamepad":
                if active_plugin():
                    plugin_set_gamepad(data)
                    self.response(200, b'{"ok":true}', "application/json; charset=utf-8")
                    return
                global pad_revision, pad_updated
                payload = encode_input(data.get("buttons", "NONE"), data.get("frames", 8),
                                       [data.get(k, 0) for k in ("moveX", "moveY", "lookX", "lookY")])
                if not receiver_on() or not link_enabled or (reverse_mode() and not device_connected()):
                    raise ValueError("Remote session is off")
                with live_lock:
                    pad_payload = payload
                    pad_revision += 1
                    pad_updated = time.monotonic()
                self.response(200, b'{"ok":true}', "application/json; charset=utf-8")
                return
            elif self.path == '/api/touch':
                payload = touch_api.encode_sample(data)
                if active_plugin():
                    plugin_set_gamepad(data, kind='touch')
                else:
                    if not receiver_on() or not link_enabled or (reverse_mode() and not device_connected()):
                        raise ValueError('Remote session is off')
                    with live_lock:
                        touch_payload = payload
                        touch_revision += 1
                        touch_updated = time.monotonic()
                self.response(200, b'{"ok":true}', 'application/json; charset=utf-8')
                return
            elif self.path == "/api/stream":
                if active_plugin():
                    plugin_request_stream()
                    self.response(200, b'{"ok":true}', "application/json; charset=utf-8")
                    return
                global stream_requested
                if not receiver_on() or not link_enabled or (reverse_mode() and not device_connected()):
                    raise ValueError("Remote session is off")
                with live_lock:
                    stream_pending = True
                    stream_requested = time.monotonic()
                self.response(200, b'{"ok":true}', "application/json; charset=utf-8")
                return
            elif self.path == "/api/link":
                desired = data.get("connected")
                if not isinstance(desired, bool):
                    raise ValueError("connected must be true or false")
                if not desired:
                    homebrew_api.release(plugin_runtimes)
                with live_lock:
                    link_enabled = desired
                    if not desired:
                        plugin_input_arms.clear()
                        pad_payload = ""
                        pad_delivered = pad_revision
                        touch_payload = ''
                        touch_delivered = touch_revision
                        stream_pending = False
                if not desired:
                    runtime=active_plugin()
                    notice=getattr(runtime.adapter,'disconnect',None) if runtime else None
                    if callable(notice):
                        def notify_disconnect():
                            try:notice()
                            except Exception:pass
                        threading.Thread(target=notify_disconnect,daemon=True).start()
                self.response(200, json.dumps({"linkEnabled": desired}).encode(), "application/json; charset=utf-8")
                return
            elif self.path == "/api/retry":
                if not link_enabled:
                    raise ValueError("Enable the PC link before retrying")
                plugin = active_plugin()
                if plugin:
                    if not plugin.status()["session"]:
                        raise ValueError("Arm the selected device session before retrying")
                    plugin.retry()
                else:
                    if not receiver_on() or not reverse_mode():
                        raise ValueError("Arm the remote session before retrying")
                    with live_lock:
                        retry_generation += 1
                self.response(200, b'{"retryRequested":true}', "application/json; charset=utf-8")
                return
            elif self.path == "/api/shot":
                if active_plugin():
                    ident = plugin_enqueue("shot", "-")
                else:
                    with closing(database()) as db:
                        row = db.execute("SELECT id FROM tasks WHERE kind='shot' AND state IN ('queued', 'sent') ORDER BY id DESC LIMIT 1").fetchone()
                    ident = row[0] if row else enqueue("shot", "-")
            elif self.path == '/api/capture':
                self.response(200, json.dumps(request_capture()).encode(), 'application/json; charset=utf-8')
                return
            elif self.path == "/api/preview" and active_plugin():
                kind = data.get("kind")
                item_id = data.get("id")
                map_id = data.get("map")
                if kind not in ("map", "weapon", "vehicle") or not isinstance(item_id, str) \
                        or not re.fullmatch(r"[a-z0-9_]{1,32}", item_id):
                    raise ValueError("Invalid preview selection")
                if kind != "map":
                    if not isinstance(map_id, str) or not re.fullmatch(r"[a-z0-9_]{1,32}", map_id):
                        raise ValueError("Invalid preview map")
                    item_id += ":" + map_id
                ident = plugin_enqueue("preview", kind + ":" + item_id)
            elif self.path in ("/api/report", "/api/log", "/api/perf") and active_plugin():
                kind = self.path.rsplit("/", 1)[1]
                ident = plugin_enqueue(kind, "-")
            elif self.path in ('/api/report', '/api/log'):
                ident = enqueue('report', '-')
            elif self.path == '/api/performance':
                preset = data.get('preset')
                if preset not in {item['id'] for item in public_presets()}:
                    raise ValueError('Unknown preset')
                value = performance_capture.set_enabled(LOCAL / preset, data.get('enabled'))
                if preset == 'morrowind' and not value:
                    with live_lock:
                        perf_pending = False
                self.response(200, json.dumps({'enabled': value}).encode(), 'application/json; charset=utf-8')
                return
            elif self.path == '/api/perf':
                if not performance_capture.enabled(LOCAL / current_preset()):
                    raise ValueError('Performance capture is off')
                if not selected_device_connected() or not receiver_on():
                    raise ValueError('Paired device is not connected')
                with live_lock:
                    now = time.monotonic()
                    if now - perf_requested >= 1:
                        perf_pending = True
                        perf_requested = now
                self.response(200, b'{"id":0}', 'application/json; charset=utf-8')
                return
            else:
                self.response(404)
                return
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            self.response(400, str(exc).encode("utf-8", errors="replace"))
            return
        self.response(200, json.dumps({"id": ident}).encode(), "application/json; charset=utf-8")

    def pair_post(self):
        if self.client_address[0] == "127.0.0.1":
            self.response(403)
            return
        try:
            length = int(self.headers.get("Content-Length", "-1"))
            if not 1 <= length <= 64 or self.headers.get("Content-Type", "").split(";", 1)[0] != "application/x-www-form-urlencoded":
                raise ValueError()
            pin = parse_qs(self.rfile.read(length).decode("ascii"), strict_parsing=True).get("pin", [""])[0]
        except (ValueError, UnicodeDecodeError):
            self.response(400)
            return
        now = time.monotonic()
        peer = self.client_address[0]
        with viewer_auth_lock:
            attempts = [t for t in viewer_attempts.get(peer, []) if now - t < 60]
            if len(attempts) >= 5 or not hmac.compare_digest(pin, viewer_pin):
                attempts.append(now)
                viewer_attempts[peer] = attempts
                self.response(429 if len(attempts) > 5 else 403)
                return
            token = secrets.token_urlsafe(24)
            viewer_sessions[token] = now + 12 * 3600
            viewer_attempts.pop(peer, None)
        self.send_response(303)
        self.send_header("Location", "/")
        self.send_header("Set-Cookie", f"REMOTE_PILOT_VIEWER={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age=43200")
        self.send_header("Content-Length", "0")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()


def submit_cli(action, payload, viewer_port=38764):
    """Send a CLI action to the live process that owns connection state."""
    if not 1 <= viewer_port <= 65535:
        raise ValueError("Viewer port must be between 1 and 65535")
    body = json.dumps(payload).encode("utf-8")
    request = Request(f"http://127.0.0.1:{viewer_port}/api/{action}", body,
                      {"Content-Type": "application/json", "X-Remote-Pilot-Viewer": "1"},
                      method="POST")
    try:
        with urlopen(request, timeout=5) as response:
            result = json.load(response)
    except HTTPError as exc:
        reason = exc.read(300).decode("utf-8", "replace")
        raise ValueError(reason or f"Viewer rejected request ({exc.code})") from exc
    except (URLError, TimeoutError) as exc:
        raise ValueError("Start the local viewer before sending a command") from exc
    print(f"Queued {action} #{result['id']}")
    return result["id"]


def main():
    global viewer_pin
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("setup", help="make private 3DS config, remote control off by default")
    p.add_argument("--host", required=True, help="this PC's private IPv4 address")
    p.add_argument("--port", type=int, default=38763)
    p.add_argument("--session", action="store_true", help="enable remote QA for this SD session")
    p.add_argument("--reverse", action="store_true", help="PC connects to the 3DS; no PC inbound firewall rule")
    p = sub.add_parser("serve", help="listen on private LAN and show a local PC viewer")
    p.add_argument("--viewer-port", type=int, default=38764)
    p.add_argument("--pc-host", help="this PC's private IPv4 address for device discovery")
    p.add_argument("--reverse-host", help="paired device private IPv4 address, or auto (default in reverse mode)")
    p.add_argument("--discover-subnet", help="optional private CIDR for auto discovery (maximum 1024 addresses)")
    p.add_argument("--viewer-lan", action="store_true", help="allow paired phone/tablet browsers on private Wi-Fi")
    p = sub.add_parser("setup-preset", help="make a private device pairing config for a local adapter")
    p.add_argument("preset", help="preset id from its manifest")
    p.add_argument("--device-host", default="auto", help="device private IPv4 address, or auto")
    p.add_argument("--port", type=int, default=38765)
    p = sub.add_parser("console", help="send one game console command through the running viewer")
    p.add_argument("text", help="up to 127 printable ASCII characters")
    p.add_argument("--viewer-port", type=int, default=38764)
    p = sub.add_parser("input", help="press listed buttons for 1..30 frames")
    p.add_argument("buttons", help="comma-separated A,B,X,Y,L,R,UP,DOWN,LEFT,RIGHT,START,SELECT,ZL,ZR; use NONE for motion only")
    p.add_argument("--frames", type=int, default=1)
    p.add_argument("--move-x", type=float, default=0)
    p.add_argument("--move-y", type=float, default=0)
    p.add_argument("--look-x", type=float, default=0)
    p.add_argument("--look-y", type=float, default=0)
    p.add_argument("--viewer-port", type=int, default=38764)
    p = sub.add_parser("shot", help="request both screens through the running viewer")
    p.add_argument("--viewer-port", type=int, default=38764)
    sub.add_parser("status", help="show queued and completed requests")
    args = parser.parse_args()
    if args.command == "setup-preset":
        manifest = next((item for item in public_presets() if item["id"] == args.preset), None)
        if not manifest or manifest["transport"] != "python-v1":
            parser.error("The preset does not provide a local adapter")
        runtime = PluginRuntime(manifest, PRESETS, LOCAL)
        configure = getattr(runtime.adapter, "configure", None)
        if not callable(configure):
            parser.error("The preset adapter does not offer setup")
        path = configure(args.device_host, args.port)
        print(f"Private SD config: {path}")
        print("Copy it to the device path in the preset documentation. Keep pairing files private.")
    elif args.command == "setup":
        if args.reverse and not args.session:
            parser.error("--reverse requires --session")
        setup(args.host, args.port, args.session, args.reverse)
    elif args.command == "serve":
        legacy_available = CONFIG.exists() and SECRET.exists()
        cfg = dict(line.split("=", 1) for line in CONFIG.read_text(encoding="ascii").splitlines()) if legacy_available else {}
        reverse = legacy_available and cfg.get("mode") == "reverse"
        host = serving_pc_host(args.pc_host, cfg.get("host"), reverse,
                               offline_ok=reverse or not legacy_available)
        if not reverse and args.reverse_host:
            parser.error("--reverse-host requires reverse pairing")
        if reverse and cfg.get("session") != "on":
            parser.error("Run setup --session --reverse and recopy the config to the 3DS")
        device_host = ("auto" if not args.reverse_host else args.reverse_host) if reverse else None
        if device_host not in (None, "auto"):
            device_host = private_host(device_host)
        if args.discover_subnet and device_host != "auto":
            parser.error("--discover-subnet requires automatic reverse discovery")
        http = None if reverse or not legacy_available else ThreadingHTTPServer((host, int(cfg["port"])), Receiver)
        viewer = ThreadingHTTPServer(("0.0.0.0" if args.viewer_lan else "127.0.0.1", args.viewer_port), Viewer)
        viewer.lan_enabled = args.viewer_lan
        viewer_pin = f"{secrets.randbelow(1000000):06d}" if args.viewer_lan else ""
        if http:
            http.daemon_threads = True
        viewer.daemon_threads = True
        viewer_thread = threading.Thread(target=viewer.serve_forever, daemon=True)
        for manifest in public_presets():
            if manifest["transport"] == "python-v1":
                runtime = PluginRuntime(manifest, PRESETS, LOCAL, network_host=host,
                                        active=lambda preset_id=manifest["id"]: plugin_poll_active(preset_id),
                                        on_event=plugin_event)
                plugin_runtimes[manifest["id"]] = runtime
                threading.Thread(target=runtime.run_forever, daemon=True).start()
        viewer_thread.start()
        if reverse:
            print(f"Finding paired device on the private LAN ({device_host}); no PC inbound listener")
        elif http:
            print(f"Listening on {host}:{cfg['port']}; remote session {'ON' if cfg.get('session') == 'on' else 'OFF'}")
        else:
            print("Finding paired device on the private LAN; no PC inbound listener")
        print(f"Private PC viewer: http://127.0.0.1:{args.viewer_port}/")
        if args.viewer_lan:
            lan_ip = host
            if device_host:
                try:
                    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as route:
                        route.connect((host if device_host == "auto" and host else device_host, 9))
                        lan_ip = private_host(route.getsockname()[0])
                except (OSError, ValueError):
                    pass
            if lan_ip:
                print(f"Phone/tablet viewer: http://{lan_ip}:{args.viewer_port}/")
            else:
                print("Phone/tablet viewer: waiting for a private LAN address")
            print(f"One-session viewer pairing code: {viewer_pin}")
        try:
            if reverse:
                reverse_loop(device_host, int(cfg["port"]), host, args.discover_subnet,
                             auto_pc_host=not args.pc_host)
            elif http:
                http.serve_forever()
            else:
                previous_host = host
                while True:
                    if not args.pc_host:
                        try:
                            current_host = local_pc_host()
                        except ValueError:
                            current_host = None
                        if current_host != previous_host:
                            refresh_network_adapters(current_host)
                            previous_host = current_host
                    time.sleep(1)
        except KeyboardInterrupt:
            pass
        finally:
            for runtime in plugin_runtimes.values():
                runtime.stop()
            if http:
                http.server_close()
            viewer.shutdown()
            viewer.server_close()
            viewer_thread.join()
    elif args.command == "console":
        value = args.text
        if not value or len(value) > 127 or any(ord(c) < 32 or ord(c) > 126 for c in value):
            parser.error("Console command must be 1..127 printable ASCII characters")
        submit_cli("console", {"text": value}, args.viewer_port)
    elif args.command == "input":
        try:
            submit_cli("input", {"buttons": args.buttons, "frames": args.frames,
                     "moveX": args.move_x, "moveY": args.move_y,
                     "lookX": args.look_x, "lookY": args.look_y}, args.viewer_port)
        except ValueError as exc:
            parser.error(str(exc))
    elif args.command == "shot":
        submit_cli("shot", {}, args.viewer_port)
    elif args.command == "status":
        with closing(database()) as db, db:
            for ident, kind, payload, state, result in db.execute("SELECT * FROM tasks ORDER BY id DESC LIMIT 30"):
                print(f"#{ident} {kind} {state}: {payload} -> {result[:200]}")


if __name__ == "__main__":
    main()
