"""Fast authenticated asset transfer across the real protocol and host C++ app."""
import hashlib
import io
from pathlib import Path
import secrets
import tempfile
import unittest
from unittest.mock import patch

import homebrew_protocol
from homebrew_data import register, safe_path, WINDOW
from homebrew_runtime import HomebrewAdapter
import test_homebrew as harness
from test_homebrew import HOST, UPDATER_HOST


class FastDataTests(unittest.TestCase):
    executable = HOST
    setUp = harness.CompanionTests.setUp
    start = harness.CompanionTests.start
    tearDown = harness.CompanionTests.tearDown
    wait = harness.CompanionTests.wait
    key = harness.CompanionTests.key

    def begin(self, data, path='packs/base.pak', target='example/data', checksum=None):
        ident = secrets.token_hex(16)
        checksum = checksum or hashlib.sha256(data).hexdigest()
        body = f'{ident} {len(data)} {checksum}\n{target}\n{path}'.encode()
        self.client.call('data-begin', body)
        return ident

    def upload(self, data, ident):
        source = io.BytesIO(data)
        for offset in range(0, len(data), WINDOW):
            self.client.data_stream(ident, offset, source, min(WINDOW, len(data)-offset))
        self.client.call('data-end', ident.encode())
        return self.wait(lambda: (job if (job := self.client.call('data-status', ident.encode())['dataJob'])['state'] in {'complete','failed'} else None))

    def test_multiple_windows_and_verified_commit(self):
        self.key(4)
        data = bytes(range(256)) * 17000 + b'last partial frame'
        ident = self.begin(data)
        self.assertEqual(self.upload(data, ident)['state'], 'complete')
        self.assertEqual((self.root/'test-game-data/example/data/packs/base.pak').read_bytes(),data)
        self.assertFalse(list((self.root/'test-game-data').rglob('*.part')))

    def test_matching_files_skipped_differing_files_never_overwritten(self):
        self.key(4)
        data=b'original-data'
        ident=self.begin(data);self.upload(data,ident)
        ident=self.begin(data)
        self.wait(lambda: self.client.call('data-status',ident.encode())['dataJob']['state']=='present')
        ident=self.begin(b'different!!!!')
        self.wait(lambda: self.client.call('data-status',ident.encode())['dataJob']['state']=='failed')
        self.assertEqual((self.root/'test-game-data/example/data/packs/base.pak').read_bytes(),data)

    def test_wrong_hash_and_tampered_proof_do_not_commit(self):
        self.key(4)
        data=b'untrusted payload'*100
        ident=self.begin(data,checksum='0'*64)
        self.assertEqual(self.upload(data,ident)['error'],'data-sha256-mismatch')
        self.assertFalse((self.root/'test-game-data/example/data/packs/base.pak').exists())
        ident=self.begin(data)
        actual_mac=homebrew_protocol.mac
        with patch('homebrew_protocol.mac',side_effect=lambda token,msg:'0'*64 if msg.startswith('data:') else actual_mac(token,msg)):
            with self.assertRaises((ValueError,OSError)):
                self.client.data_stream(ident,0,io.BytesIO(data),len(data))
        self.assertEqual(self.client.call('data-status',ident.encode())['dataJob']['state'],'failed')
        self.assertFalse((self.root/'test-game-data/example/data/packs/base.pak').exists())

    def test_protected_paths_and_unarmed_denied(self):
        with self.assertRaises(ValueError):self.begin(b'a')
        self.key(4)
        for target,path in [('luma','config.ini'),('3ds/RemotePilotHomebrew/data','pack.dat'),('doom3','../bad'),('doom3','save/slot.dat'),('doom3','app.cia'),('3ds','x.dat')]:
            with self.subTest(target=target,path=path),self.assertRaises(ValueError):self.begin(b'a',path,target)

    def test_disarm_cancels_without_committing(self):
        self.key(4)
        ident=self.begin(b'data')
        self.client.data_stream(ident,0,io.BytesIO(b'da'),2)
        self.key(4)
        self.assertEqual(self.client.call('data-status',ident.encode())['dataJob']['state'],'cancelled')
        self.assertFalse((self.root/'test-game-data/example/data/packs/base.pak').exists())

    def test_registered_package_manager_end_to_end_and_public_status(self):
        self.key(4)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            source=root/'assets';source.mkdir()
            (source/'pack.pak').write_bytes(b'asset bytes'*9000)
            adapter=HomebrewAdapter(root/'private',{})
            try:
                adapter.client=self.client
                adapter.status()
                package=register(source,'example/data','Owner assets',adapter.data.registry)
                adapter.data.start(package['id'])
                self.wait(lambda: adapter.data.job.get('state') in {'complete','failed','interrupted'})
                self.assertEqual(adapter.data.job['state'],'complete',adapter.data.job)
                self.assertEqual(adapter.data.job['wireBytes'],99000)
                self.assertGreater(adapter.data.job['mibPerSecond'],0)
                self.assertNotIn(str(source),str(adapter.data.snapshot()))
                adapter.data.start(package['id'])
                self.wait(lambda: adapter.data.job.get('state') in {'complete','failed','interrupted'})
                self.assertEqual(adapter.data.job['state'],'complete',adapter.data.job)
                self.assertEqual(adapter.data.job['wireBytes'],0)
            finally:adapter.stop()


class RecoveryDataTests(unittest.TestCase):
    executable=UPDATER_HOST
    setUp=harness.CompanionTests.setUp
    start=harness.CompanionTests.start
    tearDown=harness.CompanionTests.tearDown
    wait=harness.CompanionTests.wait
    def test_recovery_does_not_advertise_or_allow_game_data(self):
        self.assertNotIn('data-transfer',self.client.call('status')['capabilities'])
        with self.assertRaises(ValueError):self.client.call('data-status')


class RegistrationTests(unittest.TestCase):
    def test_paths_and_size_limits(self):
        for path in ('../escape','foo\\bar','save/slot','NUL.dat','3ds//foo','.hidden','thing.exe'):
            with self.subTest(path=path),self.assertRaises(ValueError):safe_path(path)
        safe_path('doom3/base',True);safe_path('3ds/example/data',True)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'source';source.mkdir()
            (source/'ok.pak').write_bytes(b'ok')
            value=register(source,'doom3/base','Package',root/'registry')
            self.assertNotIn('folder',value)

if __name__=='__main__':unittest.main()
