@echo off
REM Auto-start wrapper for the Ollama API server.
REM Invoked by the Ollama-Server scheduled task (Task Scheduler, runs as
REM SYSTEM, AtStartup trigger, no delay - Ollama is the first piece in the
REM chain and Akari-API's 60s delay accounts for warm-up time).
REM
REM Runs ollama.exe serve directly (not "ollama app.exe", the GUI tray)
REM so no user session is required. Models are read from the user-profile
REM store via the explicit OLLAMA_MODELS path; SYSTEM's $env:USERPROFILE
REM resolves to C:\Windows\System32\config\systemprofile which has no
REM .ollama dir, so the env var is required.
REM
REM Logs: data\ollama.out.log + data\ollama.err.log (append-only; rotate
REM manually if they grow large).

setlocal
set "OLLAMA_BIN=%USERPROFILE%\AppData\Local\Programs\Ollama\ollama.exe"
set "OLLAMA_MODELS=%USERPROFILE%\.ollama\models"
REM Bound to the loopback interface only. Nothing outside this machine talks to
REM the model server: the AKARI API is the only client and it runs here too.
set "OLLAMA_HOST=127.0.0.1:11434"

REM --- Performance tuning (4GB RTX 3050, 32GB RAM) ---
REM Keep models resident forever so we never pay the ~35s reload tax between
REM queries. This is the main cause of the 30-45s vs 100+s latency swing:
REM a query that hits an unloaded model reloads gemma4:e2b (7.9GB) from scratch.
set "OLLAMA_KEEP_ALIVE=-1"
REM Allow both tiers (gemma3:4b fast + gemma4:e2b thinking) to stay warm at
REM once instead of evicting one to load the other.
set "OLLAMA_MAX_LOADED_MODELS=2"
REM One request slot: on a 4GB card, parallel slots multiply the KV cache and
REM push more model layers onto the CPU. Single slot keeps VRAM for layers.
set "OLLAMA_NUM_PARALLEL=1"
REM Flash attention shrinks the KV cache, freeing VRAM so more of the model
REM fits on the GPU (helps gemma4:e2b's 27% GPU share) and speeds attention.
set "OLLAMA_FLASH_ATTENTION=1"

set "LOG_DIR=C:\akari\data"

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

echo [%DATE% %TIME%] starting ollama serve (run marker %RANDOM%) >> "%LOG_DIR%\ollama.out.log"
"%OLLAMA_BIN%" serve 1>>"%LOG_DIR%\ollama.out.log" 2>>"%LOG_DIR%\ollama.err.log"
echo [%DATE% %TIME%] ollama serve exited (exit=%ERRORLEVEL%) >> "%LOG_DIR%\ollama.err.log"
endlocal
