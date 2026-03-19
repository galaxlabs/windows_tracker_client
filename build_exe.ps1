$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectRoot

if (-not (Test-Path ".venv")) {
    py -m venv .venv
}

$venvPython = ".\.venv\Scripts\python.exe"
$pythonCmd = $venvPython
$useSystemPython = $false

& $venvPython -m pip --version | Out-Null
if ($LASTEXITCODE -ne 0) {
    $useSystemPython = $true
}

if ($useSystemPython) {
    Write-Host "Virtualenv pip is unavailable. Falling back to system Python for build dependencies."
    & py -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) { throw "Failed to upgrade system pip" }
    & py -m pip install -r .\requirements.txt -r .\requirements-build.txt
    if ($LASTEXITCODE -ne 0) { throw "Failed to install build dependencies with system Python" }
    $pythonCmd = "py"
} else {
    & $venvPython -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) { throw "Failed to upgrade virtualenv pip" }
    & $venvPython -m pip install -r .\requirements.txt -r .\requirements-build.txt
    if ($LASTEXITCODE -ne 0) { throw "Failed to install build dependencies in virtualenv" }
}

& $pythonCmd -m PyInstaller --clean --noconfirm .\tracker.spec
if ($LASTEXITCODE -ne 0) {
    if ($useSystemPython) {
        throw "PyInstaller build failed with system Python"
    }
    throw "PyInstaller build failed in virtualenv"
}

Write-Host ""
Write-Host "Build complete."
Write-Host "EXE: $projectRoot\dist\cclms-tracker.exe"
Write-Host "Use setup_config.ps1 or install_service.ps1 if you want a popup to collect missing CRM details."
