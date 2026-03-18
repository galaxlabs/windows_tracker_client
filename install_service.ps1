param(
    [string]$ServiceName = "CCLMS-Tracker",
    [string]$NssmPath = "C:\nssm\nssm.exe",
    [ValidateSet("Auto", "Task", "Service")]
    [string]$InstallMode = "Auto"
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$exePath = Join-Path $projectRoot "dist\cclms-tracker.exe"
$configPath = Join-Path $projectRoot "config.json"
$setupScript = Join-Path $projectRoot "setup_config.ps1"

function Get-TrackerConfig {
    param([string]$Path)
    if (-not (Test-Path $Path)) {
        return @{}
    }
    try {
        $raw = Get-Content $Path -Raw | ConvertFrom-Json
        $result = @{}
        foreach ($property in $raw.PSObject.Properties) {
            $result[$property.Name] = $property.Value
        }
        return $result
    } catch {
        return @{}
    }
}

function Has-Value {
    param($Value)
    return ($null -ne $Value -and [string]::IsNullOrWhiteSpace([string]$Value) -eq $false)
}

function Test-NeedsSetup {
    param([hashtable]$Config)

    if (-not (Has-Value ($Config["device_id"]))) {
        return $true
    }

    $hasSite = Has-Value ($Config["site_url"])
    $hasKey = Has-Value ($Config["api_key"])
    $hasSecret = Has-Value ($Config["api_secret"])

    if (($hasSite -or $hasKey -or $hasSecret) -and -not ($hasSite -and $hasKey -and $hasSecret)) {
        return $true
    }

    return $false
}

function Resolve-NssmPath {
    param(
        [string]$RequestedPath,
        [string]$ProjectRoot
    )

    $candidates = [System.Collections.Generic.List[string]]::new()

    if (Has-Value $RequestedPath) {
        $candidates.Add($RequestedPath)
    }

    $command = Get-Command "nssm.exe" -ErrorAction SilentlyContinue
    if ($command -and (Has-Value $command.Source)) {
        $candidates.Add($command.Source)
    }

    $candidates.Add((Join-Path $ProjectRoot "nssm.exe"))
    $candidates.Add("C:\nssm\nssm.exe")
    $candidates.Add("${env:ProgramFiles}\nssm\win64\nssm.exe")
    $candidates.Add("${env:ProgramFiles(x86)}\nssm\win64\nssm.exe")
    $candidates.Add("${env:ChocolateyInstall}\bin\nssm.exe")

    foreach ($candidate in $candidates) {
        if (Has-Value $candidate -and (Test-Path -LiteralPath $candidate)) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }

    $checked = $candidates | Where-Object { Has-Value $_ } | Select-Object -Unique
    throw "nssm.exe was not found. Checked: $($checked -join ', '). Install NSSM, add it to PATH, copy nssm.exe next to install_service.ps1, or run .\install_service.ps1 -NssmPath '<full path to nssm.exe>'"
}

function Install-WithScheduledTask {
    param(
        [string]$TaskName,
        [string]$ExecutablePath,
        [string]$ConfigFilePath,
        [string]$WorkingDirectory
    )

    $actionArgs = '"' + $ConfigFilePath + '"'
    $action = New-ScheduledTaskAction -Execute $ExecutablePath -Argument $actionArgs -WorkingDirectory $WorkingDirectory
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
    $principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances Ignore

    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
    Start-ScheduledTask -TaskName $TaskName

    Write-Host "Scheduled task installed and started: $TaskName"
}

function Install-WithNssm {
    param(
        [string]$ResolvedNssmPath,
        [string]$TaskName,
        [string]$ExecutablePath,
        [string]$ConfigFilePath,
        [string]$WorkingDirectory
    )

    & $ResolvedNssmPath install $TaskName $ExecutablePath $ConfigFilePath
    & $ResolvedNssmPath set $TaskName AppDirectory $WorkingDirectory
    & $ResolvedNssmPath set $TaskName Start SERVICE_AUTO_START
    & $ResolvedNssmPath start $TaskName

    Write-Host "Service installed and started via NSSM: $TaskName"
}

if (-not (Test-Path $exePath)) {
    throw "Tracker EXE not found at $exePath. Run build_exe.ps1 first."
}

$config = Get-TrackerConfig -Path $configPath
if (Test-NeedsSetup -Config $config) {
    if (-not (Test-Path $setupScript)) {
        throw "Setup script not found at $setupScript"
    }
    & powershell -ExecutionPolicy Bypass -File $setupScript -ConfigPath $configPath
    $config = Get-TrackerConfig -Path $configPath
}

if (-not (Has-Value ($config["device_id"]))) {
    throw "Device ID is still missing in config.json"
}

$resolvedNssmPath = $null
try {
    $resolvedNssmPath = Resolve-NssmPath -RequestedPath $NssmPath -ProjectRoot $projectRoot
} catch {
    if ($InstallMode -eq "Service") {
        throw
    }
}

if ($InstallMode -eq "Task" -or (-not $resolvedNssmPath)) {
    Install-WithScheduledTask -TaskName $ServiceName -ExecutablePath $exePath -ConfigFilePath $configPath -WorkingDirectory $projectRoot
} else {
    Install-WithNssm -ResolvedNssmPath $resolvedNssmPath -TaskName $ServiceName -ExecutablePath $exePath -ConfigFilePath $configPath -WorkingDirectory $projectRoot
}
