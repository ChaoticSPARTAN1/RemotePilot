# One-time bootstrap only. Never copies or installs a Morrowind CIA.
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][ValidatePattern('^[0-9A-Fa-f]{8}$')][string]$ExpectedVolumeSerial
)
$ErrorActionPreference = 'Stop'
$artifactRoot = if (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'dist\verification.json')) { Join-Path $PSScriptRoot 'dist' } else { Join-Path $PSScriptRoot '..\apps' }
$receiverRoot = if (Test-Path -LiteralPath (Join-Path $PSScriptRoot '..\pc')) { Join-Path $PSScriptRoot '..\pc' } else { Join-Path $PSScriptRoot '..\RemotePilot' }
$expectedSerial = $ExpectedVolumeSerial.ToUpperInvariant()
$cards = @(Get-CimInstance Win32_LogicalDisk | Where-Object VolumeSerialNumber -EQ $expectedSerial)
if ($cards.Count -ne 1 -or $cards[0].FileSystem -ne 'FAT32') { throw 'Expected owner FAT32 card not uniquely identified.' }
$device = $cards[0].DeviceID
$cardRoot = [IO.Path]::GetFullPath($device + '\')
function Identity {
    $disk = Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='$device'"
    if (-not $disk -or $disk.FileSystem -ne 'FAT32' -or $disk.VolumeSerialNumber -ne $expectedSerial) {
        throw 'Card identity changed; stopping.'
    }
}
function SafePath([string]$path) {
    $absolute = [IO.Path]::GetFullPath($path)
    if (-not $absolute.StartsWith($cardRoot, [StringComparison]::OrdinalIgnoreCase)) { throw 'Path escapes card root.' }
    $ancestor = $absolute
    while ($ancestor.Length -gt $cardRoot.Length) {
        if (Test-Path -LiteralPath $ancestor) {
            if ((Get-Item -LiteralPath $ancestor -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Linked SD path rejected.' }
        }
        $ancestor = Split-Path -Parent $ancestor
    }
}
function Hash([string]$path) { (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() }
foreach ($folder in @('3ds','cias','Nintendo 3DS')) {
    $path = Join-Path $cardRoot $folder
    SafePath $path
    if (-not (Test-Path -LiteralPath $path -PathType Container)) { throw ('Expected card layout missing: '+$folder) }
}
$run = Join-Path $PSScriptRoot ('local\setup-' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff'))
New-Item -ItemType Directory -Path $run | Out-Null
$protected = @()
$mwRoot = Join-Path $cardRoot '3ds\mw3ds'
if (Test-Path -LiteralPath $mwRoot) {
    $protected += @(Get-ChildItem -LiteralPath $mwRoot -File -Force)
    foreach ($folder in @('saves','bug-it')) {
        $path = Join-Path $mwRoot $folder
        if (Test-Path -LiteralPath $path) { $protected += @(Get-ChildItem -LiteralPath $path -File -Recurse -Force) }
    }
}
$before = @{}
foreach ($file in $protected) {
    SafePath $file.FullName
    $relative = $file.FullName.Substring($cardRoot.Length)
    $backup = Join-Path $run ('protected\'+$relative)
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $backup) | Out-Null
    $before[$relative] = Hash $file.FullName
    Copy-Item -LiteralPath $file.FullName -Destination $backup
    if ((Hash $backup) -ne $before[$relative]) { throw 'Protected state backup failed.' }
}
$verification = Get-Content -LiteralPath (Join-Path $artifactRoot 'verification.json') -Raw | ConvertFrom-Json
$targets = [ordered]@{
    'RemotePilotHomebrew.3dsx' = '3ds\RemotePilotHomebrew\RemotePilotHomebrew.3dsx'
    'RemotePilotHomebrew.smdh' = '3ds\RemotePilotHomebrew\RemotePilotHomebrew.smdh'
    'RemotePilotHomebrew.cia' = 'cias\RemotePilotHomebrew.cia'
    'remote-pilot-homebrew.cfg' = '3ds\RemotePilotHomebrew\remote-pilot-homebrew.cfg'
}
$sources = @{}
foreach ($name in $targets.Keys) {
    $source = if ($name.EndsWith('.cfg')) {
        Join-Path $receiverRoot 'local\homebrew\remote-pilot-homebrew.cfg'
    } else { Join-Path $artifactRoot $name }
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { throw ('Source missing: '+$name) }
    $hash = Hash $source
    if (-not $name.EndsWith('.cfg')) {
        $expected = $verification.files.$name
        if (-not $expected -or $hash -ne $expected.sha256 -or (Get-Item -LiteralPath $source).Length -ne $expected.size) { throw ('Build receipt mismatch: '+$name) }
    }
    $sources[$name] = @{ Path=$source; Hash=$hash }
}
$results = @()
foreach ($name in $targets.Keys) {
    Identity
    $target = Join-Path $cardRoot $targets[$name]
    SafePath $target
    if (Test-Path -LiteralPath $target) {
        $backup = Join-Path $run ('previous\'+$targets[$name])
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $backup) | Out-Null
        Copy-Item -LiteralPath $target -Destination $backup
        if ((Hash $target) -ne (Hash $backup)) { throw 'Previous companion backup failed.' }
    }
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $target) | Out-Null
    $temporary = $target + '.bootstrap-tmp'
    SafePath $temporary
    if (Test-Path -LiteralPath $temporary) { throw 'Unreviewed temporary bootstrap file exists.' }
    Copy-Item -LiteralPath $sources[$name].Path -Destination $temporary
    if ((Hash $temporary) -ne $sources[$name].Hash) { throw ('Card verification failed: '+$name) }
    Identity
    Move-Item -LiteralPath $temporary -Destination $target -Force
    if ((Hash $target) -ne $sources[$name].Hash) { throw 'Final card hash mismatch.' }
    $results += @{path=$targets[$name];sha256=$sources[$name].Hash}
}
Identity
foreach ($relative in $before.Keys) {
    if ((Hash (Join-Path $cardRoot $relative)) -ne $before[$relative]) { throw 'Protected Morrowind state changed unexpectedly.' }
}
$flushed = $false
try { Write-VolumeCache -DriveLetter $device.Substring(0,1) -ErrorAction Stop; $flushed=$true }
catch { Write-Output 'Use Windows Safely Remove Hardware before removing the card.' }
@{createdAt=(Get-Date).ToString('o');files=$results;protectedFiles=$before;protectedFilesUnchanged=$true;
  volumeSerial=$expectedSerial;volumeCacheFlushed=$flushed;morrowindCiaCopied=$false;
  note='Companion bootstrap only; Morrowind update remains on PC for wireless upload/install.'} |
    ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $run 'receipt.json') -Encoding utf8
Write-Output ('Verified four companion bootstrap files; backed up and preserved '+$before.Count+' existing state files.')
Write-Output 'No Morrowind CIA copied, no title installed, no boot/firmware files changed.'
