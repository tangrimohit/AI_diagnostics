# Register the Ollama-Server scheduled task.
# Run from an ELEVATED PowerShell prompt (Right-click PowerShell -> Run as Administrator).
#
# What this creates:
#   - Task name: Ollama-Server
#   - Runs:      scripts\start-ollama.cmd  (which starts ollama.exe serve)
#   - Identity:  NT AUTHORITY\SYSTEM (no user login required)
#   - Trigger:   At system startup, no delay (Ollama is first in the chain;
#                Akari-API's own 60s delay covers warm-up)
#   - Settings:  Restart up to 3 times if it crashes, no execution time limit
#
# After installing, you may want to disable the per-user logon shortcut at
# %APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\Ollama.lnk so it
# doesn't double-start Ollama on attended logon. (Optional; the second
# instance just fails to bind 11434 and exits.)
#
# To remove later, run scripts\uninstall-ollama-task.ps1 from an elevated prompt.

$ErrorActionPreference = "Stop"

$current = [Security.Principal.WindowsIdentity]::GetCurrent()
$wp = New-Object Security.Principal.WindowsPrincipal($current)
if (-not $wp.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "ERROR: This script must be run from an elevated PowerShell prompt." -ForegroundColor Red
    Write-Host "Right-click PowerShell and choose 'Run as Administrator', then re-run this script." -ForegroundColor Red
    exit 1
}

$wrapperPath = "C:\akari\scripts\start-ollama.cmd"
if (-not (Test-Path $wrapperPath)) {
    Write-Host "ERROR: wrapper script not found at $wrapperPath" -ForegroundColor Red
    exit 1
}

# Pre-flight: confirm the ollama.exe path the wrapper expects actually exists.
$ollamaBin = "%USERPROFILE%\AppData\Local\Programs\Ollama\ollama.exe"
if (-not (Test-Path $ollamaBin)) {
    Write-Host "ERROR: ollama.exe not found at $ollamaBin" -ForegroundColor Red
    Write-Host "Edit scripts\start-ollama.cmd to point OLLAMA_BIN at the actual install path." -ForegroundColor Red
    exit 1
}

$action  = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$wrapperPath`""
$trigger = New-ScheduledTaskTrigger -AtStartup   # no delay; first in chain
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
    -Description "Start Ollama API server at boot. Runs as SYSTEM, no user session needed. Wrapper: scripts\start-ollama.cmd. Logs: data\ollama.{out,err}.log. Uses OLLAMA_MODELS=%USERPROFILE%\.ollama\models so SYSTEM finds the user-profile model store."

Register-ScheduledTask -TaskName "Ollama-Server" -InputObject $task -Force | Out-Null

Write-Host "OK: 'Ollama-Server' scheduled task registered." -ForegroundColor Green
Write-Host ""
Write-Host "Task summary:" -ForegroundColor Cyan
Get-ScheduledTask -TaskName "Ollama-Server" | Format-List TaskName, State, Description
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Yellow
Write-Host "  1. To start it now without waiting for reboot (stop any currently-running ollama first):"
Write-Host "       Get-Process | Where-Object { `$_.Name -like '*ollama*' } | Stop-Process -Force"
Write-Host "       Start-Sleep -Seconds 2"
Write-Host "       Start-ScheduledTask -TaskName Ollama-Server"
Write-Host "  2. To verify it's working:"
Write-Host "       Invoke-RestMethod -Uri http://127.0.0.1:11434/api/tags"
Write-Host "  3. Logs land in C:\akari\data\ollama.{out,err}.log"
Write-Host ""
Write-Host "Optional: disable the per-user logon shortcut so Ollama only starts via this task:" -ForegroundColor Yellow
Write-Host "  Rename-Item '%USERPROFILE%\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup\Ollama.lnk' 'Ollama.lnk.disabled'"
