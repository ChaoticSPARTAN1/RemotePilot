"""Bounded diagnostic reads over the actual authenticated native protocol."""
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import test_homebrew as harness
from test_homebrew import HOST, UPDATER_HOST
from homebrew_protocol import CompanionClient
from homebrew_runtime import HomebrewAdapter
from homebrew_diagnostics import validate, MAX


class DiagnosticsTests(unittest.TestCase):
    executable = HOST
    setUp = harness.CompanionTests.setUp
    start = harness.CompanionTests.start
    tearDown = harness.CompanionTests.tearDown
    wait = harness.CompanionTests.wait
    key = harness.CompanionTests.key

    def fixture(self, path, data):
        target=self.root/'test-game-data'/path
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(data)
        return target

    def test_unarmed_and_unpaired_reads_rejected(self):
        self.fixture('doom3/log.txt',b'private log')
        with self.assertRaises(ValueError):self.client.call('diag-list')
        self.key(4)
        bad=CompanionClient(self.client.host,self.client.port,'f'*64)
        with self.assertRaises(ValueError):bad.call('diag-list')
        self.assertEqual(len(self.client.call('diag-list')['files']),1)

    def test_catalog_excludes_secrets_saves_oversized_and_traversal(self):
        self.key(4)
        self.fixture('doom3/log.txt',b'log')
        self.fixture('doom3/save/log.txt',b'save')
        self.fixture('3ds/RemotePilotHomebrew/remote-pilot-homebrew.cfg',b'secret')
        self.fixture('luma/dumps/arm11/crash_dump_00000002.dmp',b'dump')
        self.fixture('luma/screenshots/test.png',b'png')
        self.fixture('luma/screenshots/secrets.txt',b'private')
        self.fixture('doom3/stack-near-limit.bin',b'').write_bytes(b'x'*(MAX+1))
        rows=self.client.call('diag-list')['files']
        self.assertEqual({r['path'] for r in rows},{'doom3/log.txt','luma/dumps/arm11/crash_dump_00000002.dmp','luma/screenshots/test.png'})
        for row in rows:validate(row)
        for value in ('../doom3/log.txt','0'*32,'/doom3/log.txt'):
            with self.assertRaises(ValueError):self.client.call('diag-open',value.encode())

    def test_large_catalog_crosses_soc_send_boundary_with_valid_signed_reply(self):
        self.key(4)
        for folder in ('luma/screenshots','doom3/screenshots','3ds/mw3ds/screenshots','3ds/mw3ds/bug-it','3ds/RemotePilotHomebrew/bug-images'):
            for number in range(24):
                self.fixture(folder+'/'+('image_'+str(number).zfill(2)+'_'+'x'*70+'.png'),b'synthetic image fixture')
        reply=self.client.call('diag-list')
        self.assertEqual(len(reply['files']),120)
        import json
        self.assertGreater(len(json.dumps(reply).encode()),8192)
        for row in reply['files']:validate(row)

    def test_snapshot_stays_consistent_if_source_changes_and_never_writes_source(self):
        self.key(4);data=bytes(range(256))*140
        path=self.fixture('doom3/log.txt',data)
        row=self.client.call('diag-list')['files'][0]
        info=self.client.call('diag-open',row['id'].encode())
        self.assertEqual(path.read_bytes(),data)
        path.write_bytes(b'later log')
        received=b''
        for offset in range(0,len(data),32768):
            count=min(32768,len(data)-offset)
            received+=bytes.fromhex(self.client.call('diag-read',f"{info['sha256']} {offset} {count}".encode())['hex'])
        self.assertEqual(received,data)
        self.assertEqual(hashlib.sha256(received).hexdigest(),info['sha256'])
        self.client.call('diag-close')
        with self.assertRaises(ValueError):self.client.call('diag-read',f"{info['sha256']} 0 1".encode())
        self.assertEqual(path.read_bytes(),b'later log')

    def test_invalid_offsets_and_wrong_snapshot_rejected(self):
        self.key(4);self.fixture('doom3/log.txt',b'abc')
        row=self.client.call('diag-list')['files'][0];info=self.client.call('diag-open',row['id'].encode())
        for body in (f"{info['sha256']} 0 32769",f"{info['sha256']} 3 1",f"{info['sha256']} -1 1",f"{'0'*64} 0 1"):
            with self.assertRaises(ValueError):self.client.call('diag-read',body.encode())

    def test_bug_it_images_logs_and_watchdog_exclude_receiver_configuration(self):
        self.key(4)
        for path in ('3ds/mw3ds/bug-it/shot-12.bmp','3ds/mw3ds/bug-it/logs-123.txt','3ds/mw3ds/watchdog.txt'):
            self.fixture(path,b'example')
        self.fixture('3ds/mw3ds/bug-it/receiver.cfg',b'private pairing')
        rows=self.client.call('diag-list')['files']
        self.assertEqual(len(rows),3)
        for row in rows:validate(row)

    def test_live_deployment_blocks_reads_and_disarm_invalidates_snapshot(self):
        self.key(4);self.fixture('doom3/log.txt',b'abc')
        row=self.client.call('diag-list')['files'][0]
        info=self.client.call('diag-open',row['id'].encode())
        self.key(4);self.key(4)
        with self.assertRaises(ValueError):self.client.call('diag-read',f"{info['sha256']} 0 1".encode())
        ident='a'*32
        body=f"{ident} 3 {hashlib.sha256(b'abc').hexdigest()}\ndoom3/base\ntest.dat"
        self.client.call('data-begin',body.encode())
        with self.assertRaises(ValueError):self.client.call('diag-list')
        self.client.call('data-cancel',ident.encode())

    def test_private_collection_and_download_verified_end_to_end(self):
        self.key(4);data=b'<script>not HTML</script>\n'*4000
        path=self.fixture('doom3/log.txt',data)
        with tempfile.TemporaryDirectory() as folder:
            adapter=HomebrewAdapter(folder,{})
            adapter.client=self.client;adapter.connected=True;adapter.remote=self.client.call('status')
            rows=adapter.homebrew_request('diag-list',{})['files']
            adapter.homebrew_request('diag-collect',{'id':rows[0]['id']})
            state=self.wait(lambda:(j if (j:=adapter.diagnostics.snapshot()['job']).get('state')=='complete' else None))
            result=adapter.homebrew_request('diag-result',{'id':state['id']})
            import base64
            self.assertEqual(base64.b64decode(result['base64']),data)
            self.assertEqual(path.read_bytes(),data)
            self.assertNotIn('host',result);self.assertNotIn('token',result)
            with self.assertRaises(ValueError):adapter.homebrew_request('diag-result',{'id':'../companion'})
            adapter.stop()

    def test_pc_rejects_unapproved_catalog_and_corrupt_chunks(self):
        with self.assertRaises(ValueError):validate({'id':'0'*32,'path':'doom3/save/log.txt','kind':'text','size':4})
        self.key(4);self.fixture('doom3/log.txt',b'abc')
        with tempfile.TemporaryDirectory() as folder:
            adapter=HomebrewAdapter(folder,{})
            adapter.client=self.client;adapter.connected=True;adapter.remote=self.client.call('status')
            row=adapter.homebrew_request('diag-list',{})['files'][0]
            actual=self.client.call
            def corrupt(action,payload=b''):
                value=actual(action,payload)
                if action=='diag-read':value['hex']='00'*3
                return value
            with patch.object(self.client,'call',side_effect=corrupt):adapter.diagnostics.collect(row,self.client)
            self.assertEqual(adapter.diagnostics.job['state'],'failed')
            self.assertFalse(list((Path(folder)/'diagnostics').glob('*.txt')))
            self.assertFalse(list((Path(folder)/'diagnostics').glob('*.part')))
            adapter.stop()


class RecoveryDiagnosticsTests(unittest.TestCase):
    executable=UPDATER_HOST
    setUp=harness.CompanionTests.setUp
    start=harness.CompanionTests.start
    tearDown=harness.CompanionTests.tearDown
    wait=harness.CompanionTests.wait
    key=harness.CompanionTests.key
    def test_recovery_stays_update_only(self):
        self.key(4)
        self.assertNotIn('diagnostics',self.client.call('status')['capabilities'])
        with self.assertRaises(ValueError):self.client.call('diag-list')
