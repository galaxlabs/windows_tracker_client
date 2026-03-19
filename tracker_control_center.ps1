Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$configPath = Join-Path $projectRoot "config.json"
$buildScript = Join-Path $projectRoot "build_exe.ps1"
$installScript = Join-Path $projectRoot "install_service.ps1"
$setupScript = Join-Path $projectRoot "setup_config.ps1"
$syncExtensionScript = Join-Path $projectRoot "sync_browser_extension_config.ps1"
$runAgentScript = Join-Path $projectRoot "run_agent.ps1"
$extensionPath = Join-Path $projectRoot "browser_extension"

function Read-TrackerConfig {
    if (-not (Test-Path $configPath)) {
        return @{}
    }
    try {
        $raw = Get-Content $configPath -Raw | ConvertFrom-Json
        $result = @{}
        foreach ($property in $raw.PSObject.Properties) {
            $result[$property.Name] = $property.Value
        }
        return $result
    } catch {
        return @{}
    }
}

function Write-TrackerConfig {
    param([hashtable]$Config)
    $json = $Config | ConvertTo-Json -Depth 6
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($configPath, $json, $utf8NoBom)
}

function Get-TaskInfoText {
    try {
        $task = Get-ScheduledTaskInfo -TaskName "CCLMS-Tracker" -ErrorAction Stop
        return "Task running. Last result: $($task.LastTaskResult). Last run: $($task.LastRunTime)"
    } catch {
        return "Task not installed or not readable."
    }
}

function Get-TrackerProcessText {
    $items = Get-Process cclms-tracker -ErrorAction SilentlyContinue
    if (-not $items) {
        return "No cclms-tracker process running."
    }
    return "Processes: " + (($items | ForEach-Object { $_.Id }) -join ", ")
}

function Invoke-DetachedPowerShell {
    param([string]$FilePath)
    Start-Process powershell -ArgumentList @("-ExecutionPolicy", "Bypass", "-File", $FilePath) -WorkingDirectory $projectRoot
}

function Sync-ExtensionDefaultsFromConfig {
    & powershell -ExecutionPolicy Bypass -File $syncExtensionScript | Out-Null
    if ($mapsCheckbox.Checked -or $chatCheckbox.Checked) {
        $defaultsPath = Join-Path $extensionPath "local.defaults.js"
        if (Test-Path $defaultsPath) {
            $content = Get-Content $defaultsPath -Raw
            $content = $content -replace 'mapsEnabled: true', ("mapsEnabled: " + ($mapsCheckbox.Checked.ToString().ToLower()))
            $content = $content -replace 'chatEnabled: false', ("chatEnabled: " + ($chatCheckbox.Checked.ToString().ToLower()))
            Set-Content -Path $defaultsPath -Value $content -Encoding UTF8
        }
    }
}

$form = New-Object System.Windows.Forms.Form
$form.Text = "CCLMS Tracker Control Center"
$form.Size = New-Object System.Drawing.Size(900, 620)
$form.StartPosition = "CenterScreen"

$title = New-Object System.Windows.Forms.Label
$title.Text = "CCLMS Tracker Control Center"
$title.Font = New-Object System.Drawing.Font("Segoe UI", 16, [System.Drawing.FontStyle]::Bold)
$title.AutoSize = $true
$title.Location = New-Object System.Drawing.Point(20, 20)
$form.Controls.Add($title)

$statusLabel = New-Object System.Windows.Forms.Label
$statusLabel.Text = "Loading status..."
$statusLabel.AutoSize = $false
$statusLabel.Size = New-Object System.Drawing.Size(840, 40)
$statusLabel.Location = New-Object System.Drawing.Point(20, 58)
$form.Controls.Add($statusLabel)

$fields = @(
    @{ Label = "CRM Base URL"; Name = "site_url"; X = 20; Y = 110; Width = 400 },
    @{ Label = "API Key"; Name = "api_key"; X = 450; Y = 110; Width = 400 },
    @{ Label = "API Secret"; Name = "api_secret"; X = 20; Y = 180; Width = 400; Secret = $true },
    @{ Label = "Device ID"; Name = "device_id"; X = 450; Y = 180; Width = 400 },
    @{ Label = "GitHub Repo"; Name = "github_repo"; X = 20; Y = 250; Width = 400 },
    @{ Label = "GitHub Asset"; Name = "github_release_asset"; X = 450; Y = 250; Width = 400 }
)

$textBoxes = @{}
foreach ($field in $fields) {
    $label = New-Object System.Windows.Forms.Label
    $label.Text = $field.Label
    $label.Location = New-Object System.Drawing.Point($field.X, $field.Y)
    $label.Size = New-Object System.Drawing.Size($field.Width, 20)
    $form.Controls.Add($label)

    $textbox = New-Object System.Windows.Forms.TextBox
    $textbox.Name = $field.Name
    $textbox.Location = New-Object System.Drawing.Point($field.X, ($field.Y + 22))
    $textbox.Size = New-Object System.Drawing.Size($field.Width, 24)
    if ($field.Secret) {
        $textbox.UseSystemPasswordChar = $true
    }
    $form.Controls.Add($textbox)
    $textBoxes[$field.Name] = $textbox
}

$mapsCheckbox = New-Object System.Windows.Forms.CheckBox
$mapsCheckbox.Text = "Enable browser extension / Google Maps helper defaults"
$mapsCheckbox.Location = New-Object System.Drawing.Point(20, 324)
$mapsCheckbox.Size = New-Object System.Drawing.Size(400, 24)
$form.Controls.Add($mapsCheckbox)

