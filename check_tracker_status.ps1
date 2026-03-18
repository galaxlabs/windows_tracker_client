param(
    [string]$ServiceName = "CCLMS-Tracker"
)

$ErrorActionPreference = "Stop"

$task = Get-ScheduledTask -TaskName $ServiceName -ErrorAction SilentlyContinue
if ($task) {
    $info = Get-ScheduledTaskInfo -TaskName $ServiceName
    Write-Host "Type: ScheduledTask"
    Write-Host "Name: $ServiceName"
    Write-Host "State: $($info.State)"
    Write-Host "LastRunTime: $($info.LastRunTime)"
    Write-Host "LastTaskResult: $($info.LastTaskResult)"
    exit 0
}

$service = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($service) {
    Write-Host "Type: WindowsService"
    Write-Host "Name: $ServiceName"
    Write-Host "Status: $($service.Status)"
    exit 0
}

Write-Host "Tracker service/task was not found: $ServiceName"
exit 1
