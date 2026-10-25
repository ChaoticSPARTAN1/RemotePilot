"""Package binaries and corresponding source; never include local pairing data."""
import hashlib
import argparse
import json
from pathlib import Path
import shutil
import struct
import zipfile

ROOT = Path(__file__).resolve().parent


def verify_cia(path, expected_title, expected_version):
    with path.open('rb') as src:
        hdr = struct.unpack('<IHHIIIIQ', src.read(32))
        align = lambda n: (n + 63) & ~63
        if hdr[0] != 0x2020: raise ValueError('Invalid CIA header')
        tmd = align(align(align(hdr[0]) + hdr[3]) + hdr[4])
        src.seek(tmd)
        if src.read(4) != bytes.fromhex('00010004'): raise ValueError('Unexpected TMD signature format')
        src.seek(tmd + 0x140 + 0x4c)
        title = src.read(8).hex()
        if title != expected_title: raise ValueError('Application title identity mismatch')
        src.seek(tmd + 0x140 + 0x9c)
        version = int.from_bytes(src.read(2), 'big')
        if version != expected_version: raise ValueError(f'Actual TMD version {version} != requested {expected_version}')
        src.seek(0); data=src.read()
        content=align(tmd+hdr[5])
        record=tmd+0x140+0xc4+0x900
        if int.from_bytes(data[tmd+0x140+0x9e:tmd+0x140+0xa0],'big')!=1:
            raise ValueError('Expected one native application content')
        size=int.from_bytes(data[record+8:record+16],'big')
        if size<512 or content+size>len(data) or hashlib.sha256(data[content:content+size]).digest()!=data[record+16:record+48]:
            raise ValueError('CIA content checksum mismatch')
        ncch=data[content:content+512]
        if ncch[0x100:0x104]!=b'NCCH' or int.from_bytes(ncch[0x118:0x120],'little')!=int(title,16):
            raise ValueError('Native content identity mismatch')
        def region(offset,length):
            if offset<512 or length<1 or offset+length>size:raise ValueError('Native section bounds invalid')
            return data[content+offset:content+offset+length]
        exhdr_size=int.from_bytes(ncch[0x180:0x184],'little')
        if hashlib.sha256(region(512,exhdr_size)).digest()!=ncch[0x160:0x180]:
            raise ValueError('Extended-header checksum mismatch')
        logo_offset,logo_size=(v*512 for v in struct.unpack_from('<II',ncch,0x198))
        if logo_size!=8192:raise ValueError('Missing compatible application boot-logo region')
        logo=region(logo_offset,logo_size)
        if logo[0]!=0x11 or hashlib.sha256(logo).digest()!=ncch[0x130:0x150]:
            raise ValueError('Boot-logo checksum or compression invalid')
        exefs_offset,exefs_size,hash_size=(v*512 for v in struct.unpack_from('<III',ncch,0x1a0))
        exefs=region(exefs_offset,exefs_size)
        if hash_size!=512 or hashlib.sha256(exefs[:hash_size]).digest()!=ncch[0x1c0:0x1e0]:
            raise ValueError('ExeFS-header checksum mismatch')
        sections=set()
        for index in range(10):
            name=exefs[index*16:index*16+8].rstrip(b'\0').decode('ascii')
            if not name:continue
            offset,length=struct.unpack_from('<II',exefs,index*16+8)
            if offset+length>exefs_size-512 or hashlib.sha256(exefs[512+offset:512+offset+length]).digest()!=exefs[0xc0+(9-index)*32:0xe0+(9-index)*32]:
                raise ValueError('ExeFS-payload checksum mismatch')
            sections.add(name)
        if not {'.code','icon','banner'}<=sections:raise ValueError('Missing executable or HOME artwork')
        return {'titleId': title, 'version': version, 'contentChecksPassed':True,
                'bootLogoSha256':hashlib.sha256(logo).hexdigest()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--companion-version', type=int, default=11)
    parser.add_argument('--updater-version', type=int, default=10)
    args = parser.parse_args()
    out = ROOT / 'dist'
    out.mkdir(exist_ok=True)
    files = [stem + suffix for stem in ('RemotePilotHomebrew', 'RemotePilotUpdater')
             for suffix in ('.cia', '.3dsx', '.smdh')]
    receipt = {'applicationVersion': '0.10.0-preview', 'hardwareVerified': False,
               'cia': verify_cia(ROOT / files[0], '000400000f3d5200', args.companion_version),
               'updater': verify_cia(ROOT / 'RemotePilotUpdater.cia', '000400000f3d5300', args.updater_version),
               'files': {}}
    for name in files:
        source = ROOT / name
        if source.is_symlink() or not source.stat().st_size: raise ValueError('Missing build artifact')
        shutil.copy2(source, out / name)
        receipt['files'][name] = {'size': source.stat().st_size,
                                 'sha256': hashlib.sha256(source.read_bytes()).hexdigest()}
    (out / 'verification.json').write_text(json.dumps(receipt, indent=2) + '\n')
    (out / 'SHA256SUMS.txt').write_text(''.join(f"{info['sha256']}  {name}\n" for name, info in receipt['files'].items()))
    sources = ['Makefile', 'companion.rsf', 'build.ps1', 'Get-BuildTools.ps1', 'Stage-Companion.ps1', 'Stage-ToolUpdates.ps1', 'make_assets.py',
               'package_build.py', 'README.md', 'PROTOCOL.md', 'HARDWARE_TESTS.md', 'NOTICE.md', 'LICENSE',
               ]
    sources += [path.relative_to(ROOT).as_posix() for path in sorted((ROOT / 'third_party').iterdir()) if path.is_file()]
    sources += [path.relative_to(ROOT).as_posix() for path in sorted((ROOT / 'artwork').iterdir()) if path.is_file()]
    sources += [path.relative_to(ROOT).as_posix() for path in sorted((ROOT / 'source').iterdir()) if path.is_file()]
    sources += [path.relative_to(ROOT).as_posix() for path in sorted((ROOT / 'tests').iterdir()) if path.is_file()]
    with zipfile.ZipFile(out / 'RemotePilotHomebrew-source.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
        for name in sources: archive.write(ROOT / name, 'RemotePilot-Homebrew/' + name)
    with zipfile.ZipFile(out / 'RemotePilotHomebrew-preview.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
        for name in files + ['verification.json', 'SHA256SUMS.txt', 'RemotePilotHomebrew-source.zip']:
            archive.write(out / name, name)
        for name in ('README.md', 'PROTOCOL.md', 'HARDWARE_TESTS.md', 'NOTICE.md', 'LICENSE', 'third_party/libctru-LICENSE.txt'):
            archive.write(ROOT / name, name)
    print(f"Verified local preview: CIA title {receipt['cia']['titleId']}, raw TMD version {receipt['cia']['version']}; hardware untested")


if __name__ == '__main__': main()
