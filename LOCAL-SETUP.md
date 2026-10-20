# AKARI on this computer

This document describes the existing local installation. The repository is in
`eme-service-main-diagnositicassitant-002-main` within the parent AKARI folder.

## Start

In the parent AKARI folder, double-click `Start-AKARI.cmd`, then open <http://127.0.0.1:8000>.
The launcher starts Ollama if necessary and runs AKARI in the terminal.
Keep that terminal open; press Ctrl+C to stop AKARI. If AKARI is already
running, use the existing server instead of starting a second copy.

## Installed tools

- uv 0.13.1
- Python 3.12.15, stored in `.python-runtime` in the parent AKARI folder
- Project dependencies installed from `uv.lock` into the source folder's `.venv`
- Ollama 0.40.6
- Git for Windows 2.55.0

The source folder's `.env` contains a generated, stable user hash salt.
Keep this file private and preserve the salt when backing up or moving the app.
Outbound email is disabled. NVIDIA GPU monitoring is disabled for this Intel laptop.
Models are configured to release memory after five idle minutes on future app starts.

## Hardware limitations

This computer has about 7.7 GB usable RAM and Intel integrated graphics.
The Ollama server selected CPU inference. Model loading and diagnoses may
be slow or fail from insufficient available memory. Installation does not
guarantee that the configured models fit in memory.

The fast model is `gemma3:4b`, and the UI defaults to Fast mode on this computer.
The larger `gemma4:e2b` model has not been
downloaded; thinking mode requires it or a separately configured Ollama host.
The included wiki contains sample knowledge for four projector models.

## Logs and data

- Installation and current background server logs: `../installation-logs`
- Databases: `data/`
- Database backups: `backup/`

The repository has been initialized, committed, and uploaded to
`https://github.com/tangrimohit/AI_diagnostics` on the `main` branch.
Configure a local Git author name and email before making further commits.
Local `.env`, virtual environment, databases, and backups are excluded by `.gitignore`.

## Scope

AKARI listens only on `127.0.0.1:8000`, and Ollama on `127.0.0.1:11434`.
No firewall rules, boot tasks, or shared access were configured. Use the local
launcher in the parent AKARI folder rather than the repository's original `C:\akari` startup scripts.
Authentication and admin authorization require an identity-aware reverse proxy
before configuring shared access.
