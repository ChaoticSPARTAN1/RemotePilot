"""Private companion deployment jobs, file integrity and cross-app state."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import re
import secrets
import threading
import time
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler
from urllib.parse import urlsplit

from homebrew_protocol import CHUNK, HEX, MAX_CIA, CompanionClient, CompanionInterrupted, CompanionRejected, cia_info, private_host, title_id
from luma_input import LumaInput
from homebrew_download import PublicHTTPSHandler
from homebrew_data import DataManager
from homebrew_diagnostics import DiagnosticsManager

CAPS = {"upload", "install", "titles", "launch", "data-transfer", "diagnostics"}
COMPANION_TITLE = "000400000f3d5200"
UPDATER_TITLE = "000400000f3d5300"
TRANSFER_CHUNK = 16 * 1024  # shorter stop-and-wait writes also support the original bootstrap
TERMINAL = {"uploaded", "installed", "cancelled", "failed", "unknown", "interrupted", "launching"}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError("Download redirects are disabled; use the final HTTPS URL")


class HomebrewAdapter:
    def __init__(self, local_dir, manifest):
        self.root = Path(local_dir)
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="homebrew-job")
        self.active = lambda: False
        self.client = None
        self.remote = {}
        self.connected = False
        self.last_poll = 0
        self.jobs = {}
        self.titles = []
        self.handoff = None
        self.stop_event = threading.Event()
        self.system = LumaInput(lambda: self.active())
        self.error = "Pair the companion before connecting"
        self.config_path = self.root / "companion.json"
        self.journal = self.root / "jobs.json"
        parent = Path(__file__).resolve().parent.parent
        self.update_root = parent / 'apps' if (parent / 'apps' / 'verification.json').is_file() else parent / "RemotePilot-Homebrew" / "dist"
        self.update_cache = (None, {})
        try:
            saved = json.loads(self.journal.read_text())
            for job in saved[-20:]:
                if job["state"] not in TERMINAL:
                    job.update(state="interrupted", detail="Receiver restarted; inspect the console job before any new action")
                self.jobs[job["id"]] = job
        except (OSError, ValueError, TypeError, KeyError):
            pass
        self._load()
        self.data = DataManager(self)
        self.diagnostics = DiagnosticsManager(self)

    def set_active(self, callback):
        self.active = callback

    def _load(self):
        if self.config_path.exists():
            config = json.loads(self.config_path.read_text())
            self.client = CompanionClient(config["host"], config["port"], config["token"])

    def configure(self, device_host, port=38765):
        host = private_host(device_host)
        with self.lock:
            if (self.data.busy() or self.diagnostics.busy()) or any(j["state"] not in TERMINAL for j in self.jobs.values()):
                raise ValueError("Finish or cancel the active job before changing pairing")
            token = secrets.token_hex(32)
            if self.config_path.exists():
                token = json.loads(self.config_path.read_text())["token"]
            client = CompanionClient(host, port, token)
            config = {"host": host, "port": port, "token": token}
            temporary = self.config_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(config), encoding="ascii")
            temporary.replace(self.config_path)
            sd_config = self.root / "remote-pilot-homebrew.cfg"
            sd_config.write_text(f"port={port}\ntoken={token}\n", encoding="ascii")
            self.system.release()
            self.client, self.connected = client, False
            return sd_config

    def status(self):
        if self.client and time.monotonic() - self.last_poll > 1:
            self.last_poll = time.monotonic()
            try:
                remote = self.client.call("status")
                if remote.get("protocol") != 1 or not isinstance(remote.get("capabilities"), list) \
                        or any(cap not in CAPS for cap in remote["capabilities"]):
                    raise ValueError("Companion capability negotiation failed")
                # Older bootstraps omit identity; only the main companion can
                # be assumed. Recovery updater identification must be explicit.
                identity = remote.get("applicationTitleId", COMPANION_TITLE)
                if identity not in (COMPANION_TITLE, UPDATER_TITLE) or \
                        (identity == UPDATER_TITLE and (remote.get("updater") is not True or
                                                      remote.get("updateTarget") != COMPANION_TITLE)):
                    raise ValueError("Unexpected companion application identity")
                remote["applicationTitleId"] = identity
                with self.lock:
                    self.remote, self.connected, self.error = remote, True, ""
                    if self.handoff:
                        expected = self.handoff.get("titleId")
                        if expected in (COMPANION_TITLE, UPDATER_TITLE) and identity == expected:
                            self.handoff["state"] = "updater" if identity == UPDATER_TITLE else "companion"
                            self.handoff["detail"] = "Paired target application is connected; press X there to arm"
                        elif expected not in (COMPANION_TITLE, UPDATER_TITLE):
                            self.handoff["state"] = "companion"
                            self.handoff["detail"] = "Companion is open; inspect its launch receipt before retrying"
            except ValueError as exc:
                with self.lock:
                    self.connected, self.error = False, str(exc)
        with self.lock:
            return {"connected": self.connected, "session": self.connected,
                    "host": self.client.host if self.client else "", "discovery": self.error or "Paired companion",
                    "meta": {"application": "RemotePilot Updater" if self.remote.get("applicationTitleId") == UPDATER_TITLE
                             else "RemotePilot Homebrew", "resident": False}, "perf": None}

    def available_updates(self):
        """Offer only the two fixed, owner-built artifacts with a matching receipt."""
        names = {'companion':('RemotePilotHomebrew.cia', COMPANION_TITLE, 'cia'),
                 'updater':('RemotePilotUpdater.cia', UPDATER_TITLE, 'updater')}
        try:
            receipt_path = self.update_root / 'verification.json'
            paths = [receipt_path] + [self.update_root / v[0] for v in names.values()]
            if any(p.is_symlink() for p in paths): return {}
            stamp = tuple((p.stat().st_mtime_ns, p.stat().st_size) for p in paths)
            if self.update_cache[0] == stamp: return dict(self.update_cache[1])
            receipt = json.loads(receipt_path.read_text())
            result = {}
            for kind, (name, title, section) in names.items():
                path = self.update_root / name
                expected = receipt['files'][name]
                info = cia_info(path)
                if info['titleId'] != title or info['version'] != receipt[section]['version'] or \
                        receipt[section]['titleId'] != title or info['size'] != expected['size'] or \
                        hashlib.sha256(path.read_bytes()).hexdigest() != expected['sha256']:
                    raise ValueError('Local update receipt mismatch')
                result[kind] = {**info, 'sha256': expected['sha256']}
            self.update_cache = (stamp, result)
            return dict(result)
        except (OSError, ValueError, TypeError, KeyError):
            return {}

    def snapshot(self):
        with self.lock:
            active = next((j["state"] for j in reversed(list(self.jobs.values())) if j["state"] not in TERMINAL), None)
            latest = next(reversed(self.jobs.values()), None) if self.jobs else None
            if not active and latest and latest['state'] in ('unknown', 'interrupted'):
                active = latest['state']
            state = active or (("updater" if self.remote.get("applicationTitleId") == UPDATER_TITLE else "companion") if self.connected else
                               "launching" if self.handoff and self.handoff.get("state") == "launching" else "unavailable")
            return {"connected": self.connected, "configured": self.client is not None,
                    "state": state, "detail": self.error,
                    "capabilities": sorted(CAPS.intersection(self.remote.get("capabilities", []))) if self.connected else [],
                    "jobs": [dict(j) for j in list(self.jobs.values())[-20:]], "titles": list(self.titles),
                    "remoteJob": self.remote.get("job"), "armed": self.connected and self.remote.get("armed") is True,
                    "consoleHost": self.client.host if self.client else "",
                    "localUpdates": self.available_updates(),
                    "applicationTitleId": self.remote.get("applicationTitleId") if self.connected else None,
                    "buildVersion": self.remote.get("buildVersion") if self.connected else None,
                    "updater": self.connected and self.remote.get("applicationTitleId") == UPDATER_TITLE,
                    "autonomousSupported": self.connected and self.remote.get('autonomousSupported') is True,
                    "autonomousEnabled": self.connected and self.remote.get('armed') is True and self.remote.get('autonomousEnabled') is True,
                    "system": self.system.status(),
                    "handoff": dict(self.handoff) if self.handoff else None,
                    "dataTransfer": self.data.snapshot(),
                    "diagnostics": self.diagnostics.snapshot(),
                    "screenStreaming": False, "audioStreaming": False, "twl": False}

    def _require(self, cap):
        if not self.client or not self.connected or cap not in self.remote.get("capabilities", []):
            raise ValueError("Connected companion does not advertise " + cap)

    def _save(self):
        # caller holds lock; persist outcomes without sources, tokens or LAN addresses.
        temporary = self.journal.with_suffix(".tmp")
        temporary.write_text(json.dumps(list(self.jobs.values())[-20:], indent=2), encoding="utf-8")
        temporary.replace(self.journal)

    def _require_armed(self):
        if self.remote.get("armed") is not True:
            raise ValueError("Press X in the companion to arm this console session")

    def _update(self, ident, **fields):
        with self.lock:
            self.jobs[ident].update(fields)
            self._save()

    def new_job(self, expected_hash, expected_title, install=False):
        self._require("upload")
        self._require_armed()
        if (self.data.busy() or self.diagnostics.busy()):
            raise ValueError("Finish game-data transfer before sending an installer")
        if self.remote.get('job', {}).get('state') == 'unknown':
            raise ValueError('Review the previous console outcome before starting another deployment')
        if not isinstance(expected_hash, str) or not HEX.fullmatch(expected_hash) or type(install) is not bool:
            raise ValueError("Exact SHA-256 and install boolean required")
        title = title_id(expected_title)
        running = self.remote.get("applicationTitleId", COMPANION_TITLE)
        if title == running:
            raise ValueError("Open RemotePilot Updater to update the companion; never replace the running title")
        if running == UPDATER_TITLE and title != COMPANION_TITLE:
            raise ValueError("Recovery updater accepts only the RemotePilot companion CIA")
        if install:
            self._require("install")
        self.system.release()
        with self.lock:
            if any(j["state"] not in TERMINAL or j['state'] in ('unknown','interrupted') for j in self.jobs.values()):
                raise ValueError("Inspect the previous console outcome before starting another deployment")
            ident = secrets.token_hex(16)
            self.jobs[ident] = {"id": ident, "state": "receiving", "done": 0, "total": 0,
                                "sha256": expected_hash, "titleId": title, "install": install,
                                "approvalMode": 'autonomous' if install and self.remote.get('autonomousSupported') is True and self.remote.get('autonomousEnabled') is True else 'manual',
                                "applicationTitleId": running, "detail": ""}
            while len(self.jobs) > 20:
                self.jobs.pop(next(iter(self.jobs)))
            self._save()
        return ident

    def receive_file(self, stream, length, digest, title, install):
        if type(length) is not int or not 0x2020 <= length <= MAX_CIA:
            raise ValueError("CIA upload must be at most 512 MiB")
        ident = self.new_job(digest, title, install)
        path = self.root / (ident + ".cia")
        try:
            self._update(ident, total=length)
            hasher = hashlib.sha256()
            done = 0
            started = time.monotonic()
            reported = started
            with path.open("xb") as output:
                while done < length:
                    if time.monotonic() - started > 600:
                        raise ValueError("PC upload exceeded ten-minute limit")
                    if self._cancelled(ident):
                        raise ValueError("Upload cancelled")
                    chunk = stream.read(min(CHUNK, length - done))
                    if not chunk:
                        raise ValueError("Upload interrupted")
                    output.write(chunk)
                    hasher.update(chunk)
                    done += len(chunk)
                    if time.monotonic() - reported > .25:
                        self._update(ident, done=done)
                        reported = time.monotonic()
            if hasher.hexdigest() != digest:
                raise ValueError("Upload SHA-256 mismatch; nothing sent to console")
            info = cia_info(path)
            if info["titleId"] != title.lower():
                raise ValueError("CIA title does not match the approved title ID")
            self._update(ident, state="queued", total=length, version=info["version"])
            self.pool.submit(self._deploy, ident, path)
            return {"ok": True, "id": ident}
        except Exception as exc:
            cancelled = self._cancelled(ident)
            self._update(ident, state="cancelled" if cancelled else "failed",
                         detail="PC upload cancelled; no console install requested" if cancelled else
                         str(exc) if isinstance(exc, ValueError) else "Local upload interrupted")
            path.unlink(missing_ok=True)
            raise ValueError(self.jobs[ident]["detail"]) from None

    def download(self, data):
        url = data.get("url")
        parts = urlsplit(url) if isinstance(url, str) else None
        if not parts or parts.scheme != "https" or not parts.hostname or parts.username or parts.password \
                or parts.fragment or parts.port not in (None, 443) or len(url) > 2048:
            raise ValueError("Use a final public HTTPS URL on port 443 without embedded credentials")
        ident = self.new_job(data.get("sha256"), data.get("titleId"), data.get("install", False))
        self.pool.submit(self._download, ident, url)
        return {"ok": True, "id": ident}

    def _cancelled(self, ident):
        with self.lock:
            return self.stop_event.is_set() or self.jobs[ident].get("cancelRequested", False)

    def _download(self, ident, url):
        path = self.root / (ident + ".cia")
        try:
            self._update(ident, state="downloading")
            opener = build_opener(ProxyHandler({}), PublicHTTPSHandler(), NoRedirect())
            digest, done = hashlib.sha256(), 0
            started = time.monotonic()
            with opener.open(Request(url, headers={"User-Agent": "RemotePilot-Homebrew/1"}), timeout=10) as response, path.open("xb") as output:
                if response.status != 200:
                    raise ValueError("Download did not return HTTP 200")
                length = response.headers.get("Content-Length")
                if length and (not length.isdigit() or not 0 < int(length) <= MAX_CIA):
                    raise ValueError("Download exceeds size limit")
                while True:
                    if self._cancelled(ident):
                        self._update(ident, state="cancelled", detail="PC download stopped; no install requested")
                        return
                    if time.monotonic() - started > 600:
                        raise ValueError("Download exceeded ten-minute limit")
                    chunk = response.read(CHUNK)
                    if not chunk:
                        break
                    done += len(chunk)
                    if done > MAX_CIA:
                        raise ValueError("Download exceeds 512 MiB")
                    digest.update(chunk)
                    output.write(chunk)
                    self._update(ident, done=done, total=int(length) if length else 0)
            if digest.hexdigest() != self.jobs[ident]["sha256"]:
                raise ValueError("Downloaded SHA-256 mismatch; nothing sent to console")
            info = cia_info(path)
            if info["titleId"] != self.jobs[ident]["titleId"]:
                raise ValueError("Downloaded CIA title ID mismatch")
            self._update(ident, total=done, version=info["version"])
            self._deploy(ident, path)
        except Exception as exc:
            self._update(ident, state="failed", detail=str(exc) if isinstance(exc, ValueError) else "HTTPS download failed")
        finally:
            path.unlink(missing_ok=True)

    def _deploy(self, ident, path):
        remote_started = False
        try:
            job = self.jobs[ident]
            if self._cancelled(ident):
                self._update(ident, state="cancelled")
                return
            self._require("upload")
            self._require_armed()
            body = f"{ident} {job['total']} {job['sha256']} {job['titleId']} {job['version']}".encode()
            if job.get('approvalMode') == 'autonomous':
                body += b' autonomous'
            remote_started = True
            try:
                self._send_once(ident, "begin", body, {'uploading'}, 0)
            except CompanionRejected as exc:
                self._update(ident, state='failed', done=0,
                             detail=str(exc) + '; console declined the transfer before receiving file data')
                return
            self._update(ident, state="uploading", done=0)
            done = 0
            transfer_chunk = CHUNK if self.remote.get('buildVersion', 0) >= 4 else TRANSFER_CHUNK
            with path.open("rb") as source:
                while chunk := source.read(transfer_chunk):
                    if self._cancelled(ident):
                        value = self.client.call("cancel", ident.encode())
                        self._update(ident, state=value["job"]["state"], detail="Console cancellation acknowledged")
                        return
                    self._send_once(ident, "chunk", f"{ident} {done}\n".encode() + chunk, {'uploading'}, done + len(chunk))
                    done += len(chunk)
                    self._update(ident, done=done)
            self._update(ident, state="verifying")
            self._send_once(ident, "verify", ident.encode(), {'verifying','verified'})
            # Verification runs incrementally on device; status remains available.
            self._wait_remote(ident, {"verified"}, 180)
            if not job["install"]:
                self._update(ident, state="uploaded", detail="Console SHA-256 verified; no installation requested")
                return
            response = self._send_once(ident, "install", ident.encode(), {'awaiting-approval','rechecking','installing','committing','installed'})
            remote_job = response.get('job', {})
            phase = remote_job.get('state', 'awaiting-approval')
            if phase not in {'awaiting-approval','rechecking','installing','committing','installed'}:
                raise ValueError('Unexpected install response; inspect console outcome')
            self._update(ident, state=phase, approvalMode=remote_job.get('approvalMode', 'manual'),
                         detail='On the console, approve this title/version/hash with A; B rejects' if phase == 'awaiting-approval' else
                         'Autonomous installation authorized for this console session; checking the outcome')
            self._wait_remote(ident, {"installed"}, 900)
            self._update(ident, state="installed", done=job['total'], detail="AM finished and installed version independently checked")
        except RemoteOutcome:
            pass
        except Exception as exc:
            self._update(ident, state="unknown" if remote_started else "failed",
                         detail=str(exc) if isinstance(exc, ValueError) else "Deployment interrupted; inspect console job")
        finally:
            path.unlink(missing_ok=True)  # generated PC spool only; original owner file is never changed

    def _send_once(self, ident, action, body, states, done=None):
        """A missing acknowledgement never resends a mutation.

        An authenticated, exact-job receipt can prove it already happened. For
        chunks the exact next byte offset is required. Otherwise stop unknown.
        No install completion is invented; the device checks AM + its inventory.
        """
        try:
            return self.client.call(action, body)
        except CompanionInterrupted as original:
            value = self.client.call('job', ident.encode())
            remote, local = value.get('job', {}), self.jobs[ident]
            if remote.get('id') != ident or remote.get('titleId') != local['titleId'] or \
                    remote.get('version') != local['version'] or remote.get('total') != local['total'] or \
                    remote.get('state') not in states or done is not None and remote.get('done') != done:
                raise original
            self._update(ident, detail='Console receipt confirmed this step; no command was resent')
            return value

    def _wait_remote(self, ident, wanted, seconds):
        started = time.monotonic()
        deadline = started + seconds
        hard_deadline = started + max(seconds, 4 * 60 * 60)
        previous_state, previous_done = None, 0
        advancing = {'verifying', 'rechecking', 'installing', 'committing'}
        while time.monotonic() < min(deadline, hard_deadline) and not self.stop_event.wait(.4):
            if self._cancelled(ident):
                self.client.call("cancel", ident.encode())
            value = self.client.call("job", ident.encode())["job"]
            state = value["state"]
            if state in wanted:
                return value
            if state in {"failed", "cancelled", "unknown"}:
                self._update(ident, state=state, detail="Console job ended: " + str(value.get("error", state))[:64])
                raise RemoteOutcome(state)
            done = value.get('done', 0)
            # Large native hashes can exceed three minutes while progressing.
            # Only real phase/byte advancement renews the inactivity deadline;
            # repeated status replies and waiting for A never extend it.
            if state in advancing and (state != previous_state or done > previous_done):
                deadline = time.monotonic() + seconds
            previous_state, previous_done = state, done
            self._update(ident, state=state, done=value.get("done", 0), approvalMode=value.get('approvalMode', 'manual'))
        raise ValueError("Job timeout waiting for progress or approval; inspect console status; no automatic retry")

    def homebrew_request(self, action, data):
        if action.startswith("diag-"):
            return self.diagnostics.request(action, data)
        if action.startswith("data-"):
            return self.data.request(action, data)
        if action == "status":
            return self.snapshot()
        if action == "configure":
            existing = self.config_path.exists()
            path = self.configure(data.get("host"), data.get("port", 38765))
            return {"ok": True, "pairingFile": path.name, "existingPairing": existing}
        if action == "download":
            if data.get("install") is True and "install" not in self.remote.get("capabilities", []):
                raise ValueError("Companion does not advertise install")
            return self.download(data)
        if action == "update":
            kind = data.get('kind')
            if kind not in ('companion', 'updater'):
                raise ValueError('Choose the companion or recovery updater')
            info = self.available_updates().get(kind)
            if not info: raise ValueError('A verified local update build is not available')
            name = 'RemotePilotHomebrew.cia' if kind == 'companion' else 'RemotePilotUpdater.cia'
            # No request supplies a filesystem path; receive_file independently
            # rehashes and parses the exact bytes before any console transfer.
            with (self.update_root / name).open('rb') as src:
                return self.receive_file(src, info['size'], info['sha256'], info['titleId'], True)
        if action == "titles":
            self._require("titles")
            value = self.client.call("titles")
            rows = value.get("titles")
            if not isinstance(rows, list) or len(rows) > 512 or any(not isinstance(row, dict) or
                    title_id(row.get("titleId")) != row.get("titleId") or type(row.get("version")) is not int for row in rows):
                raise ValueError("Invalid companion title inventory")
            with self.lock:
                self.titles = rows
            return {"ok": True, "titles": rows}
        if action == "cancel":
            ident = data.get("id")
            with self.lock:
                if ident not in self.jobs or self.jobs[ident]["state"] in TERMINAL:
                    raise ValueError("No active job with that ID")
                self.jobs[ident]["cancelRequested"] = True
            return {"ok": True, "detail": "Cancellation requested; await console outcome"}
        if action == "inspect":
            ident = data.get("id")
            if not isinstance(ident, str) or not re.fullmatch(r"[0-9a-f]{32}", ident):
                raise ValueError("Invalid job ID")
            if ident in self.jobs and self.jobs[ident].get("applicationTitleId", COMPANION_TITLE) != self.remote.get("applicationTitleId", COMPANION_TITLE):
                raise ValueError("Open the application that handled this job before inspecting its receipt")
            value = self.client.call("job", ident.encode())
            if ident in self.jobs:
                self._update(ident, **{k: v for k, v in value["job"].items() if k in ("state", "done", "error")})
            return value
        if action == "launch":
            self._require("launch")
            self._require_armed()
            title = title_id(data.get("titleId"))
            running = self.remote.get("applicationTitleId", COMPANION_TITLE)
            if title == running or (running == UPDATER_TITLE and title != COMPANION_TITLE):
                raise ValueError("Cannot launch this title from the current companion mode")
            if data.get("preset") not in (None, "", "morrowind", "halo"):
                raise ValueError("Unsupported game handoff target")
            if title in (COMPANION_TITLE, UPDATER_TITLE) and data.get("preset"):
                raise ValueError("Companion updates use the homebrew connection, without a game handoff")
            with self.lock:
                if (self.data.busy() or self.diagnostics.busy()) or any(j["state"] not in TERMINAL for j in self.jobs.values()):
                    raise ValueError("Finish or cancel the deployment before launching")
            self.system.release()
            ident = secrets.token_hex(16)
            with self.lock:
                self.jobs[ident] = {"id": ident, "state": "sending-launch", "titleId": title,
                                    "applicationTitleId": running,
                                    "detail": "Awaiting launch preparation acknowledgement"}
                self._save()
            # Prepare acknowledgment only. Actual APT outcome requires the new transport.
            try:
                value = self.client.call("launch", f"{ident} {title}".encode())
            except ValueError:
                self._update(ident, state="unknown", detail="Launch acknowledgement lost; inspect console; never retry automatically")
                raise
            if value.get("state") != "launching":
                self._update(ident, state="unknown", detail="Unexpected launch response; inspect console")
                raise ValueError("Console did not acknowledge launch preparation")
            target_detail = "paired target companion" if title in (COMPANION_TITLE, UPDATER_TITLE) else "selected game's paired transport"
            self._update(ident, state="launching", detail="APT prepared; await " + target_detail)
            with self.lock:
                self.handoff = {"state": "launching", "titleId": title, "preset": data.get("preset"),
                                "requestId": ident, "detail": "Launch prepared; waiting for " + target_detail}
                self.handoff_at = time.monotonic()
                self.connected = False
            return {"ok": True, "state": "launching", "preset": data.get("preset")}
        if action == "system-arm":
            if data.get("enabled") is False:
                self.system.release()
            elif data.get("enabled") is True and data.get("inputRedirectionEnabled") is True and self.client:
                with self.lock:
                    if (self.data.busy() or self.diagnostics.busy()) or any(j["state"] not in TERMINAL for j in self.jobs.values()):
                        raise ValueError("System input stays off during deployment and console approval")
                self.system.arm(self.client.host, data.get("owner"), data.get("version"))
            else:
                raise ValueError("Confirm InputRedirection is enabled manually on the console")
            return {"ok": True}
        if action == "system-input":
            touch = data.get("touch")
            if touch is not None and (not isinstance(touch, list) or len(touch) != 2):
                raise ValueError("Invalid touch sample")
            return self.system.pulse(data.get("owner"), data.get("button", "NONE"), data.get("home", False),
                                     touch, data.get("milliseconds", 100))
        if action == "system-release":
            self.system.release()
            return {"ok": True, "delivery": "unacknowledged"}
        raise ValueError("Unsupported homebrew action")

    def request(self, kind, payload):
        raise ValueError("Companion actions use the homebrew capability contract")

    def disconnect(self):
        self.system.release()

    def stop(self):
        self.stop_event.set()
        self.system.release()
        self.pool.shutdown(wait=False, cancel_futures=True)


class RemoteOutcome(ValueError):
    pass
