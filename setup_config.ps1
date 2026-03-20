param(
    [string]$ConfigPath = ""
)

$ErrorActionPreference = "Stop"

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

if (-not $ConfigPath) {
    $projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
    $ConfigPath = Join-Path $projectRoot "config.json"
}

function Read-Config {
    param([string]$Path)

    $result = @{}
    if (-not (Test-Path $Path)) {
        return $result
    }

    try {
        $raw = Get-Content $Path -Raw | ConvertFrom-Json
        foreach ($property in $raw.PSObject.Properties) {
            $result[$property.Name] = $property.Value
        }
    } catch {
        $result = @{}
    }
    return $result
}

function Write-Config {
    param(
        [string]$Path,
        [hashtable]$Payload
    )

    $json = $Payload | ConvertTo-Json -Depth 6
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $json, $utf8NoBom)
}

function Get-StringValue {
    param($Config, [string]$Name, [string]$Default = "")
    if ($Config.ContainsKey($Name) -and $null -ne $Config[$Name]) {
        return [string]$Config[$Name]
    }
    return $Default
}

function Get-BoolValue {
    param($Config, [string]$Name, [bool]$Default = $false)
    if ($Config.ContainsKey($Name) -and $null -ne $Config[$Name]) {
        return [System.Convert]::ToBoolean($Config[$Name])
    }
    return $Default
}

function Get-IntValue {
    param($Config, [string]$Name, [int]$Default = 0)
    if ($Config.ContainsKey($Name) -and $null -ne $Config[$Name] -and "$($Config[$Name])".Trim()) {
        return [string][int]$Config[$Name]
    }
    return [string]$Default
}

$existing = Read-Config -Path $ConfigPath

$form = New-Object System.Windows.Forms.Form
$form.Text = "CCLMS Tracker Setup"
$form.Size = New-Object System.Drawing.Size(760, 720)
$form.StartPosition = "CenterScreen"
$form.FormBorderStyle = "FixedDialog"
$form.MaximizeBox = $false
$form.MinimizeBox = $false

$panel = New-Object System.Windows.Forms.Panel
$panel.Location = New-Object System.Drawing.Point(10, 10)
$panel.Size = New-Object System.Drawing.Size(720, 610)
$panel.AutoScroll = $true
$form.Controls.Add($panel)

$textFields = @(
    @{ Label = "CRM Base URL"; Name = "site_url"; Help = "Leave blank to use embedded default."; Secret = $false; Default = "" },
    @{ Label = "API Key"; Name = "api_key"; Help = "Leave blank to use embedded default."; Secret = $false; Default = "" },
    @{ Label = "API Secret"; Name = "api_secret"; Help = "Leave blank to use embedded default."; Secret = $true; Default = "" },
    @{ Label = "Device ID"; Name = "device_id"; Help = "Recommended: laptop hostname."; Secret = $false; Default = $env:COMPUTERNAME },
    @{ Label = "GitHub Repo"; Name = "github_repo"; Help = "Optional release repo override."; Secret = $false; Default = "galaxlabs/windows_tracker_client" },
    @{ Label = "GitHub Asset"; Name = "github_release_asset"; Help = "Optional release asset override."; Secret = $false; Default = "cclms-tracker-windows-x64.zip" }
)

$numberFields = @(
    @{ Label = "Notification Poll Seconds"; Name = "notifications_poll_seconds"; Help = "How often the client checks CRM for alerts."; Default = 60 },
    @{ Label = "Device Action Poll Seconds"; Name = "device_actions_poll_seconds"; Help = "How often the client checks CRM for pending actions."; Default = 60 },
    @{ Label = "Device Health Poll Seconds"; Name = "device_health_poll_seconds"; Help = "How often health reports are sent to CRM."; Default = 300 },
    @{ Label = "Biometric Sync Minutes"; Name = "biometric_sync_interval_minutes"; Help = "How often biometric attendance sync runs."; Default = 15 },
    @{ Label = "Auto Update Check Minutes"; Name = "auto_update_check_minutes"; Help = "How often release checks run."; Default = 360 }
)

$toggleFields = @(
    @{ Label = "Enable Notifications"; Name = "notifications_enabled"; Default = $true },
    @{ Label = "Enable Device Actions"; Name = "device_actions_enabled"; Default = $false },
    @{ Label = "Enable Device Health"; Name = "device_health_enabled"; Default = $false },
    @{ Label = "Enable Biometric Sync"; Name = "biometric_sync_enabled"; Default = $false },
    @{ Label = "Enable Map Intelligence"; Name = "map_intelligence_enabled"; Default = $false },
    @{ Label = "Enable Call Metadata"; Name = "call_metadata_enabled"; Default = $true },
    @{ Label = "Enable Auto Update"; Name = "auto_update_enabled"; Default = $true },
    @{ Label = "Verify SSL"; Name = "verify_ssl"; Default = $true }
)

$controls = @{}
$y = 10

function Add-SectionLabel {
    param([string]$Text, [int]$Y)
    $label = New-Object System.Windows.Forms.Label
    $label.Text = $Text
    $label.Font = New-Object System.Drawing.Font("Segoe UI", 10, [System.Drawing.FontStyle]::Bold)
    $label.Location = New-Object System.Drawing.Point(10, $Y)
    $label.Size = New-Object System.Drawing.Size(680, 22)
    $panel.Controls.Add($label)
}

