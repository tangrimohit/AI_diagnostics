"""LLM drafter for ingestion.

Given a digest (the extractor's output) and the source metadata, asks the
configured LLM backend to propose a set of wiki pages matching the AKARI
schema documented in SCHEMA.md.

Backend selection via env var INGEST_DRAFT_BACKEND:
  local       → ollama gemma3:4b with format=json (default)

The drafter is responsible only for proposing page content. It does NOT
touch wiki/_drafts/ itself — that's the orchestrator's job (see main.py
background task chain).
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


PROJECT_ROOT = Path(__file__).resolve().parent.parent
MAX_DIGEST_CHARS = 12000   # cap the digest we send to the model to keep context window usable
ALLOWED_PAGE_TYPES = {"entity", "concept", "procedure", "error_code", "output"}


def select_backend() -> str:
    return (os.environ.get("INGEST_DRAFT_BACKEND") or "local").strip().lower()


# -------------------- prompt --------------------

SCHEMA_REMINDER = """\
AKARI wiki page templates (frontmatter + canonical sections):

- entity page (a model, part, environment):
    frontmatter: type: entity, entity_type: model|part|environment, last_updated, source_count
    sections: Summary / Key facts / Known issues / Related pages / Sources / Changelog

- concept page (a reference idea / term explanation):
    frontmatter: type: concept, last_updated, source_count
    sections: # Title / what it is / why it matters / how it applies / Related pages / Sources / Changelog

- procedure page (step-by-step workflow):
    frontmatter: type: procedure, applies_to: [list], estimated_time_minutes, difficulty, last_updated
    sections: When to use / Prerequisites / Steps (numbered) / Expected outcome / If it fails / Related pages / Sources / Changelog

- error_code page (one per IPS code):
    frontmatter: type: error_code, code, category, severity, last_updated, source_count
    sections: # Code — Name / What it means / Common causes / Standard resolution sequence / Affected models / Related pages / Sources / Changelog

File path conventions:
- wiki/projectors/<model-slug>/index.md, known-failures.md, parts-reference.md, etc.
- wiki/projectors/<model-slug>/issues/<topic>.md   (failure-mode pages)
- wiki/error-codes/<code-slug>.md
- wiki/procedures/<verb-noun>.md
- wiki/concepts/<noun-slug>.md
"""


def build_draft_prompt(digest_md: str, source_meta: dict[str, Any]) -> str:
    digest = digest_md[:MAX_DIGEST_CHARS]
    if len(digest_md) > MAX_DIGEST_CHARS:
        digest += "\n\n[Digest truncated for prompt size]"

    return f"""\
You are an AKARI wiki ingestion drafter. Given the digest of a single service document below, propose 1-8 NEW wiki pages that AKARI should add to its knowledge base.

Constraints:
- Only propose pages that the digest actually supports. If the digest is thin or off-topic, propose 0 pages.
- Do NOT invent facts the digest does not contain.
- Each page must use the appropriate template from the schema below.
- Body markdown should note the source TYPE at the bottom (e.g. "Source: service manual" or "Source: field repair data"). Do NOT write raw filenames, case numbers, or ticket IDs.
- Do not use em-dashes (—). Use parens, commas, or split the sentence.
- Do not mention AI model names, framework names, ports, or internal tools in the body.
- Opsec: technical content only. NEVER include case/escalation/ticket/report IDs (TESC, SR, END, ENC, MSD numbers), customer or partner names, country or region names, incident dates, or internal project/platform codenames. State only the technical symptom, cause, and solution. Projector product model numbers (e.g. EB-X49) are allowed.
- If the digest covers an existing model like EB-X49, prefer pages under wiki/projectors/eb-x49/ rather than top-level concept pages.

{SCHEMA_REMINDER}

Source metadata:
- Source type: {source_meta.get('source_type', '?')}
- Authority level: {source_meta.get('authority', '?')}
- Notes from uploader: {source_meta.get('notes', '(none)')}
- Original filename: {source_meta.get('original_name', '?')}

Digest:
---
{digest}
---

Output a single JSON object with this exact shape. No text outside the JSON.

