[CmdletBinding()]
param(
    [switch]$HostTests,
    [ValidateRange(1,65535)][int]$CompanionVersion=8,
    [ValidateRange(1,65535)][int]$UpdaterVersion=7
)
$ErrorActionPreference = 'Stop'
$bash = 'C:\msys64\usr\bin\bash.exe'
if (-not (Test-Path -LiteralPath $bash)) { throw 'MSYS2/devkitARM is required; see README.md.' }
$drive = @('R','S','T','U','V','W','X','Y','Z') | Where-Object { -not (Test-Path ($_ + ':\')) } | Select-Object -First 1
if (-not $drive) { throw 'A free temporary drive letter is needed for GNU make with a spaced Windows path.' }
# Reversible alias only: all sources and outputs remain in this project.
& subst ($drive + ':') $PSScriptRoot
if ($LASTEXITCODE -ne 0) { throw 'Could not create the temporary build alias.' }
try {
    Push-Location -LiteralPath $PSScriptRoot
    try {
        python make_assets.py --companion-version $CompanionVersion --updater-version $UpdaterVersion
        if ($LASTEXITCODE -ne 0) { throw 'Asset generation failed.' }
        $script = 'export DEVKITPRO=/opt/devkitpro; export DEVKITARM=/opt/devkitpro/devkitARM; export PATH=/opt/devkitpro/tools/bin:/opt/devkitpro/devkitARM/bin:$PATH; cd /%DRIVE%; make -j2'
        & $bash -lc $script.Replace('%DRIVE%', $drive.ToLowerInvariant())
        if ($LASTEXITCODE -ne 0) { throw 'ARM compilation failed.' }
        & $bash -lc ($script.Replace('%DRIVE%', $drive.ToLowerInvariant()) + ' VARIANT=updater')
        if ($LASTEXITCODE -ne 0) { throw 'Updater ARM compilation failed.' }
        if ($HostTests) {
            $hostScript = 'cd /%DRIVE%; /usr/bin/g++ -Wall -Wextra -Werror -std=gnu++17 -O1 -g -Ibuild source/main.cpp source/platform_host.cpp source/sha256.cpp -o build/companion-host.exe'
            & $bash -lc $hostScript.Replace('%DRIVE%', $drive.ToLowerInvariant())
            if ($LASTEXITCODE -ne 0) { throw 'Host simulation compilation failed.' }
            $updaterHostScript = 'cd /%DRIVE%; /usr/bin/g++ -Wall -Wextra -Werror -std=gnu++17 -O1 -g -DRPH_UPDATER -Ibuild-updater source/main.cpp source/platform_host.cpp source/sha256.cpp -o build/updater-host.exe'
            & $bash -lc $updaterHostScript.Replace('%DRIVE%', $drive.ToLowerInvariant())
            if ($LASTEXITCODE -ne 0) { throw 'Updater host simulation compilation failed.' }
            $displayTestScript = 'cd /%DRIVE%; /usr/bin/g++ -Wall -Wextra -Werror -std=gnu++17 -O1 -g -ffunction-sections -fdata-sections -Itests -Isource tests/platform_display_test.cpp source/platform.cpp -Wl,--gc-sections -o build/display-test.exe && build/display-test.exe'
            & $bash -lc $displayTestScript.Replace('%DRIVE%', $drive.ToLowerInvariant())
            if ($LASTEXITCODE -ne 0) { throw 'Native display regression test failed.' }
        }
        $makerom = Join-Path $PSScriptRoot 'tools\makerom\makerom.exe'
        $banner = Join-Path $PSScriptRoot 'tools\bannertool\windows-x86_64\bannertool.exe'
        if (-not (Test-Path -LiteralPath $makerom) -or -not (Test-Path -LiteralPath $banner)) {
            throw 'CIA packaging tools are missing. Run Get-BuildTools.ps1; the compiled 3DSX is available.'
        }
        & $banner makebanner -i build\banner.png -a build\silent.wav -o build\banner.bnr
        if ($LASTEXITCODE -ne 0) { throw 'Banner packaging failed.' }
        & $banner makesmdh -s 'RemotePilot Homebrew' -l 'Private verified deployment companion' -p 'RemotePilot' -i build\icon.png -f visible,nosavebackups -o build\icon.icn
        if ($LASTEXITCODE -ne 0) { throw 'CIA icon packaging failed.' }
        # Pinned makerom drops the minor bits in its Windows release. Use raw
        # versions 1..15, then 1024..1039, etc.; fail closed on any mismatch.
        if (($CompanionVersion -band 1008) -or ($UpdaterVersion -band 1008)) { throw 'Pinned makerom requires raw major/micro versions: 1..15, then 1024..1039, etc.' }
        & $makerom -f cia -o RemotePilotHomebrew.cia -target t -elf RemotePilotHomebrew.elf -rsf companion.rsf -banner build\banner.bnr -icon build\icon.icn -ver $CompanionVersion
        if ($LASTEXITCODE -ne 0) { throw 'CIA packaging failed.' }
        $updaterRsf = (Get-Content -LiteralPath companion.rsf -Raw).Replace('Title: RPHBREW','Title: RPHUPDTR').Replace('CTR-P-RPHB','CTR-P-RPHU').Replace('UniqueId: 0xF3D52','UniqueId: 0xF3D53')
        Set-Content -LiteralPath build-updater\updater.rsf -Value $updaterRsf -Encoding ascii
        & $banner makesmdh -s 'RemotePilot Updater' -l 'Wireless companion recovery updater' -p 'RemotePilot' -i build-updater\icon.png -f visible,nosavebackups -o build-updater\icon.icn
        if ($LASTEXITCODE -ne 0) { throw 'Updater icon packaging failed.' }
        & $banner makebanner -i build-updater\banner.png -a build\silent.wav -o build-updater\banner.bnr
        if ($LASTEXITCODE -ne 0) { throw 'Updater banner packaging failed.' }
        & $makerom -f cia -o RemotePilotUpdater.cia -target t -elf RemotePilotUpdater.elf -rsf build-updater\updater.rsf -banner build-updater\banner.bnr -icon build-updater\icon.icn -ver $UpdaterVersion
        if ($LASTEXITCODE -ne 0) { throw 'Updater CIA packaging failed.' }
        python package_build.py --companion-version $CompanionVersion --updater-version $UpdaterVersion
        if ($LASTEXITCODE -ne 0) { throw 'Package verification failed.' }
    } finally { Pop-Location }
} finally { & subst ($drive + ':') /D }
