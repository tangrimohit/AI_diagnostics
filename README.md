# AKARI

Local diagnostic assistant for Epson projectors. A FastAPI backend retrieves pages from a
Markdown knowledge base (`wiki/`), decodes IPS Tool logs deterministically, and asks a local
Gemma model (via Ollama) to write the diagnosis, ranked solutions and an escalation draft.

## Layout

- `api/` FastAPI app, inference routing, log parser, knowledge tables, SQLite stores
- `ui/` single-page web UI, admin panel, feedback form (PWA)
- `wiki/` Markdown knowledge base (sample set; production content lives on the runtime host)
- `ingest/` source extraction and wiki build helpers
- `scripts/` service install, smoke and verification scripts

## Run

```
uv sync
cp .env.example .env
uv run uvicorn api.main:app --host 127.0.0.1 --port 8000
```

Requires Ollama with `gemma3:4b` and `gemma4:e2b` pulled. SQLite databases are created under
`data/` on first start. Put the app behind an identity-aware reverse proxy that sets the
email header named in `auth_email_header`.
