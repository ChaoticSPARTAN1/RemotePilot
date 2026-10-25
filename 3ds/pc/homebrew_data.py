"""Private registered game-data packages and checked, fast LAN deployment."""
import hashlib
import json
from pathlib import Path
import re
import secrets
import threading
import time

from homebrew_protocol import CompanionInterrupted

MAX_FILE = 2**31 - 1  # compatible with 32-bit stdio on the console
MAX_TOTAL = 64 * 1024**3
WINDOW = 4 * 1024**2
FINAL = {'complete', 'failed', 'cancelled', 'interrupted', 'unknown'}
PROTECTED = {'save', 'saves', 'savegame', 'local', 'private', 'luma', 'boot9strap', 'gm9',
             'nintendo 3ds', 'dcim', 'cias', 'remotepilothomebrew', 'remotepilotupdater',
             'token', 'pairing.json', 'credentials.json', 'secrets.json'}


def safe_path(value, target=False):
    if not isinstance(value, str) or not value or len(value) > (128 if target else 224):
        raise ValueError('Invalid game-data path')
    parts = value.split('/')
    if len(parts) > 16:
        raise ValueError('Game-data path is too deep')
    for part in parts:
        stem = part.lower().split('.')[0]
        if not re.fullmatch(r'[A-Za-z0-9_ .-]{1,96}', part) or part.startswith('.') or part.endswith(('.', ' ')) or \
                part.lower() in PROTECTED or 'remote-pilot' in part.lower() or \
                stem in {'con', 'prn', 'aux', 'nul'} or re.fullmatch(r'(com|lpt)[1-9]', stem):
            raise ValueError('Protected or unsafe game-data path')
    if target:
        if parts[0].lower() == '3ds' and (len(parts) != 3 or parts[-1].lower() != 'data'):
            raise ValueError('3ds targets must be limited to an application data subfolder')
    elif Path(value).suffix.lower() in {'.cia', '.3dsx', '.firm', '.exe', '.dll', '.ps1', '.bat', '.cmd', '.key', '.pem'}:
        raise ValueError('Executables and credentials do not belong in data packages')
    return value


def digest(path):
    with path.open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def register(folder, target, name, registry):
    folder = Path(folder).expanduser().resolve()
    safe_path(target, True)
    if not folder.is_dir() or not isinstance(name, str) or not 1 <= len(name) <= 80 or any(ord(c) < 32 for c in name):
        raise ValueError('Choose a data directory and a short display name')
    rows, seen, total = [], set(), 0
    for path in sorted(folder.rglob('*')):
        if path.is_symlink() or not path.resolve().is_relative_to(folder):
            raise ValueError('Data packages cannot follow symlinks')
        if not path.is_file():
            continue
        relative = safe_path(path.relative_to(folder).as_posix())
        if relative.casefold() in seen:
            raise ValueError('Case-ambiguous data filenames')
        seen.add(relative.casefold())
        size = path.stat().st_size
        total += size
        if size > MAX_FILE or total > MAX_TOTAL or len(rows) >= 8192:
            raise ValueError('Data package exceeds FAT32/file-count limits')
        rows.append({'path': relative, 'size': size, 'sha256': digest(path)})
    if not rows:
        raise ValueError('Data package is empty')
    ident = secrets.token_hex(16)
    value = {'id': ident, 'name': name, 'targetRoot': target, 'folder': str(folder), 'files': rows, 'total': total}
    registry = Path(registry)
    registry.mkdir(parents=True, exist_ok=True)
    (registry / (ident + '.json')).write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')
    return {key: value[key] for key in ('id', 'name', 'targetRoot', 'total')}


