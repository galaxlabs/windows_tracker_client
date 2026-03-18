param(
    [string]$ConfigPath = ""
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectRoot

. (Join-Path $projectRoot "bootstrap_env.ps1")

$envInfo = Initialize-TrackerVenv -ProjectRoot $projectRoot -RequirementsFiles @(
    (Join-Path $projectRoot "requirements.txt")
)

$pythonPath = $envInfo.PythonPath
$arguments = @("agent.py")

if ($ConfigPath) {
    $arguments += $ConfigPath
} elseif (Test-Path -LiteralPath (Join-Path $projectRoot "config.json")) {
    $arguments += "config.json"
}

& $pythonPath @arguments
exit $LASTEXITCODE
