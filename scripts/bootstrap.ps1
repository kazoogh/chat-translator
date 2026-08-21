[CmdletBinding()]
param(
    [switch]$SkipPreCommit
)

$ErrorActionPreference = 'Stop'
$uvVersion = '0.8.11'
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $repoRoot

$pythonMode = $null
$venvPython = Join-Path $repoRoot '.venv\Scripts\python.exe'
if (Test-Path -LiteralPath $venvPython -PathType Leaf) {
    $probe = & $venvPython -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
    if ($LASTEXITCODE -eq 0 -and $probe -eq '3.12') {
        $pythonMode = 'venv'
    }
}
if ($null -eq $pythonMode -and (Get-Command py -ErrorAction SilentlyContinue)) {
    $probe = & py -3.12 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
    if ($LASTEXITCODE -eq 0 -and $probe -eq '3.12') {
        $pythonMode = 'launcher'
    }
}
if ($null -eq $pythonMode -and (Get-Command python -ErrorAction SilentlyContinue)) {
    $probe = & python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
    if ($LASTEXITCODE -eq 0 -and $probe -eq '3.12') {
        $pythonMode = 'path'
    }
}
if ($null -eq $pythonMode) {
    throw 'Python 3.12 is required. Install Python from python.org, then rerun this script.'
}

function Invoke-Python312 {
    if ($script:pythonMode -eq 'venv') {
        & $script:venvPython @args
    } elseif ($script:pythonMode -eq 'launcher') {
        & py -3.12 @args
    } else {
        & python @args
    }
}

$pythonVersion = Invoke-Python312 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
if ($LASTEXITCODE -ne 0 -or $pythonVersion -ne '3.12') {
    throw "Python 3.12 is required; the Python launcher could not select it."
}

$uvMode = $null
if (Get-Command uv -ErrorAction SilentlyContinue) {
    $uvMode = 'command'
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    & python -m uv --version *> $null
    if ($LASTEXITCODE -eq 0) {
        $uvMode = 'path-python'
    }
}
if ($null -eq $uvMode) {
    if ($pythonMode -eq 'venv') {
        Invoke-Python312 -m ensurepip --upgrade
        Invoke-Python312 -m pip install "uv==$uvVersion"
    } else {
        Invoke-Python312 -m pip install --user "uv==$uvVersion"
    }
    $uvMode = 'selected-python'
}

function Invoke-Uv {
    if ($script:uvMode -eq 'command') {
        & uv @args
    } elseif ($script:uvMode -eq 'path-python') {
        & python -m uv @args
    } else {
        Invoke-Python312 -m uv @args
    }
    if ($LASTEXITCODE -ne 0) {
        throw "uv command failed: $args"
    }
}

Invoke-Uv sync --python 3.12 --frozen --extra dev --extra ui --extra windows --extra capture --extra vision --extra language --extra translation
Invoke-Uv run gct-validate $repoRoot
Invoke-Uv run ruff format --check .
Invoke-Uv run ruff check .
Invoke-Uv run mypy
Invoke-Uv run pytest -m 'not language and not speech_native and not windows_ui and not vision and not translation_native'

if (-not $SkipPreCommit) {
    Invoke-Uv run pre-commit install
}

Write-Host 'Bootstrap complete. Launch with: uv run game-chat-translator'