class DataManager:
    def __init__(self, adapter):
        self.adapter = adapter
        self.root = adapter.root
        self.registry = self.root / 'data-packages'
        self.journal = self.root / 'data-job.json'
        self.lock = threading.RLock()
        self.job = {}
        try:
            self.job = json.loads(self.journal.read_text())
            if self.job.get('state') not in FINAL:
                self.job.update(state='interrupted', detail='Receiver restarted; inspect the console before retrying')
        except (OSError, ValueError):
            pass

    def busy(self):
        return bool(self.job) and self.job.get('state') not in FINAL

    def update(self, **fields):
        with self.lock:
            self.job.update(fields)
            temporary = self.journal.with_suffix('.tmp')
            temporary.write_text(json.dumps(self.job, indent=2) + '\n')
            temporary.replace(self.journal)

    def load(self, ident):
        if not isinstance(ident, str) or not re.fullmatch('[0-9a-f]{32}', ident):
            raise ValueError('Select a registered data package')
        path = self.registry / (ident + '.json')
        if path.is_symlink():
            raise ValueError('Unsafe data package registration')
        value = json.loads(path.read_text())
        safe_path(value['targetRoot'], True)
        if value.get('id') != ident or not 1 <= len(value['files']) <= 8192:
            raise ValueError('Invalid data registration')
        seen, total = set(), 0
        for row in value['files']:
            safe_path(row['path'])
            if row['path'].casefold() in seen or type(row['size']) is not int or not 0 <= row['size'] <= MAX_FILE or \
                    not re.fullmatch('[0-9a-f]{64}', row['sha256']):
                raise ValueError('Invalid data manifest')
            seen.add(row['path'].casefold()); total += row['size']
        if total != value['total'] or total > MAX_TOTAL:
            raise ValueError('Invalid package size')
        return value

    def snapshot(self):
        packages = []
        if self.registry.is_dir():
            for path in sorted(self.registry.glob('*.json'))[:64]:
                try:
                    value = self.load(path.stem)
                    packages.append({key: value[key] for key in ('id', 'name', 'targetRoot', 'total')})
                    packages[-1]['fileCount'] = len(value['files'])
                except (OSError, ValueError, KeyError, TypeError):
                    continue
        with self.lock:
            job = dict(self.job)
        return {'packages': packages, 'job': job, 'fast': True,
                'supported': self.adapter.connected and 'data-transfer' in self.adapter.remote.get('capabilities', [])}

    def start(self, ident):
        adapter = self.adapter
        adapter._require('data-transfer'); adapter._require_armed()
        package = self.load(ident)
        if adapter.diagnostics.busy() or self.busy() or self.job.get('state') in {'unknown', 'interrupted'} or \
                any(job['state'] not in {'uploaded', 'installed', 'cancelled', 'failed', 'launching'} for job in adapter.jobs.values()):
            raise ValueError('Finish or review the existing deployment before starting game data')
        if not adapter.remote.get('fastDataTransfer'):
            raise ValueError('Update the main companion for fast checked game-data transfers')
        self.job = {}
        self.update(id=secrets.token_hex(16), state='queued', name=package['name'], package=ident,
                    targetRoot=package['targetRoot'], total=package['total'], done=0, filesDone=0,
                    fileCount=len(package['files']), fast=True, wireBytes=0, transferSeconds=0,
                    verificationSeconds=0, detail='Registered game assets; saves/settings are excluded')
        adapter.system.release()
        adapter.pool.submit(self.deploy, package)
        return {'ok': True, 'id': self.job['id']}

    def remote(self, ident, row, target):
        value = self.adapter.client.call('data-status', ident.encode())['dataJob']
        if value.get('id') != ident or value.get('path') != row['path'] or value.get('total') != row['size'] or \
                value.get('sha256') != row['sha256'] or value.get('targetRoot') != target:
            raise ValueError('Exact data receipt did not match the requested file')
        if value.get('state') in {'failed', 'cancelled'}:
            raise ValueError('Console data job stopped: ' + str(value.get('error', 'unknown'))[:64])
        return value

    def wait(self, ident, row, target, accepted):
        deadline, previous = time.monotonic() + 180, None
        while not self.adapter.stop_event.wait(.12):
            if self.job.get('cancelRequested'):
                self.adapter.client.call('data-cancel', ident.encode())
                raise ValueError('Game-data transfer cancelled; destination files preserved')
            value = self.remote(ident, row, target)
            if value['state'] in accepted:
                return value
            if (value['state'], value['done']) != previous:
                deadline = time.monotonic() + 180
            previous = value['state'], value['done']
            if time.monotonic() > deadline:
                raise ValueError('Data check stopped progressing; inspect console')
        raise ValueError('Receiver stopping; no retry was sent')

    def deploy(self, package):
        completed, wire, upload_time, checking_time = 0, 0, 0.0, 0.0
        try:
            folder = Path(package['folder']).resolve()
            for number, row in enumerate(package['files']):
                if self.job.get('cancelRequested') or self.adapter.stop_event.is_set():
                    self.update(state='cancelled', detail='Stopped before the next file; committed files preserved')
                    return
                source = folder / row['path']
                if source.is_symlink() or not source.resolve().is_relative_to(folder) or source.stat().st_size != row['size'] or digest(source) != row['sha256']:
                    raise ValueError('Registered source data changed; prepare a new package')
                ident = secrets.token_hex(16)
                self.update(state='checking', activeFile=row['path'], activeId=ident, fileDone=0)
                body = f"{ident} {row['size']} {row['sha256']}\n{package['targetRoot']}\n{row['path']}".encode('ascii')
                started = time.monotonic()
                self.adapter.client.call('data-begin', body)
                result = self.wait(ident, row, package['targetRoot'], {'receiving', 'present'})
                checking_time += time.monotonic() - started
                if result['state'] != 'present':
                    self.update(state='uploading')
                    with source.open('rb') as handle:
                        offset = 0
                        while offset < row['size']:
                            if self.job.get('cancelRequested') or self.adapter.stop_event.is_set():
                                self.adapter.client.call('data-cancel', ident.encode())
                                self.update(state='cancelled', detail='Stopped; original destination files preserved')
                                return
                            size = min(WINDOW, row['size'] - offset)
                            started = time.monotonic()
                            try:
                                self.adapter.client.data_stream(ident, offset, handle, size)
                            except CompanionInterrupted:
                                result = self.remote(ident, row, package['targetRoot'])
                                if result['state'] != 'receiving' or result['done'] != offset + size:
                                    raise ValueError('Data stream outcome unclear; no batch was retried') from None
                            upload_time += time.monotonic() - started
                            offset += size; wire += size
                            result = self.remote(ident, row, package['targetRoot'])
                            if result['state'] != 'receiving' or result['done'] != offset:
                                raise ValueError('Console offset differs; stopped without resending data')
                            self.update(done=completed + offset, fileDone=offset, wireBytes=wire,
                                        transferSeconds=round(upload_time, 3), mibPerSecond=round(wire / max(upload_time, .001) / 1048576, 3))
                    self.update(state='verifying')
                    started = time.monotonic()
                    self.adapter.client.call('data-end', ident.encode())
                    self.wait(ident, row, package['targetRoot'], {'complete'})
                    checking_time += time.monotonic() - started
                completed += row['size']
                self.update(done=completed, filesDone=number + 1, verificationSeconds=round(checking_time, 3))
            self.update(state='complete', detail='All file SHA-256 checks passed on console; game data is ready')
        except (OSError, ValueError, KeyError, TypeError) as error:
            self.update(state='interrupted' if isinstance(error, CompanionInterrupted) else
                        ('cancelled' if self.job.get('cancelRequested') else 'failed'),
                        detail=('Local data access failed; check the registered package' if isinstance(error, OSError)
                                and not isinstance(error, CompanionInterrupted) else str(error)[:200]))

    def request(self, action, data):
        if action == 'data-start':
            return self.start(data.get('package'))
        if action == 'data-cancel':
            if not self.busy():
                raise ValueError('No active data deployment')
            self.update(cancelRequested=True)
            return {'ok': True}
        if action == 'data-review':
            if self.busy():
                raise ValueError('Wait for the active data operation to stop')
            remote = self.adapter.client.call('data-status').get('dataJob', {})
            if remote.get('state') in {'receiving', 'checking'}:
                raise ValueError('Console is still processing data; cancel or let it finish first')
            self.update(state='cancelled', detail='Owner reviewed the stopped data outcome; existing files remain preserved')
            return {'ok': True}
        raise ValueError('Unsupported data action')
