$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectRoot

. (Join-Path $projectRoot "bootstrap_env.ps1")

function Stop-RunningTracker {
    param([string]$TaskName = "CCLMS-Tracker")

    $scheduledTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($scheduledTask) {
        try {
            Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        } catch {
        }
    }

    $service = Get-Service -Name $TaskName -ErrorAction SilentlyContinue
    if ($service -and $service.Status -ne "Stopped") {
        try {
            Stop-Service -Name $TaskName -Force -ErrorAction SilentlyContinue
        } catch {
        }
    }

    Get-Process "cclms-tracker", "python", "pythonw" -ErrorAction SilentlyContinue |
        Where-Object {
            $_.Path -like "$projectRoot*" -or $_.ProcessName -eq "cclms-tracker"
        } |
        Stop-Process -Force -ErrorAction SilentlyContinue

    Start-Sleep -Seconds 2
}

<<<<<<< HEAD
$venvPython = ".\.venv\Scripts\python.exe"
$pythonCmd = $venvPython
$useSystemPython = $false
=======
Stop-RunningTracker
>>>>>>> a086edfe20fb9ff0ca2355721b3b1bf389fe16f0

$envInfo = Initialize-TrackerVenv -ProjectRoot $projectRoot -RequirementsFiles @(
    (Join-Path $projectRoot "requirements.txt"),
    (Join-Path $projectRoot "requirements-build.txt")
)

<<<<<<< HEAD
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
=======
$venvPython = $envInfo.PythonPath

& $venvPython -m PyInstaller --clean --noconfirm .\tracker.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed." }
>>>>>>> a086edfe20fb9ff0ca2355721b3b1bf389fe16f0

Write-Host ""
Write-Host "Build complete."
Write-Host "EXE: $projectRoot\dist\cclms-tracker.exe"
Write-Host "Use setup_config.ps1 or install_service.ps1 if you want a popup to collect missing CRM details."
