"""Build the RemotePilot PSP companion EBOOT with the PSP toolchain (pspdev).

    python psp/tools/build_psp.py [--pspdev <pspdev folder>] [--make make]

The outputs are psp/device/build/psp/EBOOT.PBP and rp_flash.prx (the
settings restore's kernel helper); copy both to ms0:/PSP/GAME/REMOTEPILOT/
on the Memory Stick. Objects stay in the build folders (ignored by git).
"""
import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

DEVICE = Path(__file__).resolve().parent.parent / 'device'


def make_path(path):
    """A path make can take: no spaces (Windows: the 8.3 short form), forward slashes."""
    path = str(Path(path).resolve())
    if os.name == 'nt' and ' ' in path:
        import ctypes
        buffer = ctypes.create_unicode_buffer(1024)
        if ctypes.windll.kernel32.GetShortPathNameW(path, buffer, len(buffer)):
            path = buffer.value
    if ' ' in path:
        sys.exit('the PSP SDK path has a space make cannot take: %s' % path)
    return path.replace(os.sep, '/')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--pspdev', default=os.environ.get('PSPDEV', ''))
    parser.add_argument('--make', default='make')
    args = parser.parse_args()
    env = dict(os.environ)
    if args.pspdev:
        env['PATH'] = str(Path(args.pspdev) / 'bin') + os.pathsep + env['PATH']
        env['PSPDEV'] = make_path(args.pspdev)
    if not shutil.which('psp-gcc', path=env['PATH']):
        sys.exit('psp-gcc not found: pass --pspdev <pspdev folder> or put its bin on PATH')
    out = DEVICE / 'build' / 'psp'
    # the restore's kernel helper, rp_flash.prx, built apart and put beside the EBOOT
    helper = DEVICE / 'build' / 'psp-flash'
    for folder, makefile in ((helper, 'flash/Makefile.flash'), (out, 'Makefile.psp')):
        folder.mkdir(parents=True, exist_ok=True)
        # make wants forward slashes, and a path without spaces for VPATH: the
        # sources are given relative to the build folder
        source = os.path.relpath(DEVICE, folder).replace(os.sep, '/')
        command = [args.make, '-f', source + '/' + makefile, 'SRC=' + source]
        # a relocated toolchain's psp-config answers its build prefix, not where it is
        if args.pspdev:
            command.append('PSPSDK=' + make_path(Path(args.pspdev) / 'psp' / 'sdk'))
        subprocess.run(command, cwd=folder, env=env, check=True)
    shutil.copyfile(helper / 'rp_flash.prx', out / 'rp_flash.prx')
    # the licences that go with any copy of the EBOOT (psp/NOTICE.md): the
    # fonts it embeds, the hash it compiles, and the SDK and C library it links
    licences = out / 'licenses'
    licences.mkdir(exist_ok=True)
    for source, name in ((DEVICE / 'ui' / 'fonts' / 'OFL.txt', 'Audiowide-OFL.txt'),
                         (DEVICE / 'ui' / 'fonts' / 'LICENSE_DEJAVU', 'DejaVu-LICENSE.txt'),
                         (DEVICE / 'third_party' / 'CHUPATHINGYCE-CC0.txt', 'sha256_hmac-CC0.txt'),
                         (DEVICE.parent / 'NOTICE.md', 'NOTICE.md')):
        shutil.copyfile(source, licences / name)
    toolchain = Path(env.get('PSPDEV') or os.environ.get('PSPDEV', '')) / 'psp' / 'share' / 'licenses'
    for source, name in (('pspsdk/LICENSE', 'pspsdk.txt'), ('newlib/COPYING.NEWLIB', 'newlib.txt')):
        if (toolchain / source).is_file():
            shutil.copyfile(toolchain / source, licences / name)
        else:
            print('warning: %s not found: add its licence to %s by hand' % (toolchain / source, licences))
    for name in ('EBOOT.PBP', 'rp_flash.prx', 'licenses'):
        target = out / name
        print('built %s%s' % (target, '' if target.is_dir() else ' (%d bytes)' % target.stat().st_size))
    return 0


if __name__ == '__main__':
    sys.exit(main())
