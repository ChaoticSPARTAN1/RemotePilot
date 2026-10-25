# Update both tool launchers and stage both HOME installers. Preserve pairing,
# receipts, pending wireless packages and game state; never install a title here.
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
    if (-not $disk -or $disk.FileSystem -ne 'FAT32' -or $disk.VolumeSerialNumber -ne $expectedSerial) { throw 'Card identity changed; stopping.' }
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
$verification = Get-Content -LiteralPath (Join-Path $artifactRoot 'verification.json') -Raw | ConvertFrom-Json
$targets = [ordered]@{}
$sources = @{}
foreach ($stem in @('RemotePilotHomebrew','RemotePilotUpdater')) {
    foreach ($extension in @('.3dsx','.smdh','.cia')) {
        $name = $stem + $extension
        $source = Join-Path $artifactRoot $name
        $expected = $verification.files.$name
        $hash = Hash $source
        if (-not $expected -or $hash -ne $expected.sha256 -or (Get-Item -LiteralPath $source).Length -ne $expected.size) { throw ('Build receipt mismatch: '+$name) }
        $targets[$name] = if ($extension -eq '.cia') { 'cias\'+$name } else { '3ds\'+$stem+'\'+$name }
        $sources[$name] = @{Path=$source;Hash=$hash}
    }
}
# Existing console pairing must match the receiver; neither copy is rewritten.
$configPath = Join-Path $cardRoot '3ds\RemotePilotHomebrew\remote-pilot-homebrew.cfg'
SafePath $configPath
$sdConfig = @{}
foreach ($line in (Get-Content -LiteralPath $configPath)) {
    if ($line -match '^([^=]+)=(.*)$') { $sdConfig[$Matches[1]]=$Matches[2] }
}
$pcConfig = Get-Content -LiteralPath (Join-Path $receiverRoot 'local\homebrew\companion.json') -Raw | ConvertFrom-Json
if ($sdConfig.token -cne $pcConfig.token -or [string]$sdConfig.port -ne [string]$pcConfig.port) { throw 'Existing SD/PC pairing differs; no files changed.' }
$run = Join-Path $PSScriptRoot ('local\tool-update-' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff'))
New-Item -ItemType Directory -Path $run | Out-Null
$protected = @()
# Preserve and back up entire small tool folders, including pending wireless
# staging. Game state protection includes settings, saves and Bug It evidence.
foreach ($folder in @('3ds\RemotePilotHomebrew','3ds\RemotePilotUpdater')) {
    $path = Join-Path $cardRoot $folder
    SafePath $path
    if (Test-Path -LiteralPath $path) { $protected += @(Get-ChildItem -LiteralPath $path -File -Recurse -Force) }
}
foreach ($relative in $targets.Values) {
    if ($relative.StartsWith('cias\')) {
        $path = Join-Path $cardRoot $relative
        if (Test-Path -LiteralPath $path) { $protected += Get-Item -LiteralPath $path }
    }
}
$mwRoot = Join-Path $cardRoot '3ds\mw3ds'
SafePath $mwRoot
if (Test-Path -LiteralPath $mwRoot) {
    $protected += @(Get-ChildItem -LiteralPath $mwRoot -File -Force)
    foreach ($folder in @('saves','bug-it')) {
        $path = Join-Path $mwRoot $folder
        SafePath $path
        if (Test-Path -LiteralPath $path) { $protected += @(Get-ChildItem -LiteralPath $path -File -Recurse -Force) }
    }
}
$before = @{}
foreach ($file in $protected) {
    Identity
    SafePath $file.FullName
    $relative = $file.FullName.Substring($cardRoot.Length)
    $backup = Join-Path $run ('previous\'+$relative)
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $backup) | Out-Null
    $before[$relative] = Hash $file.FullName
    Copy-Item -LiteralPath $file.FullName -Destination $backup
    if ((Hash $backup) -ne $before[$relative]) { throw ('Backup verification failed: '+$relative) }
}
$results = @()
foreach ($name in $targets.Keys) {
    Identity
    $target = Join-Path $cardRoot $targets[$name]
    SafePath $target
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $target) | Out-Null
    $temporary = $target + '.tool-update-tmp'
    SafePath $temporary
    if (Test-Path -LiteralPath $temporary) { throw 'Unreviewed temporary update file exists.' }
    Copy-Item -LiteralPath $sources[$name].Path -Destination $temporary
    if ((Hash $temporary) -ne $sources[$name].Hash) { throw ('Card verification failed: '+$name) }
    Identity
    Move-Item -LiteralPath $temporary -Destination $target -Force
    if ((Hash $target) -ne $sources[$name].Hash) { throw 'Final card hash mismatch.' }
    $results += @{path=$targets[$name];sha256=$sources[$name].Hash;size=(Get-Item -LiteralPath $target).Length}
}
Identity
$unchanged = @{}
foreach ($relative in $before.Keys) {
    if ($targets.Values -contains $relative) { continue }
    $path = Join-Path $cardRoot $relative
    SafePath $path
    if ((Hash $path) -ne $before[$relative]) { throw ('Preserved file changed unexpectedly: '+$relative) }
    $unchanged[$relative] = $before[$relative]
}
$flushed = $false
try { Write-VolumeCache -DriveLetter $device.Substring(0,1) -ErrorAction Stop; $flushed=$true }
catch { Write-Output 'Use Windows Safely Remove Hardware before removing the card.' }
$receipt = @{createdAt=(Get-Date).ToString('o');files=$results;preservedFiles=$unchanged;backupFolder=$run;
    volumeSerial=$expectedSerial;volumeCacheFlushed=$flushed;pairingPreserved=$true;gameStateUnchanged=$true;
    companionVersion=$verification.cia.version;updaterVersion=$verification.updater.version;
    homeMenuTitlesInstalled=$false;morrowindCiaCopied=$false;
    note='Both Homebrew Launcher tools updated. Both HOME installers staged in cias; FBI installation on console remains required.'}
$json = $receipt | ConvertTo-Json -Depth 7
$json | Set-Content -LiteralPath (Join-Path $run 'receipt.json') -Encoding utf8
$json | Set-Content -LiteralPath (Join-Path $PSScriptRoot 'local\latest-sd-tools-update.json') -Encoding utf8
Write-Output ('Verified six tool files: companion '+$verification.cia.version+', updater '+$verification.updater.version+'. Preserved '+$unchanged.Count+' files; pairing unchanged.')
Write-Output ('Backup and receipt: '+$run)
Write-Output 'HOME Menu installers require FBI on the console. Pending Morrowind staging and all inspected game state are unchanged.'
