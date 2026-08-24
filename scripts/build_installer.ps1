[CmdletBinding()]
param(
    [string]$Version = '0.1.0',
    [switch]$SkipInstaller
)

$ErrorActionPreference = 'Stop'
$repoRoot = [System.IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$artifactRoot = [System.IO.Path]::GetFullPath((Join-Path $repoRoot 'artifacts'))
$buildRoot = [System.IO.Path]::GetFullPath((Join-Path $repoRoot 'build\pyinstaller'))
$distRoot = [System.IO.Path]::GetFullPath((Join-Path $artifactRoot 'Game Chat Translator'))
$frozenRoot = Join-Path $distRoot 'GameChatTranslator'

foreach ($target in @($artifactRoot, $buildRoot)) {
    if (-not $target.StartsWith($repoRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to clean a build path outside the repository: $target"
    }
}
if (Test-Path -LiteralPath $artifactRoot) {
    Remove-Item -LiteralPath $artifactRoot -Recurse -Force
}
if (Test-Path -LiteralPath $buildRoot) {
    Remove-Item -LiteralPath $buildRoot -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $artifactRoot, $distRoot | Out-Null

$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw 'The locked .venv Python runtime is unavailable. Run scripts\bootstrap.ps1 first.'
}

$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
$env:HF_DATASETS_OFFLINE = '1'
$env:PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK = 'True'

& $python -m PyInstaller `
    --noconfirm `
    --clean `
    --workpath $buildRoot `
    --distpath $distRoot `
    (Join-Path $repoRoot 'packaging\GameChatTranslator.spec')
if ($LASTEXITCODE -ne 0) {
    throw 'PyInstaller failed.'
}

$frozenExe = Join-Path $frozenRoot 'GameChatTranslator.exe'
if (-not (Test-Path -LiteralPath $frozenExe -PathType Leaf)) {
    throw 'PyInstaller did not produce the frozen application executable.'
}
& $python (Join-Path $repoRoot 'scripts\generate_runtime_licenses.py') `
    --output (Join-Path $frozenRoot 'licenses\runtime')
if ($LASTEXITCODE -ne 0) {
    throw 'Runtime license inventory generation failed.'
}
Copy-Item -LiteralPath (Join-Path $repoRoot 'THIRD_PARTY_NOTICES.md') `
    -Destination (Join-Path $frozenRoot 'licenses\THIRD_PARTY_NOTICES.md')
Copy-Item -LiteralPath (Join-Path $repoRoot 'LICENSE') `
    -Destination (Join-Path $frozenRoot 'licenses\GameChatTranslator-Apache-2.0.txt')
Copy-Item -Path (Join-Path $repoRoot 'licenses\*') `
    -Destination (Join-Path $frozenRoot 'licenses') -Force
$torchResidual = Join-Path $frozenRoot '_internal\torch\lib\libiomp5md.dll'
if (Test-Path -LiteralPath $torchResidual -PathType Leaf) {
    Remove-Item -LiteralPath $torchResidual -Force
}
$asioResidual = Join-Path $frozenRoot `
    '_internal\_sounddevice_data\portaudio-binaries\libportaudio64bit-asio.dll'
if (Test-Path -LiteralPath $asioResidual -PathType Leaf) {
    Remove-Item -LiteralPath $asioResidual -Force
}
$cudaResidual = Join-Path $frozenRoot '_internal\ctranslate2\cudnn64_9.dll'
if (Test-Path -LiteralPath $cudaResidual -PathType Leaf) {
    Remove-Item -LiteralPath $cudaResidual -Force
}
& $python (Join-Path $repoRoot 'scripts\verify_release_contents.py') --root $frozenRoot
if ($LASTEXITCODE -ne 0) {
    throw 'Frozen artifact privacy/dependency inspection failed.'
}
& $python (Join-Path $repoRoot 'scripts\generate_artifact_inventory.py') `
    --root $frozenRoot --output (Join-Path $artifactRoot 'frozen-file-inventory.json')
if ($LASTEXITCODE -ne 0) {
    throw 'Frozen artifact inventory generation failed.'
}

function Invoke-FrozenSmoke([string]$Argument) {
    $process = Start-Process -FilePath $frozenExe -ArgumentList $Argument -PassThru
    if (-not $process.WaitForExit(60000)) {
        $process.Kill($true)
        throw "Frozen smoke timed out: $Argument"
    }
    return $process.ExitCode
}

if ((Invoke-FrozenSmoke '--packaging-smoke') -ne 0) {
    throw 'Frozen application resource/import smoke failed.'
}
$env:GCT_SMOKE_REPORT = Join-Path $artifactRoot 'frozen-runtime-smoke.log'
Remove-Item -LiteralPath $env:GCT_SMOKE_REPORT -Force -ErrorAction SilentlyContinue
if ((Invoke-FrozenSmoke '--frozen-runtime-smoke') -ne 0) {
    throw 'Frozen native runtime or subprocess smoke failed.'
}

if ($SkipInstaller) {
    Write-Host "Frozen application ready: $frozenRoot"
    exit 0
}

$isccCandidates = @(
    (Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 6\ISCC.exe'),
    (Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe'),
    (Join-Path $env:ProgramFiles 'Inno Setup 6\ISCC.exe')
)
$iscc = $isccCandidates | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } |
    Select-Object -First 1
if ($null -eq $iscc) {
    throw 'Inno Setup 6 is required to build the supported installer.'
}
& $iscc "/DMyAppVersion=$Version" "/DSourceDir=$frozenRoot" `
    (Join-Path $repoRoot 'installer\GameChatTranslator.iss')
if ($LASTEXITCODE -ne 0) {
    throw 'Inno Setup failed.'
}

$installer = Join-Path $artifactRoot 'installer\GameChatTranslator-Setup-x64.exe'
if (-not (Test-Path -LiteralPath $installer -PathType Leaf)) {
    throw 'The installer artifact was not produced.'
}
$hash = (Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash.ToLowerInvariant()
$checksum = "$hash  $([System.IO.Path]::GetFileName($installer))`n"
[System.IO.File]::WriteAllText("$installer.sha256", $checksum, [System.Text.Encoding]::ASCII)
Write-Host "Installer ready: $installer"
Write-Host "SHA-256: $hash"
