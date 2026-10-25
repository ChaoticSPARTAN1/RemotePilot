"""Integrity, auth, capability and failure tests. C++ AM calls are simulated."""
import hashlib
import io
import http.client
import json
import os
from pathlib import Path
import secrets
import socket
import struct
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from homebrew_protocol import CHUNK, CompanionClient, CompanionInterrupted, CompanionRejected, cia_info
from homebrew_runtime import HomebrewAdapter, COMPANION_TITLE, UPDATER_TITLE
from luma_input import LumaInput, packet
from plugin_runtime import PluginRuntime

ROOT = Path(__file__).resolve().parent
COMPANION = ROOT.parent / 'companion' if (ROOT.parent / 'companion').is_dir() else ROOT.parent / "RemotePilot-Homebrew"
HOST = COMPANION / "build/companion-host.exe"
UPDATER_HOST = COMPANION / "build/updater-host.exe"
TITLE = '000400000f3d5500'


def cia(version=1, title=TITLE, content=512):
    align = lambda n: (n + 63) & ~63
    cert, ticket, tmd = 0xa00, 0x350, 0x140 + 0xc4 + 0x900 + 0x30
    tmd_at = align(align(align(0x2020) + cert) + ticket)
    content_at = align(tmd_at + tmd)
    data = bytearray(align(content_at + content))
    struct.pack_into('<IHHIIIIQ', data, 0, 0x2020, 0, 0, cert, ticket, tmd, 0, content)
    struct.pack_into('>I', data, tmd_at, 0x10004)
    at = tmd_at + 0x140
    data[at + 0x4c:at + 0x54] = bytes.fromhex(title)
    struct.pack_into('>HH', data, at + 0x9c, version, 1)
    return bytes(data)