Add-SectionLabel -Text "Connection" -Y $y
$y += 30

foreach ($item in $textFields) {
    $label = New-Object System.Windows.Forms.Label
    $label.Text = $item.Label
    $label.Location = New-Object System.Drawing.Point(10, $y)
    $label.Size = New-Object System.Drawing.Size(220, 20)
    $panel.Controls.Add($label)

    $textbox = New-Object System.Windows.Forms.TextBox
    $textbox.Name = $item.Name
    $textbox.Location = New-Object System.Drawing.Point(10, ($y + 22))
    $textbox.Size = New-Object System.Drawing.Size(680, 24)
    if ($item.Secret) {
        $textbox.UseSystemPasswordChar = $true
    }
    $textbox.Text = Get-StringValue -Config $existing -Name $item.Name -Default $item.Default
    $panel.Controls.Add($textbox)
    $controls[$item.Name] = $textbox

    $help = New-Object System.Windows.Forms.Label
    $help.Text = $item.Help
    $help.ForeColor = [System.Drawing.Color]::DimGray
    $help.Location = New-Object System.Drawing.Point(10, ($y + 48))
    $help.Size = New-Object System.Drawing.Size(680, 18)
    $panel.Controls.Add($help)

    $y += 72
}

Add-SectionLabel -Text "Runtime Toggles" -Y $y
$y += 30

for ($i = 0; $i -lt $toggleFields.Count; $i++) {
    $item = $toggleFields[$i]
    $checkbox = New-Object System.Windows.Forms.CheckBox
    $checkbox.Text = $item.Label
    $checkbox.Name = $item.Name
    $checkbox.AutoSize = $false
    $checkbox.Size = New-Object System.Drawing.Size(320, 24)
    $checkbox.Location = New-Object System.Drawing.Point(10 + (340 * ($i % 2)), $y)
    $checkbox.Checked = Get-BoolValue -Config $existing -Name $item.Name -Default $item.Default
    $panel.Controls.Add($checkbox)
    $controls[$item.Name] = $checkbox

    if (($i % 2) -eq 1) {
        $y += 30
    }
}
if (($toggleFields.Count % 2) -eq 1) {
    $y += 30
}

Add-SectionLabel -Text "Intervals" -Y $y
$y += 30

foreach ($item in $numberFields) {
    $label = New-Object System.Windows.Forms.Label
    $label.Text = $item.Label
    $label.Location = New-Object System.Drawing.Point(10, $y)
    $label.Size = New-Object System.Drawing.Size(240, 20)
    $panel.Controls.Add($label)

    $textbox = New-Object System.Windows.Forms.TextBox
    $textbox.Name = $item.Name
    $textbox.Location = New-Object System.Drawing.Point(10, ($y + 22))
    $textbox.Size = New-Object System.Drawing.Size(180, 24)
    $textbox.Text = Get-IntValue -Config $existing -Name $item.Name -Default $item.Default
    $panel.Controls.Add($textbox)
    $controls[$item.Name] = $textbox

    $help = New-Object System.Windows.Forms.Label
    $help.Text = $item.Help
    $help.ForeColor = [System.Drawing.Color]::DimGray
    $help.Location = New-Object System.Drawing.Point(210, ($y + 24))
    $help.Size = New-Object System.Drawing.Size(480, 18)
    $panel.Controls.Add($help)

    $y += 52
}

$saveButton = New-Object System.Windows.Forms.Button
$saveButton.Text = "Save"
$saveButton.Location = New-Object System.Drawing.Point(550, 635)
$saveButton.Size = New-Object System.Drawing.Size(80, 30)

$cancelButton = New-Object System.Windows.Forms.Button
$cancelButton.Text = "Cancel"
$cancelButton.Location = New-Object System.Drawing.Point(645, 635)
$cancelButton.Size = New-Object System.Drawing.Size(80, 30)

$saveButton.Add_Click({
    $deviceId = $controls["device_id"].Text.Trim()
    if (-not $deviceId) {
        [System.Windows.Forms.MessageBox]::Show("Device ID is required.", "CCLMS Tracker Setup")
        return
    }

    $payload = @{}

    foreach ($field in $textFields) {
        $value = $controls[$field.Name].Text.Trim()
        if ($value) {
            $payload[$field.Name] = $value
        }
    }

    foreach ($field in $toggleFields) {
        $payload[$field.Name] = [bool]$controls[$field.Name].Checked
    }

    foreach ($field in $numberFields) {
        $raw = $controls[$field.Name].Text.Trim()
        if (-not $raw) {
            continue
        }
        $parsed = 0
        if (-not [int]::TryParse($raw, [ref]$parsed)) {
            [System.Windows.Forms.MessageBox]::Show("$($field.Label) must be a whole number.", "CCLMS Tracker Setup")
            return
        }
        $payload[$field.Name] = $parsed
    }

    Write-Config -Path $ConfigPath -Payload $payload
    $form.Tag = "saved"
    $form.Close()
})

$cancelButton.Add_Click({
    $form.Tag = "cancelled"
    $form.Close()
})

$form.Controls.Add($saveButton)
$form.Controls.Add($cancelButton)
$form.AcceptButton = $saveButton
$form.CancelButton = $cancelButton

[void]$form.ShowDialog()

if ($form.Tag -ne "saved") {
    throw "Setup was cancelled."
}

Write-Host "Saved tracker config to $ConfigPath"