$chatCheckbox = New-Object System.Windows.Forms.CheckBox
$chatCheckbox.Text = "Enable Google Chat notices in extension defaults"
$chatCheckbox.Location = New-Object System.Drawing.Point(450, 324)
$chatCheckbox.Size = New-Object System.Drawing.Size(400, 24)
$form.Controls.Add($chatCheckbox)

$logBox = New-Object System.Windows.Forms.TextBox
$logBox.Multiline = $true
$logBox.ScrollBars = "Vertical"
$logBox.ReadOnly = $true
$logBox.Location = New-Object System.Drawing.Point(20, 430)
$logBox.Size = New-Object System.Drawing.Size(830, 130)
$form.Controls.Add($logBox)

function Append-Log {
    param([string]$Message)
    $logBox.AppendText("[$(Get-Date -Format 'HH:mm:ss')] $Message`r`n")
}

function Refresh-UiFromConfig {
    $cfg = Read-TrackerConfig
    foreach ($key in $textBoxes.Keys) {
        $value = ""
        if ($cfg.ContainsKey($key) -and $null -ne $cfg[$key]) {
            $value = [string]$cfg[$key]
        }
        $textBoxes[$key].Text = $value
    }
    if (-not $textBoxes["device_id"].Text) {
        $textBoxes["device_id"].Text = $env:COMPUTERNAME
    }
    $mapsCheckbox.Checked = $true
    $chatCheckbox.Checked = $false
    $statusLabel.Text = "$(Get-TaskInfoText)`r`n$(Get-TrackerProcessText)"
}

function Collect-ConfigFromUi {
    $cfg = @{}
    foreach ($key in $textBoxes.Keys) {
        $value = $textBoxes[$key].Text.Trim()
        if ($value) {
            $cfg[$key] = $value
        }
    }
    if (-not $cfg["device_id"]) {
        $cfg["device_id"] = $env:COMPUTERNAME
    }
    return $cfg
}

$buttons = @(
    @{ Text = "Save Config"; X = 20; Y = 370; Action = {
            $cfg = Collect-ConfigFromUi
            Write-TrackerConfig -Config $cfg
            Append-Log "Saved config.json"
            Refresh-UiFromConfig
        }
    },
    @{ Text = "Open Setup UI"; X = 160; Y = 370; Action = {
            Invoke-DetachedPowerShell -FilePath $setupScript
            Append-Log "Opened setup_config.ps1"
        }
    },
    @{ Text = "Sync Extension"; X = 300; Y = 370; Action = {
            $cfg = Collect-ConfigFromUi
            Write-TrackerConfig -Config $cfg
            Sync-ExtensionDefaultsFromConfig
            Append-Log "Synced browser extension defaults from config.json"
        }
    },
    @{ Text = "Build EXE"; X = 440; Y = 370; Action = {
            Invoke-DetachedPowerShell -FilePath $buildScript
            Append-Log "Started build_exe.ps1"
        }
    },
    @{ Text = "Install / Refresh"; X = 580; Y = 370; Action = {
            Invoke-DetachedPowerShell -FilePath $installScript
            Append-Log "Started install_service.ps1"
        }
    },
    @{ Text = "Install All"; X = 720; Y = 370; Action = {
            try {
                $cfg = Collect-ConfigFromUi
                Write-TrackerConfig -Config $cfg
                Append-Log "Saved config.json"

                Sync-ExtensionDefaultsFromConfig
                Append-Log "Synced browser extension defaults"

                & powershell -ExecutionPolicy Bypass -File $buildScript | Out-Null
                Append-Log "Build complete"

                & powershell -ExecutionPolicy Bypass -File $installScript | Out-Null
                Append-Log "Install / refresh complete"

                Refresh-UiFromConfig
                Append-Log "Install All finished"
            } catch {
                Append-Log "Install All failed: $($_.Exception.Message)"
                [System.Windows.Forms.MessageBox]::Show($_.Exception.Message, "Install All Failed")
            }
        }
    },
    @{ Text = "Run Agent"; X = 20; Y = 405; Action = {
            Invoke-DetachedPowerShell -FilePath $runAgentScript
            Append-Log "Started run_agent.ps1"
        }
    },
    @{ Text = "Stop Tracker"; X = 160; Y = 405; Action = {
            try {
                Stop-ScheduledTask -TaskName "CCLMS-Tracker" -ErrorAction SilentlyContinue | Out-Null
            } catch {}
            Get-Process cclms-tracker -ErrorAction SilentlyContinue | Stop-Process -Force
            Append-Log "Stopped tracker task and process"
            Refresh-UiFromConfig
        }
    },
    @{ Text = "Start Tracker"; X = 300; Y = 405; Action = {
            Start-ScheduledTask -TaskName "CCLMS-Tracker"
            Append-Log "Started scheduled task"
            Refresh-UiFromConfig
        }
    },
    @{ Text = "Open Extension Folder"; X = 440; Y = 405; Action = {
            Start-Process explorer.exe $extensionPath
            Append-Log "Opened browser_extension folder"
        }
    },
    @{ Text = "Refresh Status"; X = 580; Y = 405; Action = {
            Refresh-UiFromConfig
            Append-Log "Refreshed status"
        }
    }
)

foreach ($buttonDef in $buttons) {
    $button = New-Object System.Windows.Forms.Button
    $button.Text = $buttonDef.Text
    $button.Location = New-Object System.Drawing.Point($buttonDef.X, $buttonDef.Y)
    $button.Size = New-Object System.Drawing.Size(120, 28)
    $button.Add_Click($buttonDef.Action)
    $form.Controls.Add($button)
}

Refresh-UiFromConfig
Append-Log "Control Center ready. config.json is the source of truth."

[void]$form.ShowDialog()
