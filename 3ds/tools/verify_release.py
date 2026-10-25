"""Verify release hashes, CIA identities, corresponding source and secret exclusion."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
from zipfile import ZipFile

ROOT=Path(__file__).resolve().parents[1]


def verify(secrets_dir=None):
    manifest=json.loads((ROOT/'release-files.json').read_text(encoding='utf-8'))
    expected_presets=['example','halo','homebrew','morrowind','waw-zombies-3ds'] if manifest['mode']=='private' else ['example','homebrew']
    if manifest['presets'] != expected_presets:raise ValueError('Unexpected distribution preset set')
    secrets=set()
    if secrets_dir:
        for path in Path(secrets_dir).rglob('*'):
            if not path.is_file() or path.stat().st_size>2*1024*1024:continue
            if path.name=='token':secrets.add(path.read_bytes().strip())
            if path.suffix in ('.cfg','.json'):
                text=path.read_text(encoding='utf-8',errors='ignore')
                secrets.update(x.encode() for x in re.findall(r'(?:token|secret)["\s]*[=:]["\s]*([a-zA-Z0-9_-]{16,})',text))
    secrets.discard(b'')
    patterns=(re.compile(rb'gh[pousr]_[A-Za-z0-9]{30,}'),
              re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'))
    for name,expected in manifest['files'].items():
        path=ROOT/name
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(ROOT):raise ValueError('Unsafe manifest path')
        if {'local','dist','__pycache__','.git','build','build-updater'}.intersection(Path(name).parts):raise ValueError('Private/runtime path in release')
        data=path.read_bytes()
        if len(data)!=expected['size'] or hashlib.sha256(data).hexdigest()!=expected['sha256']:raise ValueError('Hash mismatch: '+name)
        if any(secret in data for secret in secrets) or any(pattern.search(data) for pattern in patterns):raise ValueError('Secret material detected in: '+name)
    spec=importlib.util.spec_from_file_location('release_protocol',ROOT/'pc/homebrew_protocol.py')
    protocol=importlib.util.module_from_spec(spec);spec.loader.exec_module(protocol)
    verification=json.loads((ROOT/'apps/verification.json').read_text(encoding='utf-8'))
    for stem,title,version in (('RemotePilotHomebrew','000400000f3d5200',11),('RemotePilotUpdater','000400000f3d5300',10)):
        info=protocol.cia_info(ROOT/'apps'/(stem+'.cia'))
        if info['titleId']!=title or info['version']!=version:raise ValueError('CIA identity/version mismatch')
        for suffix in ('.cia','.3dsx','.smdh'):
            name=stem+suffix;data=(ROOT/'apps'/name).read_bytes();expected=verification['files'][name]
            if hashlib.sha256(data).hexdigest()!=expected['sha256'] or len(data)!=expected['size']:raise ValueError('App build receipt mismatch')
    with ZipFile(ROOT/'apps/RemotePilotHomebrew-source.zip') as archive:
        for name in archive.namelist():
            relative=Path(name).relative_to('RemotePilot-Homebrew')
            local=ROOT/'companion'/relative
            if '..' in relative.parts or not local.is_file() or archive.read(name)!=local.read_bytes():raise ValueError('Corresponding-source mismatch: '+name)
        for name in ('source/main.cpp','source/platform.cpp','source/sha256.cpp','LICENSE','NOTICE.md','third_party/libctru-2.7.0-source.tar.gz'):
            if 'RemotePilot-Homebrew/'+name not in archive.namelist():raise ValueError('Missing corresponding source: '+name)
    vendor=ROOT/'companion/third_party/libctru-2.7.0-source.tar.gz'
    if hashlib.sha256(vendor.read_bytes()).hexdigest()!='c22913738ce3b1da5e52f26150d245f602c04f6c72cf4b81352f32c52d411e5f':raise ValueError('Vendored library source changed')
    print(f"PASS: {manifest['mode']} distribution; {len(manifest['files'])} file hashes; correct CIA IDs/versions; matching GPL source; {len(secrets)} private-secret values checked without disclosure")


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--secrets-dir',type=Path)
    verify(parser.parse_args().secrets_dir)
