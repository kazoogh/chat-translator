[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $repoRoot

& uv run pyinstaller --version
& uv run game-chat-translator --packaging-smoke
Write-Host 'Packaging toolchain metadata and application entry point are callable.'