{{
  "proposed_pages": [
    {{
      "path":         "wiki/concepts/example-name.md",
      "frontmatter":  {{"type": "concept", "last_updated": "{datetime.now(timezone.utc).date().isoformat()}", "source_count": 1}},
      "body":         "# Title\\n\\n## Section\\n\\nMarkdown body here.\\n\\n## Sources\\n\\n`<original filename>`\\n\\n## Changelog\\n- {datetime.now(timezone.utc).date().isoformat()} v0.1.0 — Drafted from ingestion."
    }}
  ],
  "reasoning": "One sentence on why these specific pages."
}}
"""


# -------------------- backend implementations --------------------

def draft_pages_from_digest(digest_md: str, source_meta: dict[str, Any]) -> dict[str, Any]:
    """Returns {'ok': bool, 'pages': list, 'reasoning': str, 'error': str | None}.

    Best-effort: never raises. On failure, returns ok=False with an error string.
    """
    backend = select_backend()
    if backend == "local":
        return _draft_via_local(digest_md, source_meta)
    return {"ok": False, "pages": [], "reasoning": "", "error": f"Unknown INGEST_DRAFT_BACKEND: {backend}"}


def _draft_via_local(digest_md: str, source_meta: dict[str, Any]) -> dict[str, Any]:
    """Use ollama gemma3:4b with format=json. Sync wrapper around the sync ollama client
    so we can run inside a thread from FastAPI BackgroundTasks."""
    try:
        from ollama import Client  # sync client; we're already in a worker thread
    except Exception as e:
        return {"ok": False, "pages": [], "reasoning": "", "error": f"ollama client import failed: {e}"}

    host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
    model = os.environ.get("MODEL_FAST", "gemma3:4b")
    prompt = build_draft_prompt(digest_md, source_meta)

    try:
        client = Client(host=host, timeout=600)
        result = client.generate(
            model=model,
            prompt=prompt,
            format="json",
            options={"temperature": 0.2, "num_ctx": 16384},
        )
        raw = result.get("response") if isinstance(result, dict) else result.response
    except Exception as e:
        return {"ok": False, "pages": [], "reasoning": "", "error": f"LLM call failed: {e}"}

    return _parse_and_validate(raw, source_meta)



# -------------------- parsing & validation --------------------

def _parse_and_validate(raw: str, source_meta: dict[str, Any]) -> dict[str, Any]:
    raw = (raw or "").strip()
    if not raw:
        return {"ok": False, "pages": [], "reasoning": "", "error": "LLM returned empty output"}
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError as e:
        return {"ok": False, "pages": [], "reasoning": "", "error": f"LLM output is not valid JSON: {e}"}

    proposed = obj.get("proposed_pages")
    reasoning = obj.get("reasoning", "")
    if not isinstance(proposed, list):
        return {"ok": False, "pages": [], "reasoning": reasoning, "error": "Missing 'proposed_pages' list in LLM output"}

    cleaned: list[dict[str, Any]] = []
    rejections: list[str] = []
    for i, page in enumerate(proposed):
        if not isinstance(page, dict):
            rejections.append(f"page #{i}: not a dict")
            continue
        path = (page.get("path") or "").strip()
        fm = page.get("frontmatter")
        body = page.get("body") or ""
        # Basic checks
        if not path.startswith("wiki/") or not path.endswith(".md") or ".." in path.split("/"):
            rejections.append(f"page #{i}: invalid path {path!r}")
            continue
        if not isinstance(fm, dict):
            rejections.append(f"page #{i}: frontmatter must be an object")
            continue
        fm_type = (fm.get("type") or "").strip()
        if fm_type not in ALLOWED_PAGE_TYPES:
            rejections.append(f"page #{i}: invalid frontmatter type {fm_type!r}")
            continue
        if not body.strip():
            rejections.append(f"page #{i}: empty body")
            continue
        cleaned.append({"path": path, "frontmatter": fm, "body": body})

    if not cleaned:
        return {
            "ok": False,
            "pages": [],
            "reasoning": reasoning,
            "error": "All proposed pages rejected. " + ("; ".join(rejections) if rejections else "Empty proposal."),
        }
    return {"ok": True, "pages": cleaned, "reasoning": reasoning, "error": None, "rejections": rejections}


# -------------------- writing drafts to disk --------------------

def write_drafts_to_disk(source_id: str, pages: list[dict[str, Any]]) -> Path:
    """Write proposed pages under wiki/_drafts/<source_id>/.

    The path the LLM proposed becomes the basename for now — admin will rename
    in the Approve dialog. We do not honour the proposed wiki/<...>.md path
    blindly because we never write drafts directly into the live tree.
    """
    draft_dir = PROJECT_ROOT / "wiki" / "_drafts" / source_id
    draft_dir.mkdir(parents=True, exist_ok=True)
    # Clean any prior drafts for this source_id (idempotent re-runs)
    for old in draft_dir.glob("*.md"):
        old.unlink()
    # Write a manifest so the admin sees what the LLM proposed paths were
    manifest: list[dict[str, Any]] = []
    for i, page in enumerate(pages):
        proposed_path = page["path"]
        # local filename within the draft dir
        safe_name = re.sub(r"[^A-Za-z0-9._-]", "-", proposed_path.rsplit("/", 1)[-1]) or f"page-{i + 1}.md"
        local_path = draft_dir / safe_name
        # If collision (LLM gave dup filename), suffix it
        if local_path.exists():
            local_path = draft_dir / f"{i + 1:02d}-{safe_name}"
        # Compose the markdown file with frontmatter
        fm_block = _render_frontmatter(page["frontmatter"])
        local_path.write_text(fm_block + page["body"], encoding="utf-8")
        manifest.append({
            "draft_path": "wiki/_drafts/" + source_id + "/" + local_path.name,
            "proposed_destination": proposed_path,
        })
    (draft_dir / "_manifest.json").write_text(
        json.dumps({"source_id": source_id, "pages": manifest}, indent=2),
        encoding="utf-8",
    )
    return draft_dir


def _render_frontmatter(fm: dict[str, Any]) -> str:
    lines = ["---"]
    for k, v in fm.items():
        if isinstance(v, list):
            lines.append(f"{k}: [{', '.join(str(x) for x in v)}]")
        elif v is None:
            lines.append(f"{k}:")
        else:
            lines.append(f"{k}: {v}")
    lines.append("---")
    lines.append("")
    return "\n".join(lines)


def read_draft_manifest(source_id: str) -> Optional[list[dict[str, Any]]]:
    draft_dir = PROJECT_ROOT / "wiki" / "_drafts" / source_id
    manifest_path = draft_dir / "_manifest.json"
    if not manifest_path.exists():
        return None
    try:
        obj = json.loads(manifest_path.read_text(encoding="utf-8"))
        return obj.get("pages")
    except Exception:
        return None