class LocalTests(unittest.TestCase):
    def test_https_download_rejects_private_dns_and_pins_public_tls(self):
        from homebrew_download import PublicHTTPSConnection
        from unittest.mock import Mock
        for address in ('127.0.0.1','192.168.1.1','169.254.169.254','10.0.0.1','::1','::ffff:127.0.0.1','ff02::1'):
            with self.subTest(address=address), patch('homebrew_download.socket.getaddrinfo',return_value=[(2,1,6,'',(address,443))]), \
                    patch('homebrew_download.socket.create_connection') as connect:
                with self.assertRaisesRegex(ValueError,'public Internet'):
                    PublicHTTPSConnection('builds.example',timeout=10).connect()
                connect.assert_not_called()
        connection = PublicHTTPSConnection('builds.example',timeout=10)
        self.assertTrue(connection._context.check_hostname)
        import ssl
        self.assertEqual(connection._context.verify_mode,ssl.CERT_REQUIRED)
        context, raw = Mock(), Mock()
        connection._context = context
        with patch('homebrew_download.socket.getaddrinfo',return_value=[(2,1,6,'',('93.184.216.34',443))]), \
                patch('homebrew_download.socket.create_connection',return_value=raw) as connect:
            connection.connect()
            connect.assert_called_once_with(('93.184.216.34',443),10,None)
            context.wrap_socket.assert_called_once_with(raw,server_hostname='builds.example')

    def test_https_download_rejects_mixed_public_private_dns(self):
        from homebrew_download import PublicHTTPSConnection
        addresses=[(2,1,6,'',('93.184.216.34',443)),(2,1,6,'',('10.0.0.1',443))]
        with patch('homebrew_download.socket.getaddrinfo',return_value=addresses),patch('homebrew_download.socket.create_connection') as connect:
            with self.assertRaises(ValueError):PublicHTTPSConnection('builds.example',timeout=10).connect()
            connect.assert_not_called()

    def test_large_hash_progress_renews_wait_without_resending_commands(self):
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as folder:
            adapter = HomebrewAdapter(folder, {})
            ident = 'a' * 32
            adapter.jobs[ident] = {'id':ident, 'state':'verifying'}
            adapter.client = Mock()
            adapter.client.call.side_effect = [
                {'job':{'state':'verifying','done':n}} for n in range(1, 7)
            ] + [{'job':{'state':'verified','done':7}}]
            adapter.stop_event = Mock()
            adapter.stop_event.wait.return_value = False
            adapter.stop_event.is_set.return_value = False
            # Each read advances a simulated minute: total hashing exceeds the
            # old absolute three-minute limit, with steady authenticated progress.
            ticks = iter(range(0, 3000, 60))
            with patch('homebrew_runtime.time.monotonic', side_effect=lambda:next(ticks)):
                result = adapter._wait_remote(ident, {'verified'}, 180)
            self.assertEqual(result['state'], 'verified')
            self.assertEqual([call.args[0] for call in adapter.client.call.call_args_list], ['job'] * 7)
            adapter.stop()

    def test_unchanged_progress_and_waiting_for_approval_expire(self):
        from unittest.mock import Mock
        for state in ('verifying', 'awaiting-approval'):
            with self.subTest(state=state), tempfile.TemporaryDirectory() as folder:
                adapter = HomebrewAdapter(folder, {})
                ident = 'a' * 32
                adapter.jobs[ident] = {'id':ident, 'state':state}
                adapter.client = Mock()
                adapter.client.call.return_value = {'job':{'state':state,'done':5}}
                adapter.stop_event = Mock()
                adapter.stop_event.wait.return_value = False
                adapter.stop_event.is_set.return_value = False
                ticks = iter(range(0, 3000, 60))
                with patch('homebrew_runtime.time.monotonic', side_effect=lambda:next(ticks)):
                    with self.assertRaisesRegex(ValueError, 'Job timeout'):
                        adapter._wait_remote(ident, {'installed'}, 180)
                self.assertLessEqual(adapter.client.call.call_count, 3)
                self.assertTrue(all(call.args[0] == 'job' for call in adapter.client.call.call_args_list))
                adapter.stop()

    def test_unreviewed_console_receipt_blocks_pc_upload(self):
        with tempfile.TemporaryDirectory() as folder:
            adapter = HomebrewAdapter(folder, {})
            adapter.client = CompanionClient('127.0.0.1', 38765, '0' * 64)
            adapter.connected = True
            adapter.remote = {'armed':True, 'capabilities':['upload'], 'job':{'state':'unknown'}}
            with self.assertRaisesRegex(ValueError, 'previous console outcome'):
                adapter.new_job('0' * 64, TITLE)
            self.assertEqual(adapter.jobs, {})
            adapter.stop()

    def test_explicit_begin_refusal_is_not_uncertain_or_retried(self):
        with tempfile.TemporaryDirectory() as folder:
            adapter = HomebrewAdapter(folder, {})
            adapter.client = CompanionClient('127.0.0.1', 38765, '0' * 64)
            adapter.connected = True
            adapter.remote = {'armed':True, 'capabilities':['upload']}
            ident = adapter.new_job('0' * 64, TITLE)
            adapter._update(ident, total=len(cia()), version=1)
            path = Path(folder) / (ident + '.cia'); path.write_bytes(cia())
            with patch.object(CompanionClient, 'call', side_effect=CompanionRejected('Companion: job-already-active-or-unknown')) as call:
                adapter._deploy(ident, path)
            self.assertEqual(call.call_count, 1)
            self.assertEqual(adapter.jobs[ident]['state'], 'failed')
            self.assertEqual(adapter.jobs[ident]['done'], 0)
            self.assertFalse(path.exists())
            adapter.stop()

    def test_cia_rejects_truncated_system_and_wrong_layout(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'test.cia'
            path.write_bytes(cia(42))
            self.assertEqual(cia_info(path)['version'], 42)
            path.write_bytes(cia()[:-100])
            with self.assertRaises(ValueError): cia_info(path)
            path.write_bytes(cia(title='0004013800000002'))
            with self.assertRaises(ValueError): cia_info(path)

    def test_system_packet_known_neutral_home_and_touch(self):
        self.assertEqual(packet(), struct.pack('<5I', 0xfff, 0x2000000, 0x7ff7ff, 0x80800081, 0))
        self.assertEqual(struct.unpack('<5I', packet('A', True))[-1], 1)
        self.assertEqual(struct.unpack('<5I', packet('UP'))[0], 0xfff ^ 0x40)
        self.assertEqual(struct.unpack('<5I', packet(touch=[160, 120]))[1], 0x01000000 | 2047 | (2047 << 12))
        for args in ({'button': 'HOME'}, {'home': 'true'}, {'touch': [320, 10]}):
            with self.assertRaises(ValueError): packet(**args)

    def test_luma_hold_finishes_with_neutral_and_lease_expires(self):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as listener:
            listener.bind(('127.0.0.1', 4950)); listener.settimeout(1)
            luma = LumaInput(lambda: True)
            luma.arm('127.0.0.1', 'a' * 32, '13.4')
            luma.pulse('a' * 32, home=True, milliseconds=20)
            self.assertEqual(struct.unpack('<5I', listener.recv(64))[-1], 1)
            for _ in range(3): self.assertEqual(listener.recv(64), packet())
            luma.expiry = 0
            with self.assertRaises(ValueError): luma.pulse('a' * 32)
            luma.allowed = lambda: False
            with self.assertRaises(ValueError): luma.arm('127.0.0.1', 'a' * 32, '13.4')

    def test_capabilities_do_not_expand_game_actions(self):
        runtime = PluginRuntime({'id': 'example'}, ROOT / 'presets', ROOT / 'build/test-homebrew')
        with self.assertRaises(ValueError): runtime.homebrew_request('launch', {})
        with self.assertRaises(ValueError): runtime.request('system-home', '-')

    def test_pc_hash_failure_never_calls_console(self):
        with tempfile.TemporaryDirectory() as folder:
            adapter = HomebrewAdapter(folder, {})
            adapter.connected = True
            adapter.client = CompanionClient('127.0.0.1', 38765, '0' * 64)
            adapter.remote = {'armed': True, 'capabilities': ['upload']}
            with patch.object(CompanionClient, 'call', side_effect=AssertionError('no console traffic')):
                with self.assertRaisesRegex(ValueError, 'SHA-256 mismatch'):
                    adapter.receive_file(io.BytesIO(cia()), len(cia()), '0' * 64, TITLE, False)
            self.assertEqual(next(iter(adapter.jobs.values()))['state'], 'failed')
            adapter.stop()

    def test_restart_does_not_resume_mutation(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'jobs.json'
            path.write_text(json.dumps([{'id': 'a' * 32, 'state': 'installing'}]))
            adapter = HomebrewAdapter(folder, {})
            self.assertEqual(adapter.snapshot()['jobs'][0]['state'], 'interrupted')
            adapter.stop()

    def test_lost_install_and_launch_ack_are_not_retried(self):
        class LostAck:
            def __init__(self): self.calls = []
            def call(self, action, body=b''):
                self.calls.append(action)
                raise ValueError('Acknowledgement lost')
        with tempfile.TemporaryDirectory() as folder:
            adapter = HomebrewAdapter(folder, {})
            adapter.client = LostAck(); adapter.connected = True
            adapter.remote = {'armed': True, 'capabilities': ['upload', 'launch']}
            data = cia()
            result = adapter.receive_file(io.BytesIO(data), len(data), hashlib.sha256(data).hexdigest(), TITLE, False)
            end = time.monotonic() + 2
            while adapter.jobs[result['id']]['state'] != 'unknown' and time.monotonic() < end: time.sleep(.01)
            self.assertEqual(adapter.jobs[result['id']]['state'], 'unknown')
            self.assertEqual(adapter.client.calls, ['begin'])
            with self.assertRaises(ValueError): adapter.homebrew_request('launch', {'titleId': TITLE})
            self.assertEqual(adapter.client.calls, ['begin', 'launch'])
            self.assertEqual(list(adapter.jobs.values())[-1]['state'], 'unknown')
            adapter.stop()

    def test_deployment_releases_and_blocks_system_injection(self):
        with tempfile.TemporaryDirectory() as folder:
            adapter = HomebrewAdapter(folder, {})
            adapter.client = CompanionClient('127.0.0.1', 38765, '0' * 64)
            adapter.connected = True
            adapter.remote = {'armed': True, 'capabilities': ['upload', 'install']}
            adapter.set_active(lambda: True)
            with patch.object(adapter.system, 'release') as release:
                adapter.new_job('0' * 64, TITLE, True)
                release.assert_called_once()
            with self.assertRaisesRegex(ValueError, 'during deployment'):
                adapter.homebrew_request('system-arm', {'enabled': True, 'inputRedirectionEnabled': True,
                                                       'owner': 'a' * 32, 'version': '13.4'})
            adapter.stop()

    def test_https_download_wrong_hash_never_reaches_console(self):
        class Response(io.BytesIO):
            status = 200
            headers = {'Content-Length': str(len(cia()))}
        class Opener:
            def open(self, request, timeout):
                return Response(cia())
        with tempfile.TemporaryDirectory() as folder:
            adapter = HomebrewAdapter(folder, {})
            adapter.client = CompanionClient('127.0.0.1', 38765, '0' * 64)
            adapter.connected = True
            adapter.remote = {'armed': True, 'capabilities': ['upload', 'install']}
            with patch('homebrew_runtime.build_opener', return_value=Opener()), \
                    patch.object(CompanionClient, 'call', side_effect=AssertionError('no console traffic')):
                result = adapter.download({'url': 'https://builds.example.invalid/test.cia',
                                           'sha256': '0' * 64, 'titleId': TITLE, 'install': True})
                end = time.monotonic() + 2
                while adapter.jobs[result['id']]['state'] != 'failed' and time.monotonic() < end: time.sleep(.01)
                self.assertEqual(adapter.jobs[result['id']]['state'], 'failed')
                self.assertIn('SHA-256 mismatch', adapter.jobs[result['id']]['detail'])
            adapter.stop()
            self.assertFalse(list(adapter.root.glob('*.cia')))

    def test_update_routing_legacy_main_and_recovery_restrictions(self):
        with tempfile.TemporaryDirectory() as folder:
            adapter = HomebrewAdapter(folder, {})
            adapter.client = CompanionClient('127.0.0.1', 38765, '0' * 64)
            adapter.connected = True
            adapter.remote = {'armed': True, 'capabilities': ['upload', 'install', 'launch']}
            # Legacy main status has no explicit identity. Still never send self.
            with self.assertRaisesRegex(ValueError, 'Open RemotePilot Updater'):
                adapter.new_job('0' * 64, COMPANION_TITLE, True)
            ident = adapter.new_job('0' * 64, UPDATER_TITLE, True)
            adapter._update(ident, state='installed')
            adapter.remote.update(applicationTitleId=UPDATER_TITLE, updater=True, updateTarget=COMPANION_TITLE)
            with self.assertRaisesRegex(ValueError, 'only the RemotePilot'):
                adapter.new_job('0' * 64, TITLE, True)
            with self.assertRaisesRegex(ValueError, 'running title'):
                adapter.new_job('0' * 64, UPDATER_TITLE, True)
            ident = adapter.new_job('0' * 64, COMPANION_TITLE, True)
            adapter._update(ident, state='installed')
            self.assertTrue(adapter.snapshot()['updater'])
            with self.assertRaisesRegex(ValueError, 'without a game handoff'):
                adapter.homebrew_request('launch', {'titleId': COMPANION_TITLE, 'preset': 'morrowind'})
            adapter.stop()

    def test_update_handoff_confirms_target_identity_not_any_connection(self):
        class Service:
            def __init__(self): self.identity = COMPANION_TITLE
            def call(self, action):
                return {'ok': True, 'protocol': 1, 'capabilities': ['upload', 'install', 'launch'],
                        'applicationTitleId': self.identity, 'buildVersion': 16, 'updater': True,
                        'updateTarget': COMPANION_TITLE, 'armed': False}
        with tempfile.TemporaryDirectory() as folder:
            adapter = HomebrewAdapter(folder, {})
            service = Service(); service.host = '127.0.0.1'; adapter.client = service
            adapter.handoff = {'titleId': UPDATER_TITLE, 'state': 'launching'}
            adapter.status()
            self.assertEqual(adapter.handoff['state'], 'launching')
            service.identity = UPDATER_TITLE; adapter.last_poll = 0
            adapter.status()
            self.assertEqual(adapter.handoff['state'], 'updater')
            self.assertEqual(adapter.snapshot()['applicationTitleId'], UPDATER_TITLE)
            self.assertEqual(adapter.snapshot()['buildVersion'], 16)
            service.identity = TITLE; adapter.last_poll = 0
            adapter.status(); self.assertFalse(adapter.connected)
            adapter.stop()

    def test_local_update_catalog_requires_exact_build_receipts_and_fixed_kind(self):
        with tempfile.TemporaryDirectory() as folder:
            adapter = HomebrewAdapter(Path(folder)/'pc', {})
            adapter.update_root = Path(folder)/'updates'; adapter.update_root.mkdir()
            receipt={'files':{}}
            for name,title,section in [('RemotePilotHomebrew.cia',COMPANION_TITLE,'cia'),('RemotePilotUpdater.cia',UPDATER_TITLE,'updater')]:
                data=cia(4,title); (adapter.update_root/name).write_bytes(data)
                receipt[section]={'titleId':title,'version':4}
                receipt['files'][name]={'size':len(data),'sha256':hashlib.sha256(data).hexdigest()}
            (adapter.update_root/'verification.json').write_text(json.dumps(receipt))
            self.assertEqual(set(adapter.available_updates()),{'companion','updater'})
            with patch.object(adapter,'receive_file',return_value={'ok':True}) as receive:
                adapter.homebrew_request('update',{'kind':'updater'})
                self.assertEqual(receive.call_args.args[3],UPDATER_TITLE)
                self.assertIs(receive.call_args.args[4],True)
            with self.assertRaises(ValueError):adapter.homebrew_request('update',{'kind':'../private'})
            (adapter.update_root/'RemotePilotUpdater.cia').write_bytes(cia(5,UPDATER_TITLE))
            self.assertEqual(adapter.available_updates(),{})
            adapter.stop()

    def test_unknown_deployment_blocks_new_update_until_inspected(self):
        with tempfile.TemporaryDirectory() as folder:
            adapter=HomebrewAdapter(folder,{})
            adapter.client=CompanionClient('127.0.0.1',38765,'0'*64)
            adapter.connected=True;adapter.remote={'armed':True,'capabilities':['upload','install']}
            ident=adapter.new_job('0'*64,TITLE,True);adapter._update(ident,state='unknown')
            self.assertEqual(adapter.snapshot()['state'],'unknown')
            with self.assertRaisesRegex(ValueError,'Inspect the previous'):
                adapter.new_job('0'*64,TITLE,True)
            adapter.connected=False;self.assertFalse(adapter.snapshot()['armed'])
            adapter.stop()

    def test_transport_retries_reads_but_never_resends_a_mutation(self):
        client=CompanionClient('127.0.0.1',38765,'0'*64)
        with patch.object(client,'_call',side_effect=[CompanionInterrupted('reset'),{'ok':True}]) as call:
            self.assertTrue(client.call('status')['ok']);self.assertEqual(call.call_count,2)
        with patch.object(client,'_call',side_effect=[CompanionInterrupted('reset')]*5+[{'ok':True}]) as call:
            self.assertTrue(client.call('job')['ok']);self.assertEqual(call.call_count,6)
        with patch.object(client,'_call',side_effect=CompanionInterrupted('reset')) as call:
            with self.assertRaises(CompanionInterrupted):client.call('begin',b'test')
            self.assertEqual(call.call_count,1)
        with patch.object(client,'_call',side_effect=ValueError('proof failed')) as call:
            with self.assertRaises(ValueError):client.call('status')
            self.assertEqual(call.call_count,1)

    def test_lost_chunk_ack_continues_only_after_exact_authenticated_offset(self):
        class Service:
            def __init__(self,job):self.remote=job;self.calls=[]
            def call(self,action,body):
                self.calls.append(action)
                if action=='chunk':raise CompanionInterrupted('reset')
                return {'ok':True,'job':self.remote}
        with tempfile.TemporaryDirectory() as folder:
            adapter=HomebrewAdapter(folder,{})
            ident='a'*32
            adapter.jobs[ident]={'id':ident,'state':'uploading','titleId':TITLE,'version':7,'total':50000}
            remote={'id':ident,'state':'uploading','titleId':TITLE,'version':7,'total':50000,'done':16384}
            adapter.client=Service(remote)
            adapter._send_once(ident,'chunk',b'exact bytes',{'uploading'},16384)
            self.assertEqual(adapter.client.calls,['chunk','job'])
            remote['done']=0;adapter.client.calls=[]
            with self.assertRaises(CompanionInterrupted):adapter._send_once(ident,'chunk',b'exact bytes',{'uploading'},16384)
            self.assertEqual(adapter.client.calls,['chunk','job'])
            remote.update(done=16384,id='b'*32)
            with self.assertRaises(CompanionInterrupted):adapter._send_once(ident,'chunk',b'exact bytes',{'uploading'},16384)
            adapter.stop()


class HomebrewHTTPTests(unittest.TestCase):
    def test_partial_http_request_expires_without_dispatch(self):
        with patch.object(self.receiver.Viewer,'io_timeout',.08):
            with socket.create_connection(self.server.server_address,timeout=2) as client:
                client.sendall(b'GET /api/homebrew/status HTTP/1.1\r\nHost: ')
                self.assertEqual(client.recv(1024),b'')

    def setUp(self):
        import receiver
        self.receiver = receiver
        self.temp = tempfile.TemporaryDirectory()
        manifest = json.loads((ROOT / 'presets/homebrew/manifest.json').read_text())
        self.runtime = PluginRuntime(manifest, ROOT / 'presets', self.temp.name)
        self.patch = patch.multiple(receiver, plugin_runtimes={'homebrew': self.runtime}, selected_preset='example', link_enabled=True)
        self.patch.start()
        self.server = receiver.ThreadingHTTPServer(('127.0.0.1', 0), receiver.Viewer)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True); self.thread.start()

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join()
        self.runtime.stop(); self.patch.stop(); self.temp.cleanup()

    def call(self, path, body=None, headers=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=2)
        conn.request('GET' if body is None else 'POST', path, body, headers or {})
        response = conn.getresponse(); result = response.status, response.read(); conn.close(); return result

    def test_homebrew_status_coexists_with_example_and_csrf_gate(self):
        status, body = self.call('/api/homebrew/status')
        self.assertEqual(status, 200)
        self.assertFalse(json.loads(body)['connected'])
        self.assertEqual(self.call('/api/homebrew/configure', b'{}')[0], 403)
        headers = {'X-Remote-Pilot-Viewer': '1', 'Content-Type': 'application/json'}
        self.assertEqual(self.call('/api/homebrew/system-power', b'{}', headers)[0], 400)
        headers['Origin'] = 'https://untrusted.invalid'
        self.assertEqual(self.call('/api/homebrew/status', None, headers)[0], 403)

    def test_raw_upload_enforces_install_capability_and_hash(self):
        adapter = self.runtime.adapter
        adapter.client = CompanionClient('127.0.0.1', 38765, '0' * 64)
        adapter.connected = True; adapter.remote = {'armed': True, 'capabilities': ['upload', 'install']}
        self.runtime.capabilities = frozenset({'homebrew', 'upload'})
        headers = {'X-Remote-Pilot-Viewer': '1', 'Content-Type': 'application/octet-stream',
                   'X-File-Sha256': '0' * 64, 'X-Title-Id': TITLE, 'X-Install': '1'}
        status, body = self.call('/api/homebrew/file', cia(), headers)
        self.assertEqual(status, 400); self.assertIn(b'does not advertise install', body)
        headers['X-Install'] = '0'
        status, body = self.call('/api/homebrew/file', cia(), headers)
        self.assertEqual(status, 400); self.assertIn(b'SHA-256 mismatch', body)
        self.assertEqual(list(adapter.jobs.values())[-1]['state'], 'failed')
        self.assertFalse(list(adapter.root.glob('*.cia')))
        with self.assertRaisesRegex(ValueError, 'install'):
            self.runtime.homebrew_request('download', {'install': True})
        with self.assertRaisesRegex(ValueError, 'install'):
            self.runtime.homebrew_request('update', {'kind': 'updater'})


@unittest.skipUnless(HOST.exists(), 'Build the desktop C++ simulator with build.ps1 -HostTests')
class CompanionTests(unittest.TestCase):
    executable = HOST
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=COMPANION / 'build', prefix='simulation-')
        self.root = Path(self.temp.name)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0)); self.port = sock.getsockname()[1]
        self.token = secrets.token_hex(32)
        (self.root / 'remote-pilot-homebrew.cfg').write_text(f'port={self.port}\ntoken={self.token}\n')
        self.client = CompanionClient('127.0.0.1', self.port, self.token)
        self.start()

    def start(self):
        env = os.environ.copy()
        env['PATH'] = r'C:\msys64\usr\bin;' + env['PATH']
        env['RPH_TEST_ROOT'] = self.root.as_posix()
        if hasattr(self, 'titleStore'): env['RPH_TEST_TITLE_STORE'] = self.titleStore.as_posix()
        arguments = [str(self.executable), self.root.as_posix()]
        if hasattr(self, 'configRoot'): arguments.append(self.configRoot.as_posix())
        self.process = subprocess.Popen(arguments, env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        self.wait(lambda: self.client.call('status')['protocol'] == 1)

    def tearDown(self):
        self.process.terminate(); self.process.wait(timeout=5); self.temp.cleanup()

    def wait(self, test, seconds=8):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            try:
                value = test()
                if value: return value
            except (OSError, ValueError): pass
            time.sleep(.02)
        self.fail('Expected simulation state was not reached')

    def key(self, key):
        (self.root / 'test-key').write_text(str(key))
        self.wait(lambda: not (self.root / 'test-key').exists())

    def clock_offset(self, milliseconds):
        # The simulated monotonic clock must never briefly read a truncated
        # file as zero. Publish each complete offset atomically on every OS.
        target=self.root/'test-clock-offset'
        temporary=target.with_suffix('.tmp')
        temporary.write_text(str(milliseconds))
        deadline=time.monotonic()+2
        while True:
            try:
                temporary.replace(target)
                return
            except PermissionError:
                if time.monotonic()>=deadline:raise
                time.sleep(.005)

    def upload(self, data, digest=None, autonomous=False):
        ident = secrets.token_hex(16)
        with tempfile.NamedTemporaryFile(dir=self.root, suffix='.cia', delete=False) as output:
            output.write(data); path = Path(output.name)
        info = cia_info(path)
        body = f"{ident} {len(data)} {digest or hashlib.sha256(data).hexdigest()} {info['titleId']} {info['version']}".encode()
        if autonomous: body += b' autonomous'
        self.client.call('begin', body)
        for at in range(0, len(data), CHUNK):
            self.client.call('chunk', f'{ident} {at}\n'.encode() + data[at:at + CHUNK])
        self.client.call('verify', ident.encode())
        return ident

    def job(self, ident): return self.client.call('job', ident.encode())['job']

    def test_acknowledged_failure_returns_both_apps_to_ready_and_survives_restart(self):
        for executable, title in ((HOST, TITLE), (UPDATER_HOST, COMPANION_TITLE)):
            with self.subTest(app=executable.name):
                self.process.terminate(); self.process.wait(timeout=5)
                self.executable = executable; self.start(); self.key(4)
                ident = self.upload(cia(8, title), digest='0' * 64)
                self.wait(lambda:self.job(ident)['state'] == 'failed')
                self.assertFalse(self.job(ident)['reviewed'])
                self.wait(lambda:(self.root / 'test-dashboard.txt').read_text().startswith('TRANSFER STOPPED\n'))
                self.key(2)
                self.wait(lambda:self.client.call('status')['readyForTransfer'])
                result = self.job(ident)
                self.assertTrue(result['reviewed'])
                self.assertEqual((result['state'],result['error']),('failed','sha256-mismatch'))
                self.wait(lambda:(self.root / 'test-dashboard.txt').read_text().startswith('READY FOR TRANSFER\n\n0\n'))
                self.process.terminate(); self.process.wait(timeout=5); self.start()
                self.assertTrue(self.job(ident)['reviewed'])
                self.assertFalse(self.client.call('status')['armed'])
                self.wait(lambda:(self.root / 'test-dashboard.txt').read_text().startswith('READY FOR TRANSFER\n\n0\n'))

    def test_legacy_owner_acknowledgement_is_ready_without_erasing_receipt(self):
        self.process.terminate(); self.process.wait(timeout=5)
        ident = 'a' * 32
        legacy = f"{ident} {'0'*64} {TITLE} failed owner-reviewed-unknown-outcome 100 100 1\n"
        (self.root / 'receipt.txt').write_text(legacy)
        self.start(); self.key(4)
        self.assertTrue(self.client.call('status')['readyForTransfer'])
        self.assertTrue(self.job(ident)['reviewed'])
        self.assertEqual((self.root / 'receipt.txt').read_text(),legacy)
        self.wait(lambda:(self.root / 'test-dashboard.txt').read_text().startswith('READY FOR TRANSFER\n\n0\n'))

    def test_partial_and_malformed_receipts_fail_closed_without_resuming(self):
        prefix=f"{'a'*32} {'0'*64} {TITLE}"
        for value in (prefix+' installing none 100',prefix+' installed none -1 0 1',
                      prefix+' installed none 100 100 999999',prefix+' failed bad\"error 100 100 1',
                      prefix+' failed none 100 100 1 manual garbage','x'*2048,''):
            with self.subTest(value=value[:70]):
                self.process.terminate();self.process.wait(timeout=5)
                (self.root/'receipt.txt').write_text(value)
                self.start()
                result=self.client.call('status')['job']
                self.assertEqual((result['state'],result['error']),('unknown','invalid-receipt'))
                self.assertFalse(result['reviewed'])
                self.key(4)
                self.assertFalse(self.client.call('status')['readyForTransfer'])
                self.key(2)
                self.assertTrue(self.client.call('status')['readyForTransfer'])
                self.assertEqual(self.client.call('titles')['titles'],[])

    def test_uncommitted_temporary_receipt_takes_precedence_over_completed_one(self):
        self.process.terminate();self.process.wait(timeout=5)
        prefix=f"{'a'*32} {'0'*64} {TITLE}"
        (self.root/'receipt.txt').write_text(prefix+' installed none 100 100 1 manual reviewed\n')
        (self.root/'receipt.tmp').write_text(prefix+' installing none 100 20 2 manual pending\n')
        self.start()
        result=self.client.call('status')['job']
        self.assertEqual((result['state'],result['error'],result['version']),('unknown','uncommitted-receipt',2))
        self.assertFalse(result['reviewed'])

    def test_autonomous_owner_opt_in_explicit_job_and_manual_fallback(self):
        self.assertTrue(self.client.call('status')['autonomousSupported'])
        self.key(16); self.assertFalse(self.client.call('status')['autonomousEnabled'])
        self.key(4)
        with self.assertRaisesRegex(ValueError,'enable-autonomous-on-console'):
            self.upload(cia(2),autonomous=True)
        self.key(16); self.assertTrue(self.client.call('status')['autonomousEnabled'])
        ident=self.upload(cia(2),autonomous=True)
        self.wait(lambda:self.job(ident)['state']=='verified')
        self.client.call('install',ident.encode())
        self.wait(lambda:self.job(ident)['state']=='installed') # no A press
        self.assertEqual(self.job(ident)['approvalMode'],'autonomous')
        self.key(16)
        self.assertIn('autonomous',(self.root/'receipt.txt').read_text())
        self.key(16)
        legacy=self.upload(cia(3)) # old clients remain manual even when mode is on
        self.wait(lambda:self.job(legacy)['state']=='verified')
        self.client.call('install',legacy.encode())
        self.assertEqual(self.job(legacy)['state'],'awaiting-approval')
        self.assertEqual(self.job(legacy)['approvalMode'],'manual')
        self.key(1);self.wait(lambda:self.job(legacy)['state']=='installed')

    def test_autonomous_revocation_and_restart_remove_permission(self):
        self.key(4);self.key(16)
        ident=self.upload(cia(2),autonomous=True)
        self.wait(lambda:self.job(ident)['state']=='verified')
        self.key(16)
        self.client.call('install',ident.encode())
        self.assertEqual(self.job(ident)['state'],'awaiting-approval')
        self.assertEqual(self.client.call('titles')['titles'],[])
        self.key(1);self.wait(lambda:self.job(ident)['state']=='installed')
        self.key(16)
        self.process.terminate();self.process.wait(timeout=5);self.start()
        status=self.client.call('status')
        self.assertFalse(status['armed']);self.assertFalse(status['autonomousEnabled'])
        self.key(4);self.key(16);self.key(4)
        self.assertFalse(self.client.call('status')['autonomousEnabled'])

    def test_autonomous_hash_failure_and_unknown_finish_still_stop(self):
        self.key(4);self.key(16)
        ident=self.upload(cia(2),'0'*64,autonomous=True)
        self.wait(lambda:self.job(ident)['state']=='failed')
        self.assertEqual(self.job(ident)['error'],'sha256-mismatch')
        self.assertEqual(self.client.call('titles')['titles'],[])
        ident=self.upload(cia(2),autonomous=True)
        self.wait(lambda:self.job(ident)['state']=='verified')
        (self.root/'test-finish-fail').write_text('1')
        self.client.call('install',ident.encode())
        self.wait(lambda:self.job(ident)['state']=='unknown')
        self.process.terminate();self.process.wait(timeout=5);self.start()
        self.assertEqual(self.job(ident)['state'],'unknown')
        self.key(4);self.key(16)
        self.assertFalse(self.client.call('status')['autonomousEnabled'])
        with self.assertRaisesRegex(ValueError,'unknown'):self.upload(cia(3))

    def test_pc_pipeline_autonomous_installs_without_per_job_a(self):
        self.key(4);self.key(16)
        adapter=HomebrewAdapter(self.root/'pc',{})
        adapter.client=self.client;adapter.connected=True;adapter.remote=self.client.call('status')
        data=cia(2)
        try:
            result=adapter.receive_file(io.BytesIO(data),len(data),hashlib.sha256(data).hexdigest(),TITLE,True)
            self.wait(lambda:adapter.jobs[result['id']]['state']=='installed')
            job=adapter.jobs[result['id']]
            self.assertEqual(job['approvalMode'],'autonomous')
            self.assertEqual(job['done'],len(data))
            self.assertIn({'titleId':TITLE,'version':2},self.client.call('titles')['titles'])
        finally:adapter.stop()

    def test_long_active_transfer_renews_session_but_idle_expires_auto(self):
        self.key(4);self.key(16)
        data=cia(2,content=140000);ident=secrets.token_hex(16)
        self.client.call('begin',f"{ident} {len(data)} {hashlib.sha256(data).hexdigest()} {TITLE} 2 autonomous".encode())
        for number,at in enumerate(range(0,len(data),CHUNK),1):
            self.clock_offset(number*14*60*1000)
            self.client.call('chunk',f'{ident} {at}\n'.encode()+data[at:at+CHUNK])
        self.client.call('verify',ident.encode())
        self.wait(lambda:self.job(ident)['state']=='verified')
        self.assertTrue(self.client.call('status')['armed'])
        self.assertTrue(self.client.call('status')['autonomousEnabled'])
        self.client.call('install',ident.encode())
        self.wait(lambda:self.job(ident)['state']=='installed')
        self.clock_offset((number*14+16)*60*1000)
        self.wait(lambda:not self.client.call('status')['armed'])
        self.assertFalse(self.client.call('status')['autonomousEnabled'])

    @unittest.skipUnless(UPDATER_HOST.exists(), 'Build recovery updater simulator')
    def test_autonomous_updater_remains_restricted_to_companion(self):
        self.process.terminate();self.process.wait(timeout=5)
        self.executable=UPDATER_HOST;self.start();self.key(4);self.key(16)
        with self.assertRaisesRegex(ValueError,'invalid-deployment'):self.upload(cia(2),autonomous=True)
        ident=self.upload(cia(2,COMPANION_TITLE),autonomous=True)
        self.wait(lambda:self.job(ident)['state']=='verified')
        self.client.call('install',ident.encode())
        self.wait(lambda:self.job(ident)['state']=='installed')
        self.assertIn({'titleId':COMPANION_TITLE,'version':2},self.client.call('titles')['titles'])

    def test_reopened_companion_replaces_reviewed_receipt_before_new_upload(self):
        self.key(4)
        old = self.upload(cia())
        self.wait(lambda: self.job(old)['state'] == 'verified')
        self.client.call('cancel',old.encode())
        self.process.terminate(); self.process.wait(timeout=5)
        self.start(); self.key(4)
        self.assertEqual(self.job(old)['state'],'cancelled')
        new = self.upload(cia(2))
        self.wait(lambda:self.job(new)['state']=='verified')
        fields=(self.root/'receipt.txt').read_text().split()
        self.assertEqual(fields[0],new)
        self.assertEqual(fields[3],'verified')

    def test_auth_unarmed_and_system_title_rejection(self):
        wrong = CompanionClient('127.0.0.1', self.port, '1' * 64)
        with self.assertRaisesRegex(ValueError, 'proof failed'): wrong.call('status')
        with self.assertRaisesRegex(ValueError, 'arm-on-console'): self.upload(cia())
        self.assertFalse((self.root / 'staged.cia').exists())
        self.key(4)
        for title in ('0004013800000002', '000400000f3d5200'):
            body = f"{'a'*32} 10000 {'0'*64} {title} 1".encode()
            with self.assertRaisesRegex(ValueError, 'invalid-deployment'): self.client.call('begin', body)

    def test_hash_mismatch_does_not_install(self):
        self.key(4)
        ident = self.upload(cia(), '0' * 64)
        self.wait(lambda: self.job(ident)['state'] == 'failed')
        self.assertEqual(self.job(ident)['error'], 'sha256-mismatch')
        with self.assertRaisesRegex(ValueError, 'verify-before-install'): self.client.call('install', ident.encode())
        self.assertEqual(self.client.call('titles')['titles'], [])

    @unittest.skipUnless(UPDATER_HOST.exists(), 'Build recovery updater simulator')
    def test_wireless_bootstrap_recovery_update_and_return_with_shared_pairing(self):
        # Start with the owner's main bootstrap. All transitions below are
        # simulated process changes; the host never claims an actual APT jump.
        self.process.terminate(); self.process.wait(timeout=5)
        self.titleStore = self.root / 'test-installed-titles'
        self.titleStore.write_text(f'{COMPANION_TITLE} 0\n')
        self.start(); self.key(4)
        ident = self.upload(cia(1, UPDATER_TITLE))
        self.wait(lambda: self.job(ident)['state'] == 'verified')
        self.client.call('install', ident.encode()); self.key(1)
        self.wait(lambda: self.job(ident)['state'] == 'installed')
        self.process.terminate(); self.process.wait(timeout=5)
        main_root = self.root
        self.configRoot = main_root
        self.root = main_root / 'recovery-updater'; self.root.mkdir()
        self.executable = UPDATER_HOST
        self.start()
        status = self.client.call('status')
        self.assertEqual(status['applicationTitleId'], UPDATER_TITLE)
        self.assertEqual(status['updateTarget'], COMPANION_TITLE)
        self.assertTrue(status['updater']); self.assertFalse(status['armed'])
        self.assertFalse((self.root / 'remote-pilot-homebrew.cfg').exists())
        with self.assertRaisesRegex(ValueError, 'arm-on-console'): self.upload(cia(2, COMPANION_TITLE))
        self.key(4)
        for title in (TITLE, UPDATER_TITLE, '0004013800000002'):
            with self.assertRaisesRegex(ValueError, 'invalid-deployment'):
                self.client.call('begin', f"{'c'*32} 10000 {'0'*64} {title} 1".encode())
        ident = self.upload(cia(2, COMPANION_TITLE))
        self.wait(lambda: self.job(ident)['state'] == 'verified')
        self.client.call('install', ident.encode())
        self.assertEqual(self.job(ident)['state'], 'awaiting-approval')
        self.assertIn({'titleId': COMPANION_TITLE, 'version': 0}, self.client.call('titles')['titles'])
        self.key(1); self.wait(lambda: self.job(ident)['state'] == 'installed')
        for version in (2, 1):
            rejected = self.upload(cia(version, COMPANION_TITLE))
            self.wait(lambda: self.job(rejected)['state'] == 'failed')
            self.assertEqual(self.job(rejected)['error'], 'same-or-older-version')
        with self.assertRaisesRegex(ValueError, 'invalid-launch'):
            self.client.call('launch', f"{'d'*32} {TITLE}".encode())
        self.process.terminate(); self.process.wait(timeout=5)
        self.root = main_root; self.executable = HOST
        self.start()
        self.assertEqual(self.client.call('status')['applicationTitleId'], COMPANION_TITLE)
        self.assertIn({'titleId': COMPANION_TITLE, 'version': 2}, self.client.call('titles')['titles'])
        self.assertIn({'titleId': UPDATER_TITLE, 'version': 1}, self.client.call('titles')['titles'])

    @unittest.skipUnless(UPDATER_HOST.exists(), 'Build recovery updater simulator')
    def test_recovery_updater_failed_finish_stays_unknown_after_restart(self):
        self.process.terminate(); self.process.wait(timeout=5)
        self.executable = UPDATER_HOST; self.start(); self.key(4)
        ident = self.upload(cia(2, COMPANION_TITLE))
        self.wait(lambda: self.job(ident)['state'] == 'verified')
        (self.root / 'test-finish-fail').write_text('1')
        self.client.call('install', ident.encode()); self.key(1)
        self.wait(lambda: self.job(ident)['state'] == 'unknown')
        self.assertEqual(self.job(ident)['error'], 'install-finish-unconfirmed')
        self.process.terminate(); self.process.wait(timeout=5); self.start(); self.key(4)
        self.assertEqual(self.job(ident)['state'], 'unknown')
        with self.assertRaisesRegex(ValueError, 'unknown'):
            self.upload(cia(3, COMPANION_TITLE))

    def test_verified_approval_install_version_conflicts_and_launch_failure(self):
        self.key(4)
        ident = self.upload(cia(2))
        self.wait(lambda: self.job(ident)['state'] == 'verified')
        self.client.call('install', ident.encode())
        self.assertEqual(self.job(ident)['state'], 'awaiting-approval')
        self.assertEqual(self.client.call('titles')['titles'], [])
        self.key(1)
        self.wait(lambda: self.job(ident)['state'] == 'installed')
        for version in (2, 1):
            ident = self.upload(cia(version))
            self.wait(lambda: self.job(ident)['state'] == 'failed')
            self.assertEqual(self.job(ident)['error'], 'same-or-older-version')
            self.assertEqual(self.client.call('titles')['titles'], [{'titleId': TITLE, 'version': 2}])
        launch = secrets.token_hex(16)
        self.assertEqual(self.client.call('launch', f'{launch} {TITLE}'.encode())['state'], 'launching')
        self.wait(lambda: self.job(launch)['state'] == 'failed')
        self.assertEqual(self.job(launch)['error'], 'application-jump-failed')

    def test_cancel_out_of_order_and_reboot_outcome(self):
        self.key(4)
        ident = secrets.token_hex(16)
        body = f"{ident} 10000 {'0'*64} {TITLE} 1".encode()
        self.client.call('begin', body)
        with self.assertRaisesRegex(ValueError, 'out-of-order'): self.client.call('chunk', f'{ident} 1\na'.encode())
        self.assertEqual(self.client.call('cancel', ident.encode())['job']['state'], 'cancelled')
        ident = secrets.token_hex(16)
        self.client.call('begin', f"{ident} 10000 {'0'*64} {TITLE} 1".encode())
        self.process.terminate(); self.process.wait(timeout=5)
        self.start()
        self.assertEqual(self.job(ident)['state'], 'unknown')
        self.assertFalse(self.job(ident)['reviewed'])
        self.assertFalse(self.client.call('status')['armed'])
        self.key(4)
        self.assertFalse(self.client.call('status')['readyForTransfer'])
        with self.assertRaisesRegex(ValueError, 'unknown'): self.client.call('begin', body)
        self.key(2)
        self.assertEqual(self.job(ident)['state'], 'failed')
        self.assertTrue(self.job(ident)['reviewed'])
        self.assertTrue(self.client.call('status')['readyForTransfer'])

    def test_pc_job_end_to_end_against_cpp_service(self):
        self.key(4)
        adapter = HomebrewAdapter(self.root / 'pc', {})
        adapter.client = self.client
        adapter.status()
        data = cia(3)
        result = adapter.receive_file(io.BytesIO(data), len(data), hashlib.sha256(data).hexdigest(), TITLE, True)
        ident = result['id']
        self.wait(lambda: adapter.jobs[ident]['state'] == 'awaiting-approval')
        self.key(1)
        self.wait(lambda: adapter.jobs[ident]['state'] == 'installed')
        self.assertEqual(adapter.homebrew_request('titles', {})['titles'][0]['version'], 3)
        adapter.stop()

    def test_am_finish_failure_is_unknown_and_approval_rehashes(self):
        self.key(4)
        ident = self.upload(cia(4))
        self.wait(lambda: self.job(ident)['state'] == 'verified')
        with (self.root / 'staged.cia').open('r+b') as staged:
            staged.seek(-1, 2); staged.write(b'!')
        self.client.call('install', ident.encode()); self.key(1)
        self.wait(lambda: self.job(ident)['state'] == 'failed')
        self.assertEqual(self.job(ident)['error'], 'sha256-mismatch')
        self.assertEqual(self.client.call('titles')['titles'], [])
        ident = self.upload(cia(4))
        self.wait(lambda: self.job(ident)['state'] == 'verified')
        (self.root / 'test-finish-fail').write_text('1')
        self.client.call('install', ident.encode()); self.key(1)
        self.wait(lambda: self.job(ident)['state'] == 'unknown')
        self.assertEqual(self.job(ident)['error'], 'install-finish-unconfirmed')
        self.assertEqual(self.client.call('titles')['titles'], [])


if __name__ == '__main__': unittest.main()
