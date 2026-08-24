[CmdletBinding()]
param(
    [string]$Installer = ''
)

$ErrorActionPreference = 'Stop'
$repoRoot = [System.IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$smokeRoot = [System.IO.Path]::GetFullPath((Join-Path $repoRoot 'artifacts\installer-smoke'))
if (-not $smokeRoot.StartsWith($repoRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to use a smoke path outside the repository: $smokeRoot"
}
if ([string]::IsNullOrWhiteSpace($Installer)) {
    $Installer = Join-Path $repoRoot 'artifacts\installer\GameChatTranslator-Setup-x64.exe'
}
$Installer = [System.IO.Path]::GetFullPath($Installer)
if (-not (Test-Path -LiteralPath $Installer -PathType Leaf)) {
    throw "Installer is unavailable: $Installer"
}
if (Test-Path -LiteralPath $smokeRoot) {
    Remove-Item -LiteralPath $smokeRoot -Recurse -Force
}
$installRoot = Join-Path $smokeRoot 'Installed App'
$logPath = Join-Path $smokeRoot 'install.log'
New-Item -ItemType Directory -Force -Path $smokeRoot | Out-Null

function Invoke-AndWait([string]$FilePath, [string[]]$Arguments) {
    $process = Start-Process -FilePath $FilePath -ArgumentList $Arguments -PassThru
    if (-not $process.WaitForExit(120000)) {
        $process.Kill($true)
        throw "Process timed out: $FilePath"
    }
    return $process.ExitCode
}

$installCode = Invoke-AndWait $Installer @(
    '/VERYSILENT',
    '/SUPPRESSMSGBOXES',
    '/NORESTART',
    ('/DIR="' + $installRoot + '"'),
    ('/LOG="' + $logPath + '"')
)
if ($installCode -ne 0) {
    throw "Silent install failed with exit code $installCode."
}
$application = Join-Path $installRoot 'GameChatTranslator.exe'
$uninstaller = Join-Path $installRoot 'unins000.exe'
if (-not (Test-Path -LiteralPath $application -PathType Leaf) -or
    -not (Test-Path -LiteralPath $uninstaller -PathType Leaf)) {
    throw 'Silent install did not produce the expected application and uninstaller.'
}

$savedPath = $env:PATH
try {
    $env:PATH = "$env:SystemRoot\System32;$env:SystemRoot"
    if ((Invoke-AndWait $application @('--packaging-smoke')) -ne 0) {
        throw 'Installed application resource smoke failed.'
    }
    $env:GCT_SMOKE_REPORT = Join-Path $smokeRoot 'frozen-runtime-smoke.log'
    if ((Invoke-AndWait $application @('--frozen-runtime-smoke')) -ne 0) {
        throw 'Installed application native runtime smoke failed.'
    }
}
finally {
    $env:PATH = $savedPath
}

$uninstallCode = Invoke-AndWait $uninstaller @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART')
if ($uninstallCode -ne 0) {
    throw "Silent uninstall failed with exit code $uninstallCode."
}
if (Test-Path -LiteralPath $application) {
    throw 'Silent uninstall left the installed application behind.'
}
Write-Host "Installer smoke passed: $Installer"
