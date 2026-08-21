[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $repoRoot

& uv run pyinstaller --version
if ($LASTEXITCODE -ne 0) {
    throw 'PyInstaller version check failed.'
}
& uv build --wheel
if ($LASTEXITCODE -ne 0) {
    throw 'Wheel build failed.'
}
$wheel = Get-ChildItem -LiteralPath (Join-Path $repoRoot 'dist') -Filter '*.whl' |
    Sort-Object -Property LastWriteTime -Descending |
    Select-Object -First 1
if ($null -eq $wheel) {
    throw 'Wheel build did not produce an artifact.'
}
$smokeRoot = Join-Path ([System.IO.Path]::GetTempPath()) 'gct wheel smoke with spaces'
New-Item -ItemType Directory -Force -Path $smokeRoot | Out-Null
Push-Location -LiteralPath $smokeRoot
try {
    & uv run --isolated --with $wheel.FullName -- game-chat-translator --packaging-smoke
    if ($LASTEXITCODE -ne 0) {
        throw 'Clean wheel smoke failed.'
    }
} finally {
    Pop-Location
}
Write-Host 'Clean wheel launch and packaged resource validation passed.'
