"""Read-only console diagnostics, verified locally and kept out of releases."""
import base64
import hashlib
import json
from pathlib import Path
import re
import secrets
import threading

MAX = 4 * 1024**2
ID = re.compile(r'[0-9a-f]{32}\Z')
SHA = re.compile(r'[0-9a-f]{64}\Z')
FIXED = {'doom3/log.txt', 'doom3/stack-near-limit.bin', '3ds/mw3ds/log.txt', '3ds/mw3ds/crash.txt', '3ds/mw3ds/watchdog.txt'}
IMAGES = {'luma/screenshots', 'doom3/screenshots', '3ds/mw3ds/screenshots', '3ds/mw3ds/bug-it', '3ds/RemotePilotHomebrew/bug-images'}
DUMPS = {'luma/dumps/arm11', 'luma/dumps/arm9'}


def validate(row):
    if not isinstance(row, dict) or not isinstance(row.get('id'), str) or not ID.fullmatch(row['id']) or \
            type(row.get('size')) is not int or not 0 <= row['size'] <= MAX:
        raise ValueError('Invalid diagnostic catalog')
    path = row.get('path', '')
    if not isinstance(path, str): raise ValueError('Invalid diagnostic name')
    folder, _, name = path.rpartition('/')
    if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,95}', name):
        raise ValueError('Invalid diagnostic name')
    kind = 'text' if (path in FIXED and path.endswith('.txt')) or (folder=='3ds/mw3ds/bug-it' and (name=='crash.txt' or re.fullmatch(r'logs-[A-Za-z0-9_.-]+\.txt', name))) else 'dump' if path in FIXED else \
        'dump' if folder in DUMPS and re.fullmatch(r'crash_dump_[A-Za-z0-9_.-]+\.dmp', name) else \
        'image' if folder in IMAGES and Path(name).suffix.lower() in {'.png', '.bmp', '.jpg', '.jpeg'} else None
    if kind != row.get('kind') or hashlib.sha256(path.encode('ascii')).hexdigest()[:32] != row['id']:
        raise ValueError('Unapproved diagnostic source')
    return {k: row[k] for k in ('id', 'path', 'kind', 'size')}


class DiagnosticsManager:
    def __init__(self, adapter):
        self.adapter = adapter
        self.lock = threading.RLock()
        self.files = []
        self.job = {}
        self.results = {}

    def busy(self):
        return self.job.get('state') == 'collecting'

    def snapshot(self):
        with self.lock:
            return {'files': list(self.files), 'job': dict(self.job),
                    'supported': self.adapter.connected and 'diagnostics' in self.adapter.remote.get('capabilities', [])}

    def gate(self):
        a = self.adapter
        a._require('diagnostics'); a._require_armed()
        if self.busy() or a.data.busy() or any(j['state'] not in {'uploaded','installed','cancelled','failed','launching'} for j in a.jobs.values()):
            raise ValueError('Finish or review the current operation before reading diagnostics')

    def request(self, action, data):
        a = self.adapter
        if action == 'diag-result':
            ident = data.get('id')
            if not isinstance(ident, str) or not ID.fullmatch(ident) or ident not in self.results:
                raise ValueError('Diagnostic result is unavailable')
            row, path, expected = self.results[ident]
            if path.is_symlink() or path.stat().st_size > MAX:
                raise ValueError('Diagnostic copy changed')
            content = path.read_bytes()
            if hashlib.sha256(content).hexdigest() != expected:
                raise ValueError('Diagnostic copy changed')
            return {'ok': True, **row, 'sha256': expected, 'base64': base64.b64encode(content).decode('ascii')}
        with a.lock:
            self.gate()
            if action == 'diag-list':
                rows = a.client.call('diag-list').get('files')
                if not isinstance(rows, list) or len(rows) > 128:
                    raise ValueError('Invalid diagnostic catalog')
                rows = [validate(row) for row in rows]
                if len({row['id'] for row in rows}) != len(rows):
                    raise ValueError('Duplicate diagnostic entries')
                with self.lock: self.files = rows
                return {'ok': True, 'files': rows}
            if action == 'diag-collect':
                ident = data.get('id')
                row = next((row for row in self.files if row['id'] == ident), None)
                if not row: raise ValueError('Refresh the diagnostic list and choose a file')
                a.system.release()
                with self.lock: self.job = {'state':'collecting', 'path':row['path'], 'done':0, 'total':row['size']}
                a.pool.submit(self.collect, dict(row), a.client)
                return {'ok': True}
        raise ValueError('Unsupported diagnostic action')

    def collect(self, row, client):
        temporary = None
        try:
            info = client.call('diag-open', row['id'].encode('ascii'))
            size, checksum = info.get('size'), info.get('sha256')
            if type(size) is not int or not 0 <= size <= MAX or not isinstance(checksum, str) or not SHA.fullmatch(checksum):
                raise ValueError('Invalid diagnostic snapshot')
            # A log can grow between listing and opening. The device freezes the
            # exact opened bytes in RAM; every chunk and the final file are hashed.
            row['size'] = size
            folder = self.adapter.root / 'diagnostics'
            if folder.is_symlink(): raise ValueError('Unsafe diagnostic destination')
            folder.mkdir(exist_ok=True)
            ident = secrets.token_hex(16)
            final = folder / (ident + Path(row['path']).suffix.lower())
            temporary = folder / (ident + '.part')
            digest = hashlib.sha256()
            with temporary.open('xb') as target:
                for offset in range(0, size, 32768):
                    count = min(32768, size-offset)
                    reply = client.call('diag-read', f'{checksum} {offset} {count}'.encode('ascii'))
                    value = reply.get('hex')
                    if reply.get('offset') != offset or not isinstance(value, str) or not re.fullmatch('[0-9a-f]{%d}' % (2*count), value):
                        raise ValueError('Invalid diagnostic chunk')
                    chunk = bytes.fromhex(value); target.write(chunk); digest.update(chunk)
                    with self.lock: self.job.update(done=offset+count, total=size)
            if digest.hexdigest() != checksum or hashlib.sha256(temporary.read_bytes()).hexdigest() != checksum:
                raise ValueError('Diagnostic checksum mismatch')
            temporary.replace(final)
            metadata = {**row, 'sha256':checksum, 'id':ident}
            final.with_suffix(final.suffix+'.json').write_text(json.dumps(metadata, indent=2)+'\n')
            with self.lock:
                self.results[ident] = (row, final, checksum)
                self.job.update(state='complete', id=ident, detail='Verified copy saved privately on this PC')
        except (OSError, ValueError, KeyError, TypeError):
            if temporary and temporary.exists(): temporary.unlink()
            with self.lock: self.job.update(state='failed', detail='Diagnostic collection failed; reconnect and refresh to try again')
        finally:
            try: client.call('diag-close')
            except (ValueError, OSError): pass
