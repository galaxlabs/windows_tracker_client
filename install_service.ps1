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

    $hasSite = Has-Value ($Config["site_url"])
    $hasKey = Has-Value ($Config["api_key"])
    $hasSecret = Has-Value ($Config["api_secret"])

    if (($hasSite -or $hasKey -or $hasSecret) -and -not ($hasSite -and $hasKey -and $hasSecret)) {
        return $true
    }

    return $false
}

function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Ensure-DeviceId {
    param(
        [hashtable]$Config,
        [string]$ConfigPath
    )

    if (Has-Value ($Config["device_id"])) {
        return $Config
    }

    $Config["device_id"] = $env:COMPUTERNAME
    $json = $Config | ConvertTo-Json -Depth 4
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($ConfigPath, $json, $utf8NoBom)
    return $Config
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
            return [System.IO.Path]::GetFullPath($candidate)
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

    if (-not (Test-IsAdministrator)) {
        throw "Scheduled task installation requires an elevated PowerShell window. Reopen PowerShell as Administrator and rerun .\install_service.ps1 -InstallMode Task"
    }

    $actionArgs = '"' + $ConfigFilePath + '"'
    $action = New-ScheduledTaskAction -Execute $ExecutablePath -Argument $actionArgs -WorkingDirectory $WorkingDirectory
    $logonTrigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
    $logonTrigger.Delay = "PT1M"
    $startupTrigger = New-ScheduledTaskTrigger -AtStartup
    $triggers = @($logonTrigger, $startupTrigger)
    $principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances Ignore -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)

    try {
        Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    } catch {
    }
    Get-Process "cclms-tracker" -ErrorAction SilentlyContinue | Stop-Process -Force

    $existingTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($existingTask) {
        try {
            Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        } catch {
        }
    }

    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $triggers -Principal $principal -Settings $settings -Force | Out-Null
    Start-ScheduledTask -TaskName $TaskName

    Write-Host "Scheduled task installed, refreshed, and started: $TaskName"
}

function Install-WithNssm {
    param(
        [string]$ResolvedNssmPath,
        [string]$TaskName,
        [string]$ExecutablePath,
        [string]$ConfigFilePath,
        [string]$WorkingDirectory
    )

    if (-not (Test-IsAdministrator)) {
        throw "Service installation requires an elevated PowerShell window. Reopen PowerShell as Administrator and rerun .\install_service.ps1 -InstallMode Service -NssmPath '<real path to nssm.exe>'"
    }

    & $ResolvedNssmPath status $TaskName | Out-Null
    $serviceExists = ($LASTEXITCODE -eq 0)

    if ($serviceExists) {
        & $ResolvedNssmPath stop $TaskName | Out-Null
    } else {
        & $ResolvedNssmPath install $TaskName $ExecutablePath $ConfigFilePath
    }

    & $ResolvedNssmPath set $TaskName Application $ExecutablePath
    & $ResolvedNssmPath set $TaskName AppParameters $ConfigFilePath
    & $ResolvedNssmPath set $TaskName AppDirectory $WorkingDirectory
    & $ResolvedNssmPath set $TaskName Start SERVICE_AUTO_START
    & $ResolvedNssmPath set $TaskName AppExit Default Restart
    & $ResolvedNssmPath start $TaskName

    Write-Host "Service installed or refreshed and started via NSSM: $TaskName"
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

$config = Ensure-DeviceId -Config $config -ConfigPath $configPath

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
