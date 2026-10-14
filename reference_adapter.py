"""Optional ready-to-configure RP2 adapter for a device implementing the reference protocol."""

from concurrent.futures import ThreadPoolExecutor, as_completed
import ipaddress
import json
from pathlib import Path
import secrets
import socket
import struct
import threading
import time

from reference_transport import exchange, private_ipv4, TransportError


class ReferenceAdapter:
    def __init__(self, local_dir, manifest):
        self.local_dir = Path(local_dir)
        self.manifest = dict(manifest)
        self.config_path = self.local_dir / "pairing.json"
        self.device_path = self.local_dir / "device.cfg"
        self.cache_path = self.local_dir / "last-device.json"
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._retry = threading.Event()
        self._active = lambda: True
        self._event_sink = None
        self._host = ""
        self._last_seen = 0.0
        self._meta = None
        self._perf = None
        self._discovery = "Prepare pairing to begin"
        self._event_baseline = None

    def set_active(self, callback):
        self._active = callback

    def set_event_sink(self, callback):
        self._event_sink = callback

    def _config(self):
        if not self.config_path.is_file():
            return None
        value = json.loads(self.config_path.read_text(encoding="ascii"))
        if not isinstance(value, dict) or type(value.get("port")) is not int or not 1024 <= value["port"] <= 65535:
            raise ValueError("Invalid local pairing")
        token = value.get("token")
        if not isinstance(token, str) or len(token) != 64 or any(c not in "0123456789abcdef" for c in token):
            raise ValueError("Invalid local pairing token")
        host = value.get("host", "auto")
        if host != "auto" and not private_ipv4(host):
            raise ValueError("Invalid paired device address")
        return value

    def setup(self):
        self.local_dir.mkdir(parents=True, exist_ok=True)
        old = self._config()
        if old:
            config = old
        else:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                probe.bind(("127.0.0.1", 0))
                port = probe.getsockname()[1]
            config = {"host": "auto", "port": port, "token": secrets.token_hex(32)}
            temporary = self.config_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(config) + "\n", encoding="ascii")
            temporary.replace(self.config_path)
        self.device_path.write_bytes((f"app_id={self.manifest['id']}\nport={config['port']}\n"
                                      f"token={config['token']}\nsession=on\n").encode("ascii"))
        self._retry.set()
        return {"configPath": str(self.device_path)}

    def _interfaces(self):
        candidates = []
        try:
            for item in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
                address = item[4][0]
                if private_ipv4(address) and address not in candidates:
                    candidates.append(address)
        except OSError:
            pass
        if "127.0.0.1" not in candidates:
            candidates.append("127.0.0.1")
        return candidates

    def _probe(self, host, config):
        try:
            exchange(host, config["port"], config["token"], self.manifest["id"], "ping", timeout=1.5)
            return host
        except (ValueError, TransportError):
            return None

    def _discover(self, config):
        candidates = []
        with self._lock:
            previous = self._host
        if previous:
            candidates.append(previous)
        if config.get("host") != "auto":
            candidates.append(config["host"])
        else:
            try:
                cached = json.loads(self.cache_path.read_text(encoding="ascii"))["host"]
                if private_ipv4(cached):
                    candidates.append(cached)
            except (OSError, ValueError, KeyError, TypeError):
                pass
            for address in self._interfaces():
                if address == "127.0.0.1":
                    candidates.append(address)
        for candidate in dict.fromkeys(candidates):
            if self._probe(candidate, config):
                return candidate
        if config.get("host") != "auto":
            return None
        networks = [ipaddress.IPv4Network(f"{address}/24", strict=False)
                    for address in self._interfaces() if address != "127.0.0.1"]
        addresses = [str(ip) for net in networks for ip in net.hosts() if str(ip) not in candidates]
        if not addresses:
            return None
        pool = ThreadPoolExecutor(max_workers=32)
        try:
            futures = [pool.submit(self._probe, host, config) for host in dict.fromkeys(addresses)]
            for future in as_completed(futures):
                found = future.result()
                if found:
                    for remaining in futures:
                        remaining.cancel()
                    return found
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
        return None

    def _poll(self, host, config):
        token, port, app_id = config["token"], config["port"], self.manifest["id"]
        meta_bytes = exchange(host, port, token, app_id, "meta", timeout=5)
        data = json.loads(meta_bytes.decode("utf-8"))
        if not isinstance(data, dict) or data.get("schemaVersion") != 2 or data.get("appId") != app_id:
            raise ValueError("Device metadata does not match this preset")
        sequence = data.get("captureSequence", 0)
        if type(sequence) is not int or not 0 <= sequence <= 0xffffffff:
            raise ValueError("Invalid capture event sequence")
        safe_meta = {key: data[key] for key in ("label", "state", "captureSequence") if key in data}
        perf = None
        if "perf" in self.manifest["capabilities"]:
            result = exchange(host, port, token, app_id, "perf", timeout=5)
            perf = json.loads(result.decode("utf-8")) if result else None
        with self._lock:
            prior = self._event_baseline
            self._event_baseline = sequence
            self._host = host
            self._last_seen = time.monotonic()
            self._meta = safe_meta
            self._perf = perf
            self._discovery = "Connected to paired device"
        self.cache_path.write_text(json.dumps({"host": host}) + "\n", encoding="ascii")
        if prior is not None and sequence != prior and sequence and self._event_sink:
            self._event_sink("capture", sequence)

    def start(self):
        threading.Thread(target=self._loop, daemon=True,
                         name=f"remote-pilot-discovery-{self.manifest['id']}").start()

    def _loop(self):
        while not self._stop.is_set():
            if not self._active():
                with self._lock:
                    self._event_baseline = None
                self._retry.wait(1)
                self._retry.clear()
                continue
            try:
                config = self._config()
                if not config:
                    with self._lock:
                        self._discovery = "Prepare pairing to begin"
                else:
                    host = self._discover(config)
                    if host:
                        self._poll(host, config)
                    else:
                        with self._lock:
                            self._host = ""
                            self._meta = None
                            self._perf = None
                            self._discovery = "Searching local private network"
            except (ValueError, OSError, TransportError, json.JSONDecodeError):
                with self._lock:
                    self._host = ""
                    self._meta = None
                    self._perf = None
                    self._discovery = "Waiting for paired device"
            self._retry.wait(2)
            self._retry.clear()

    def status(self):
        with self._lock:
            fresh = bool(self._host and time.monotonic() - self._last_seen < 15)
            return {"connected": fresh, "session": self._config() is not None,
                    "host": self._host if fresh else "", "discovery": self._discovery,
                    "meta": self._meta if fresh else None, "perf": self._perf if fresh else None}

    def request(self, kind, payload):
        config = self._config()
        with self._lock:
            host = self._host
        if not config or not host:
            raise TransportError("Paired device is not connected")
        body = b"" if payload in (None, "-") else payload.encode("utf-8")
        result = exchange(host, config["port"], config["token"], self.manifest["id"], kind, body,
                          timeout=15 if kind in ("shot", "stream", "preview") else 8)
        with self._lock:
            self._last_seen = time.monotonic()
        if kind == "stream":
            if len(result) < 8:
                raise ValueError("Truncated live packet")
            image_size, audio_size = struct.unpack_from("<II", result)
            if image_size > 4 * 1024 * 1024 or audio_size > 16384 or audio_size % 2 or len(result) != 8 + image_size + audio_size:
                raise ValueError("Invalid live packet")
            return result[8:8 + image_size], result[8 + image_size:]
        if kind in ("shot", "preview"):
            return result
        if kind in ("meta", "perf"):
            return json.loads(result.decode("utf-8"))
        return result.decode("utf-8", "replace")

    def retry(self):
        with self._lock:
            self._host = ""
            self._last_seen = 0.0
            self._discovery = "Fresh search requested"
        self._retry.set()

    def stop(self):
        self._stop.set()
        self._retry.set()
