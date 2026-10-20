@echo off
REM Auto-start wrapper for the AKARI FastAPI server.
REM Invoked by the Akari-API scheduled task (Task Scheduler, runs as SYSTEM,
REM AtStartup trigger with a 60s delay so Ollama has time to bind 11434).
REM
REM Logs land in data\akari-uvicorn.out.log and data\akari-uvicorn.err.log
REM so a fresh run can be inspected after reboot. The logs are append-only;
REM rotate manually if they grow large.

setlocal
set "PROJECT_ROOT=C:\akari"
set "VENV_PY=%PROJECT_ROOT%\.venv\Scripts\python.exe"
set "LOG_DIR=%PROJECT_ROOT%\data"

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

cd /d "%PROJECT_ROOT%"
echo [%DATE% %TIME%] starting uvicorn (run marker %RANDOM%; actual PID logged by uvicorn into akari-uvicorn.err.log) >> "%LOG_DIR%\akari-uvicorn.out.log"
"%VENV_PY%" -u -m uvicorn api.main:app --host 127.0.0.1 --port 8000 --app-dir "%PROJECT_ROOT%" 1>>"%LOG_DIR%\akari-uvicorn.out.log" 2>>"%LOG_DIR%\akari-uvicorn.err.log"
echo [%DATE% %TIME%] uvicorn exited (exit=%ERRORLEVEL%) >> "%LOG_DIR%\akari-uvicorn.err.log"
endlocal
