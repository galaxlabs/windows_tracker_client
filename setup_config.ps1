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

$existing = @{}
if (Test-Path $ConfigPath) {
    try {
        $raw = Get-Content $ConfigPath -Raw | ConvertFrom-Json
        foreach ($property in $raw.PSObject.Properties) {
            $existing[$property.Name] = $property.Value
        }
    } catch {
        $existing = @{}
    }
}

$form = New-Object System.Windows.Forms.Form
$form.Text = "CCLMS Tracker Setup"
$form.Size = New-Object System.Drawing.Size -ArgumentList 520, 360
$form.StartPosition = "CenterScreen"
$form.FormBorderStyle = "FixedDialog"
$form.MaximizeBox = $false
$form.MinimizeBox = $false

$labels = @(
    @{ Text = "CRM Base URL"; Name = "site_url"; Y = 20; Help = "Leave blank to use embedded default." },
    @{ Text = "API Key"; Name = "api_key"; Y = 80; Help = "Leave blank to use embedded default." },
    @{ Text = "API Secret"; Name = "api_secret"; Y = 140; Help = "Leave blank to use embedded default." },
    @{ Text = "Device ID"; Name = "device_id"; Y = 200; Help = "Recommended: laptop hostname." }
)

$textBoxes = @{}

foreach ($item in $labels) {
    $label = New-Object System.Windows.Forms.Label
    $label.Text = $item.Text
    $label.Location = New-Object System.Drawing.Point -ArgumentList 20, $item.Y
    $label.Size = New-Object System.Drawing.Size -ArgumentList 180, 20
    $form.Controls.Add($label)

    $textbox = New-Object System.Windows.Forms.TextBox
    $textbox.Name = $item.Name
    $textbox.Location = New-Object System.Drawing.Point -ArgumentList 20, ($item.Y + 22)
    $textbox.Size = New-Object System.Drawing.Size -ArgumentList 460, 24
    if ($item.Name -eq "api_secret") {
        $textbox.UseSystemPasswordChar = $true
    }
    if ($existing.ContainsKey($item.Name)) {
        $textbox.Text = [string]$existing[$item.Name]
    } elseif ($item.Name -eq "device_id") {
        $textbox.Text = $env:COMPUTERNAME
    }
    $form.Controls.Add($textbox)
    $textBoxes[$item.Name] = $textbox

    $help = New-Object System.Windows.Forms.Label
    $help.Text = $item.Help
    $help.ForeColor = [System.Drawing.Color]::DimGray
    $help.Location = New-Object System.Drawing.Point -ArgumentList 20, ($item.Y + 46)
    $help.Size = New-Object System.Drawing.Size -ArgumentList 460, 18
    $form.Controls.Add($help)
}

$saveButton = New-Object System.Windows.Forms.Button
$saveButton.Text = "Save"
$saveButton.Location = New-Object System.Drawing.Point -ArgumentList 300, 270
$saveButton.Size = New-Object System.Drawing.Size -ArgumentList 80, 30

$cancelButton = New-Object System.Windows.Forms.Button
$cancelButton.Text = "Cancel"
$cancelButton.Location = New-Object System.Drawing.Point -ArgumentList 400, 270
$cancelButton.Size = New-Object System.Drawing.Size -ArgumentList 80, 30

$saveButton.Add_Click({
    $deviceId = $textBoxes["device_id"].Text.Trim()
    if (-not $deviceId) {
        [System.Windows.Forms.MessageBox]::Show("Device ID is required.", "CCLMS Tracker Setup")
        return
    }

    $payload = @{}
    foreach ($name in @("site_url", "api_key", "api_secret", "device_id")) {
        $value = $textBoxes[$name].Text.Trim()
        if ($value) {
            $payload[$name] = $value
        }
    }

    $json = $payload | ConvertTo-Json -Depth 4
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($ConfigPath, $json, $utf8NoBom)
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
