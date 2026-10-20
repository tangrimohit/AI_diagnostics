# Unregister the Akari-API scheduled task.
# Run from an ELEVATED PowerShell prompt.

$ErrorActionPreference = "Stop"

$current = [Security.Principal.WindowsIdentity]::GetCurrent()
$wp = New-Object Security.Principal.WindowsPrincipal($current)
if (-not $wp.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "ERROR: This script must be run from an elevated PowerShell prompt." -ForegroundColor Red
    exit 1
}

$task = Get-ScheduledTask -TaskName "Akari-API" -ErrorAction SilentlyContinue
if (-not $task) {
    Write-Host "Akari-API task not found; nothing to remove." -ForegroundColor Yellow
    exit 0
}

# Stop it first if running
try { Stop-ScheduledTask -TaskName "Akari-API" -ErrorAction SilentlyContinue } catch {}

Unregister-ScheduledTask -TaskName "Akari-API" -Confirm:$false
Write-Host "OK: 'Akari-API' scheduled task unregistered." -ForegroundColor Green
