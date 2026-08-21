[CmdletBinding()]
param(
    [string]$Output = ''
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $repoRoot

if ($Output) {
    & uv run gct-diagnostics --output $Output
} else {
    & uv run gct-diagnostics
}

