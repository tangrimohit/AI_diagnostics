# Register the Akari-API scheduled task.
# Run from an ELEVATED PowerShell prompt (Right-click PowerShell -> Run as Administrator).
#
# What this creates:
#   - Task name: Akari-API
#   - Runs:      scripts\start-akari-api.cmd  (which starts uvicorn)
#   - Identity:  NT AUTHORITY\SYSTEM (no user login required)
#   - Trigger:   At system startup, 60-second delay (lets Ollama bind 11434 first)
#   - Settings:  Restart up to 3 times if it crashes, no execution time limit
#
# To remove later, run scripts\uninstall-akari-api-task.ps1 from an elevated prompt.

$ErrorActionPreference = "Stop"

$current = [Security.Principal.WindowsIdentity]::GetCurrent()
$wp = New-Object Security.Principal.WindowsPrincipal($current)
if (-not $wp.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "ERROR: This script must be run from an elevated PowerShell prompt." -ForegroundColor Red
    Write-Host "Right-click PowerShell and choose 'Run as Administrator', then re-run this script." -ForegroundColor Red
    exit 1
}

$wrapperPath = "C:\akari\scripts\start-akari-api.cmd"
if (-not (Test-Path $wrapperPath)) {
    Write-Host "ERROR: wrapper script not found at $wrapperPath" -ForegroundColor Red
    exit 1
}

$action  = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$wrapperPath`""
$trigger = New-ScheduledTaskTrigger -AtStartup
$trigger.Delay = "PT60S"   # 60-second delay after boot so Ollama warms up first
$principal = New-ScheduledTaskPrincipal -UserId "NT AUTHORITY\SYSTEM" -RunLevel Highest -LogonType ServiceAccount
$settings  = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Seconds 0) `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1)

$task = New-ScheduledTask `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $settings `
    -Description "Start AKARI FastAPI uvicorn at boot. Runs as SYSTEM with 60s delay so Ollama can bind 11434. Wrapper: scripts\start-akari-api.cmd. Logs: data\akari-uvicorn.{out,err}.log"

Register-ScheduledTask -TaskName "Akari-API" -InputObject $task -Force | Out-Null

Write-Host "OK: 'Akari-API' scheduled task registered." -ForegroundColor Green
Write-Host ""
Write-Host "Task summary:" -ForegroundColor Cyan
Get-ScheduledTask -TaskName "Akari-API" | Format-List TaskName, State, Description
Write-Host "Triggers:" -ForegroundColor Cyan
(Get-ScheduledTask -TaskName "Akari-API").Triggers | Format-List
Write-Host "Principal:" -ForegroundColor Cyan
(Get-ScheduledTask -TaskName "Akari-API").Principal | Format-List
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Yellow
Write-Host "  1. To start it now without waiting for reboot:"
Write-Host "       Start-ScheduledTask -TaskName Akari-API"
Write-Host "  2. To verify it's working:"
Write-Host "       Invoke-RestMethod -Uri http://127.0.0.1:8000/health"
Write-Host "  3. Logs land in C:\akari\data\akari-uvicorn.{out,err}.log"
