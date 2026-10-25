"""Compile desktop simulations and production renderer checks, not ARM apps."""
import os
from pathlib import Path
import shutil
import subprocess

ROOT=Path(__file__).resolve().parents[1]/'companion'


def main():
    compiler=shutil.which('g++')
    if not compiler and os.name=='nt':compiler=r'C:\msys64\usr\bin\g++.exe'
    if not compiler or not Path(compiler).is_file():raise SystemExit('Install g++ (MSYS2 on Windows) for desktop tests')
    env=os.environ.copy()
    env['PATH']=str(Path(compiler).parent)+os.pathsep+env.get('PATH','')
    common=[compiler,'-Wall','-Wextra','-Werror','-std=gnu++17','-O1','-g']
    for folder,version,output,flags in (('build',12,'companion-host.exe',[]),('build-updater',11,'updater-host.exe',['-DRPH_UPDATER'])):
        (ROOT/folder).mkdir(exist_ok=True)
        (ROOT/folder/'build_version.hpp').write_text(f'#pragma once\n#define RPH_BUILD_VERSION {version}\n')
        subprocess.run(common+flags+['-I'+folder,'source/main.cpp','source/platform_host.cpp','source/sha256.cpp','-o','build/'+output],cwd=ROOT,env=env,check=True)
    subprocess.run(common+['-ffunction-sections','-fdata-sections','-Itests','-Isource','tests/platform_display_test.cpp','source/platform.cpp','-Wl,--gc-sections','-o','build/display-test.exe'],cwd=ROOT,env=env,check=True)
    subprocess.run([str(ROOT/'build/display-test.exe')],cwd=ROOT,env=env,check=True)
    subprocess.run(common+['-Isource','tests/socket_io_test.cpp','-o','build/socket-io-test.exe'],cwd=ROOT,env=env,check=True)
    subprocess.run([str(ROOT/'build/socket-io-test.exe')],cwd=ROOT,env=env,check=True)
    print('Desktop simulations and production display regression compiled and passed; no hardware installation performed')


if __name__=='__main__':main()
