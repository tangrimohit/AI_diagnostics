$ErrorActionPreference = "Continue"
$logDir = "%USERPROFILE%\.akari\logs"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir -Force | Out-Null }
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"

Start-Process `
    -FilePath "C:\akari\.venv\Scripts\python.exe" `
    -ArgumentList "-m","uvicorn","api.main:app","--host","127.0.0.1","--port","8000","--app-dir","C:\akari" `
    -WindowStyle Hidden `
    -RedirectStandardOutput "$logDir\uvicorn-$stamp.log" `
    -RedirectStandardError "$logDir\uvicorn-$stamp.err" `
    -Wait
