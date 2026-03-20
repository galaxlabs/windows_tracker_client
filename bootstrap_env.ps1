Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Get-SystemPythonCommand {
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        return [string]$py.Source
    }

    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        return [string]$python.Source
    }

    throw "Python was not found in PATH. Install Python 3 and rerun this script."
}

function Invoke-ExternalCommand {
    param(
        [Parameter(Mandatory = $true)][string]$Executable,
        [string[]]$Arguments = @(),
        [Parameter(Mandatory = $true)][string]$FailureMessage
    )

    & $Executable @Arguments | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw $FailureMessage
    }
}

function Test-VenvHealthy {
    param([Parameter(Mandatory = $true)][string]$PythonPath)

    if (-not (Test-Path -LiteralPath $PythonPath)) {
        return $false
    }

    & $PythonPath -c "import sys; print(sys.executable)" | Out-Null
    if ($LASTEXITCODE -ne 0) {
        return $false
    }

    & $PythonPath -m pip --version | Out-Null
    return ($LASTEXITCODE -eq 0)
}

function Ensure-Pip {
    param([Parameter(Mandatory = $true)][string]$PythonPath)

    & $PythonPath -m pip --version | Out-Null
    if ($LASTEXITCODE -eq 0) {
        return
    }

    & $PythonPath -m ensurepip --upgrade
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to bootstrap pip inside the tracker virtual environment."
    }
}

function Test-DependencySetAvailable {
    param(
        [Parameter(Mandatory = $true)][string]$PythonPath
    )

    $script = @"
import importlib
required = ["psutil", "requests", "win32gui", "PIL"]
missing = []
for name in required:
    try:
        importlib.import_module(name)
    except Exception:
        missing.append(name)
if missing:
    raise SystemExit("missing:" + ",".join(missing))
"@

    & $PythonPath -c $script | Out-Null
    return ($LASTEXITCODE -eq 0)
}

function Get-FileHashString {
    param([Parameter(Mandatory = $true)][string[]]$Paths)

    $builder = New-Object System.Text.StringBuilder
    foreach ($path in $Paths) {
        if (Test-Path -LiteralPath $path) {
            $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $path).Hash
            [void]$builder.AppendLine("$path=$hash")
        }
    }
    return $builder.ToString()
}

function Initialize-TrackerVenv {
    param(
        [Parameter(Mandatory = $true)][string]$ProjectRoot,
        [Parameter(Mandatory = $true)][string[]]$RequirementsFiles
    )

    $primaryVenv = Join-Path $ProjectRoot ".venv"
    $fallbackVenv = Join-Path $ProjectRoot ".venv-repair"
    $candidateRoots = @($primaryVenv, $fallbackVenv)
    $selectedRoot = $primaryVenv
    $pythonPath = Join-Path $selectedRoot "Scripts\python.exe"

    foreach ($root in $candidateRoots) {
        $candidatePython = Join-Path $root "Scripts\python.exe"
        if (Test-VenvHealthy -PythonPath $candidatePython) {
            $selectedRoot = $root
            $pythonPath = $candidatePython
            break
        }
    }

    if (-not (Test-VenvHealthy -PythonPath $pythonPath)) {
        $systemPython = Get-SystemPythonCommand

        foreach ($root in $candidateRoots) {
            if (Test-Path -LiteralPath $root) {
                try {
                    Remove-Item -LiteralPath $root -Recurse -Force -ErrorAction Stop
                } catch {
                    Write-Warning "Could not remove $root. It may still be in use."
                }
            }
        }

        $targetRoot = $primaryVenv
        if (Test-Path -LiteralPath $primaryVenv) {
            $targetRoot = $fallbackVenv
            if (Test-Path -LiteralPath $fallbackVenv) {
                Remove-Item -LiteralPath $fallbackVenv -Recurse -Force -ErrorAction SilentlyContinue
            }
        }

        $createArgs = @("-m", "venv", $targetRoot)
        Invoke-ExternalCommand -Executable $systemPython -Arguments $createArgs -FailureMessage "Failed to create the tracker virtual environment."

        $selectedRoot = $targetRoot
        $pythonPath = Join-Path $selectedRoot "Scripts\python.exe"
        Ensure-Pip -PythonPath $pythonPath
    } else {
        Ensure-Pip -PythonPath $pythonPath
    }

    $stampPath = Join-Path $selectedRoot ".requirements.sha256"
    $currentHash = Get-FileHashString -Paths $RequirementsFiles
    $storedHash = ""
    if (Test-Path -LiteralPath $stampPath) {
        $storedHash = Get-Content -LiteralPath $stampPath -Raw
    }

    if ($currentHash -ne $storedHash) {
        $installArgs = @("-m", "pip", "install")
        foreach ($file in $RequirementsFiles) {
            if (Test-Path -LiteralPath $file) {
                $installArgs += @("-r", $file)
            }
        }

        try {
            Invoke-ExternalCommand -Executable $pythonPath -Arguments $installArgs -FailureMessage "Failed to install tracker dependencies."
        } catch {
            Write-Warning "Dependency install failed. Checking whether existing packages are already sufficient."
            if (-not (Test-DependencySetAvailable -PythonPath $pythonPath)) {
                throw
            }
            Write-Warning "Continuing with the existing virtual environment packages because required build dependencies are already available."
        }
        Set-Content -LiteralPath $stampPath -Value $currentHash -Encoding UTF8
    }

    return [pscustomobject]@{
        VenvRoot = $selectedRoot
        PythonPath = $pythonPath
    }
}
