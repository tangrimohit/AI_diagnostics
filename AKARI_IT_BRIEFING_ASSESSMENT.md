# AKARI IT Briefing Assessment

**Assessed:** 2026-10-08  
**Briefing reviewed:** `AKARI_IT_Briefing_v0.6.pptx`  
**Scope:** Source-code and repository-documentation review only. Deployment claims require separate operational evidence.

## Conclusion

The briefing accurately represents AKARI's core concept: a local diagnostic
assistant for Epson projectors, using FastAPI, local Ollama/Gemma inference,
a Markdown knowledge base, deterministic IPS Tool log parsing, structured
diagnoses, ranked repair steps, source citations, and escalation drafts.

Before using the briefing for IT or security approval, amend the claims noted
below, particularly model coverage, external-service wording, and the
description of stored diagnostic data.

| Area | Assessment | Repository evidence or gap |
|---|---|---|
| Local diagnostic assistant | Matches | The FastAPI application uses local Ollama/Gemma inference, the `wiki/` Markdown knowledge base, deterministic IPS TSV decoding, structured diagnosis output, photo input, Condition Diagnosis values, and escalation drafts. |
| Retrieval and grounding | Mostly matches | Retrieval is deterministic and based on extracted entities, error codes, keywords, and fixed page-selection rules. It is not vector search. The prompt instructs the model to use only the retrieved reference material. |
| Knowledge-base governance | Partially matches | Draft wiki pages are excluded from diagnosis retrieval; the admin workflow supports review, approval, history, linting, and source ingestion. However, the repository has no `SCHEMA.md`, although the briefing presents this as the governing template. |
| Model coverage | Does not match | The briefing states approximately 40 projector models. The reviewed sample wiki has pages for four models: EB-X49, EB-PU2216B, EB-L260F, and CO-FH02, plus two platform-family pages. |
| Local-only inference | Matches by default, with qualification | The default Ollama host is `localhost` and there is no external inference fallback. However, `OLLAMA_HOSTS` supports additional hosts, so a single-machine deployment is configuration rather than an application-enforced restriction. |
| External services | Conflicts | The briefing's no-external-AI claim is correct for inference. But feedback confirmations, reminders, and GPU alerts can use the external Resend email API when configured. Describe this as “no external AI inference service,” rather than “no external service.” |
| Privacy and audit records | Conflicts materially | The code stores salted user hashes, but the audit schema also has fields for full problem text, model input, IPS-log summary, and full diagnostic response. No request-side name, serial-number, or email redaction was found before those fields are stored. |
| Access control | Partially matches | The application expects an identity-aware reverse proxy to set an authenticated-email header. The application does not itself enforce authentication or administrator roles; `/admin` protection is documented as a reverse-proxy policy. Cloudflare Tunnel, OTP sign-in, a closed two-user group, and no-inbound exposure are deployment claims not evidenced in this repository. |
| Operations | Mostly matches | Windows startup-task scripts exist for Ollama and the API, with the API starting after a 60-second delay and both configured to restart after failure. GPU monitoring, SQLite backups, and health endpoints are implemented. Tunnel setup and a separate three-minute health-check/heartbeat scheduler are not included here. |
| Retention and deletion | Partially matches | Feedback records can be marked deleted, and database backups are retained on a rolling weekly schedule. No general retention policy or automatic expiry for diagnosis and audit records was found, matching the briefing's listed open item. |

## Recommended briefing changes

1. Replace “~40 projector models covered” with the verified production count,
   or label the figure as a target until the complete production knowledge base
   has been verified.
2. Replace absolute “nothing is sent to any external service” wording with a
   precise statement that no external AI inference service is used. Disclose
   the optional email provider separately.
3. Revise the data-minimisation and auditability sections to state exactly what
   diagnostic text, log summaries, and model responses are retained, where they
   are stored, who can access them, and for how long.
4. Describe tunnel, MFA, account restrictions, hosting, health monitoring, and
   network exposure as deployment controls, with separate operational evidence.
5. Add or correct the referenced `SCHEMA.md` if it is intended to be the
   knowledge-base governance source of truth.

## Evidence reviewed

- `README.md`
- `.env.example`
- `api/main.py`
- `api/inference.py`
- `api/db.py`
- `api/emailer.py`
- `api/opsec.py`
- `scripts/install-akari-api-task.ps1`
- `scripts/install-ollama-task.ps1`
- The checked-in `wiki/` sample knowledge base
