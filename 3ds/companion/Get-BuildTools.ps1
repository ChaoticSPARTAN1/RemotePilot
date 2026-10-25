$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$toolsRoot = Join-Path $PSScriptRoot 'tools'
New-Item -ItemType Directory -Force -Path $toolsRoot | Out-Null
$tools = @(
    @{ Name='makerom'; Url='https://github.com/3DSGuy/Project_CTR/releases/download/makerom-v0.19.0/makerom-v0.19.0-win_x86_64.zip'; Hash='88df4455e60556374e202d507f54ee03fac7493ec9554ab853157524b6d69db0' },
    @{ Name='bannertool'; Url='https://github.com/diasurgical/bannertool/releases/download/1.2.0/bannertool.zip'; Hash='69768596f836acb3e3aeaa66e47c6ba560dde813c6dfcd33c8afc25fe29b7524' }
)
foreach ($item in $tools) {
    $archive = Join-Path $toolsRoot ($item.Name + '.zip')
    if (-not (Test-Path -LiteralPath $archive)) { Invoke-WebRequest -Uri $item.Url -OutFile $archive }
    if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash -ne $item.Hash) { throw ($item.Name + ' digest mismatch') }
    Expand-Archive -LiteralPath $archive -DestinationPath (Join-Path $toolsRoot $item.Name) -Force
}
Write-Output 'Official packaging tools verified and extracted locally.'
