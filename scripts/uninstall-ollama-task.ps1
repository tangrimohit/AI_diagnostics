# Unregister the Ollama-Server scheduled task.
# Run from an ELEVATED PowerShell prompt.

$ErrorActionPreference = "Stop"

$current = [Security.Principal.WindowsIdentity]::GetCurrent()
$wp = New-Object Security.Principal.WindowsPrincipal($current)
if (-not $wp.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "ERROR: This script must be run from an elevated PowerShell prompt." -ForegroundColor Red
    exit 1
}

$task = Get-ScheduledTask -TaskName "Ollama-Server" -ErrorAction SilentlyContinue
if (-not $task) {
    Write-Host "Ollama-Server task not found; nothing to remove." -ForegroundColor Yellow
    exit 0
}

try { Stop-ScheduledTask -TaskName "Ollama-Server" -ErrorAction SilentlyContinue } catch {}

Unregister-ScheduledTask -TaskName "Ollama-Server" -Confirm:$false
Write-Host "OK: 'Ollama-Server' scheduled task unregistered." -ForegroundColor Green
