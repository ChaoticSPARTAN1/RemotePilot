"""Build a reproducible 3DS bundle from the release's explicit file manifest."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parent


def build(output=None):
    receipt = json.loads((ROOT/'release-files.json').read_text(encoding='utf-8'))
    output = Path(output or ROOT/'dist'/receipt['archive']).resolve()
    files = {}
    for name, expected in receipt['files'].items():
        source = ROOT/name
        if source.is_symlink() or not source.resolve().is_relative_to(ROOT) or not source.is_file():
            raise ValueError('Unsafe or missing release file: '+name)
        data = source.read_bytes()
        if len(data) != expected['size'] or hashlib.sha256(data).hexdigest() != expected['sha256']:
            raise ValueError('Release file changed; regenerate the manifest: '+name)
        files[name] = data
    files['release-files.json'] = (ROOT/'release-files.json').read_bytes()
    output.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
        for name,data in sorted(files.items()):
            info = zipfile.ZipInfo('RemotePilot/3ds/'+name,date_time=(1980,1,1,0,0,0))
            info.create_system=3
            info.external_attr=(0o100755 if name.endswith('.sh') else 0o100644)<<16
            archive.writestr(info,data,compress_type=zipfile.ZIP_DEFLATED,compresslevel=9)
    print(f'{output.name}: {output.stat().st_size} bytes; SHA-256 {hashlib.sha256(output.read_bytes()).hexdigest()}')
    return output


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path)
    build(parser.parse_args().output)
