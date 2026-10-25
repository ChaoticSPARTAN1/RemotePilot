"""Check reproducible extraction and run the relocated PC viewer without a console."""
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from urllib.request import Request, urlopen
from zipfile import ZipFile

ROOT=Path(__file__).resolve().parents[1]


def get(url):
    with urlopen(url,timeout=2) as response:
        assert response.status==200
        return response.read()


def main():
    spec=importlib.util.spec_from_file_location('bundle_builder',ROOT/'build_bundle.py')
    builder=importlib.util.module_from_spec(spec);spec.loader.exec_module(builder)
    receipt=json.loads((ROOT/'release-files.json').read_text())
    with tempfile.TemporaryDirectory(prefix='remote-pilot-release-') as folder:
        root=Path(folder)
        first,second=builder.build(root/'one.zip'),builder.build(root/'two.zip')
        assert first.read_bytes()==second.read_bytes(),'non-reproducible bundle'
        with ZipFile(first) as archive:
            assert set(archive.namelist())=={'RemotePilot/3ds/'+name for name in receipt['files']}|{'RemotePilot/3ds/release-files.json'}
            archive.extractall(root/'relocated')
        moved=root/'relocated/RemotePilot/3ds'
        assert not (moved/'pc/local').exists()
        subprocess.run([sys.executable,str(moved/'tools/verify_release.py')],check=True)
        app=moved/'pc'
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        env=os.environ.copy();env.pop('PYTHONPATH',None)
        launch=("import runpy,socket,sys; "
                "socket.gethostbyname_ex=lambda host:(host,[],['127.0.0.1']); "
                "sys.path.insert(0,sys.argv[1]); script=sys.argv[2]; "
                "sys.argv=sys.argv[2:]; runpy.run_path(script,run_name='__main__')")
        process=subprocess.Popen([sys.executable,'-c',launch,str(app),str(app/'receiver.py'),'serve','--viewer-port',str(port)],cwd=root,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
        base=f'http://127.0.0.1:{port}'
        try:
            deadline=time.monotonic()+20
            while True:
                if process.poll() is not None:raise AssertionError('Extracted receiver exited: '+process.stdout.read())
                try:
                    state=json.loads(get(base+'/api/state'));break
                except OSError:
                    if time.monotonic()>deadline:raise AssertionError('Extracted receiver did not start')
                    time.sleep(.1)
            assert not state['connected'] and state['discovery']=='local example'
            presets=json.loads(get(base+'/api/presets'))['presets']
            assert sorted(p['id'] for p in presets)==receipt['presets']
            assert b'Remote Pilot' in get(base+'/')
            for name in ('viewer.js','viewer.css','themes.css','homebrew.js','homebrew_flow.js'):
                assert get(base+'/'+name)
            # Select each adapter offline. No pairing configuration is supplied,
            # so no device scan, input, transfer or install is initiated.
            for preset in presets:
                ident=preset['id']
                request=Request(base+'/api/preset',json.dumps({'id':ident}).encode(),{'Content-Type':'application/json','X-Remote-Pilot-Viewer':'1'},method='POST')
                with urlopen(request,timeout=5) as response:assert json.load(response)['selected']==ident
                status=json.loads(get(base+'/api/state'))
                assert not status['connected']
                assert 'Adapter unavailable' not in status.get('discovery',''),status.get('discovery')
                if preset.get('styleSheet'):assert get(base+preset['styleSheet'])
            # Exercise sibling apps discovery directly, without any console key.
            check=('from homebrew_runtime import HomebrewAdapter;import tempfile;'
                   'p=tempfile.TemporaryDirectory();a=HomebrewAdapter(p.name,{});'
                   'u=a.available_updates();assert u["companion"]["version"]==8;'
                   'assert u["updater"]["version"]==7;a.stop();p.cleanup()')
            subprocess.run([sys.executable,'-c',check],cwd=app,env=env,check=True)
        finally:
            process.terminate();process.wait(timeout=5);process.stdout.close()
    print(receipt['mode']+': reproducible archive, relocated offline viewer, every preset adapter and sibling updates PASS')


if __name__=='__main__':main()
