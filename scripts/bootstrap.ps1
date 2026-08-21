[CmdletBinding()]
param(
    [switch]$SkipPreCommit
)

$ErrorActionPreference = 'Stop'
$uvVersion = '0.8.11'
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $repoRoot

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw 'Python 3.12 or 3.13 is required. Install Python from python.org, then rerun this script.'
}

$pythonVersion = & python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
if ($pythonVersion -notin @('3.12', '3.13')) {
    throw "Python 3.12 or 3.13 is required; found $pythonVersion."
}

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    & python -m pip install --user "uv==$uvVersion"
}

function Invoke-Uv {
    if (Get-Command uv -ErrorAction SilentlyContinue) {
        & uv @args
    } else {
        & python -m uv @args
    }
    if ($LASTEXITCODE -ne 0) {
        throw "uv command failed: $args"
    }
}

Invoke-Uv sync --frozen --extra dev
Invoke-Uv run gct-validate $repoRoot
Invoke-Uv run ruff format --check .
Invoke-Uv run ruff check .
Invoke-Uv run mypy
Invoke-Uv run pytest

if (-not $SkipPreCommit) {
    Invoke-Uv run pre-commit install
}

Write-Host 'Bootstrap complete. Launch with: uv run game-chat-translator'
