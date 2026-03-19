param(
    [string]$TrackerConfigPath = ".\config.json",
    [string]$ExtensionDefaultsPath = ".\browser_extension\local.defaults.js"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $TrackerConfigPath)) {
    throw "Tracker config not found: $TrackerConfigPath"
}

$cfg = Get-Content $TrackerConfigPath -Raw | ConvertFrom-Json

$token = ""
if ($cfg.api_key -and $cfg.api_secret) {
    $token = "$($cfg.api_key):$($cfg.api_secret)"
}

$content = @"
const CCLMS_LOCAL_DEFAULTS = {
  crmBaseUrl: "$($cfg.site_url)",
  authMode: "token",
  apiToken: "$token",
  deviceId: "$($cfg.device_id)",
  employee: "",
  mapsEnabled: true,
  chatEnabled: false,
  cacheTtlSeconds: 180
};
"@

Set-Content -Path $ExtensionDefaultsPath -Value $content -Encoding UTF8
Write-Output "Wrote browser extension defaults to $ExtensionDefaultsPath"
