"""Unified source extractor for the ingest pipeline.

Routes a file to the right parser by suffix:
  .pdf            → pdfplumber
  .xlsx / .xlsm   → openpyxl (per-sheet rows)
  .docx           → python-docx
  .csv            → built-in csv
  .md / .txt      → plain text

Produces a single human-readable digest markdown and a structured JSON
sidecar in ingest/digests/<source_id>.{md,json}. Failed extraction returns
a structured error rather than raising, so the caller (which is a
BackgroundTask) can record extraction_failed and surface the reason
through the admin UI's Ingestion issues badge.
"""
from __future__ import annotations

import csv as _csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DIGEST_DIR = PROJECT_ROOT / "ingest" / "digests"


def _ensure_digest_dir() -> Path:
    DIGEST_DIR.mkdir(parents=True, exist_ok=True)
    return DIGEST_DIR


def _truncate(s: str, n: int = 500) -> str:
    s = (s or "").replace("\r\n", "\n").strip()
    if len(s) <= n:
        return s
    return s[:n].rstrip() + "..."


def extract_source(file_path: Path, source_id: str, source_meta: dict[str, Any]) -> dict[str, Any]:
    """Returns {'ok': bool, 'digest_path': str | None, 'error': str | None, 'preview': str}.

    Best-effort: never raises. On failure, returns ok=False with an error string
    that the caller writes to ingested_sources.status_detail.
    """
    suffix = file_path.suffix.lower()
    try:
        if suffix == ".pdf":
            data = _extract_pdf(file_path)
        elif suffix in (".xlsx", ".xlsm"):
            data = _extract_xlsx(file_path)
        elif suffix == ".docx":
            data = _extract_docx(file_path)
        elif suffix == ".csv":
            data = _extract_csv(file_path)
        elif suffix in (".md", ".txt"):
            data = _extract_text(file_path)
        else:
            return {"ok": False, "digest_path": None, "error": f"Unsupported file type: {suffix}", "preview": ""}
    except Exception as e:
        return {"ok": False, "digest_path": None, "error": f"{type(e).__name__}: {e}", "preview": ""}

    if not data.get("preview"):
        return {
            "ok": False,
            "digest_path": None,
            "error": "Extraction produced no readable text (scanned PDF, image-only file, or empty).",
            "preview": "",
        }

    digest_path = _write_digest(source_id, file_path, source_meta, data)
    return {"ok": True, "digest_path": str(digest_path), "error": None, "preview": data["preview"]}


# -------------------- per-format extractors --------------------

def _extract_pdf(path: Path) -> dict[str, Any]:
    import pdfplumber
    out_pages: list[dict[str, Any]] = []
    full_text_parts: list[str] = []
    with pdfplumber.open(path) as pdf:
        total = len(pdf.pages)
        # Cap at 60 pages for performance; flag in metadata when truncated
        cap = min(total, 60)
        for i in range(cap):
            try:
                t = pdf.pages[i].extract_text() or ""
            except Exception as e:
                t = f"[page {i+1} extraction error: {e}]"
            out_pages.append({"page": i + 1, "text_excerpt": _truncate(t, 600)})
            full_text_parts.append(f"\n\n=== Page {i + 1} ===\n\n{t}")
    full_text = "".join(full_text_parts).strip()
    return {
        "format": "pdf",
        "page_count": total,
        "extracted_page_count": cap,
        "truncated": cap < total,
        "pages": out_pages,
        "full_text": full_text,
        "preview": _truncate(full_text, 4000),
    }


def _extract_xlsx(path: Path) -> dict[str, Any]:
    from openpyxl import load_workbook
    wb = load_workbook(path, read_only=True, data_only=True)
    sheets_out: list[dict[str, Any]] = []
    full_lines: list[str] = []
    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        rows_iter = ws.iter_rows(values_only=True)
        rows = []
        sample_rows: list[list[Any]] = []
        for i, row in enumerate(rows_iter):
            if i >= 12:
                break
            rows.append([("" if c is None else str(c)) for c in row])
        sheets_out.append({
            "name": sheet_name,
            "dimensions": f"{ws.max_row} x {ws.max_column}",
            "sample_rows": rows,
        })
        full_lines.append(f"\n\n=== Sheet: {sheet_name} ({ws.max_row} rows x {ws.max_column} cols) ===")
        for r in rows:
            full_lines.append(" | ".join(r))
    wb.close()
    full_text = "\n".join(full_lines).strip()
    return {
        "format": "xlsx",
        "sheet_count": len(sheets_out),
        "sheets": sheets_out,
        "full_text": full_text,
        "preview": _truncate(full_text, 4000),
    }


def _extract_docx(path: Path) -> dict[str, Any]:
    from docx import Document
    doc = Document(path)
    paragraphs = [p.text for p in doc.paragraphs if p.text and p.text.strip()]
    full_text = "\n".join(paragraphs).strip()
    return {
        "format": "docx",
        "paragraph_count": len(paragraphs),
        "full_text": full_text,
        "preview": _truncate(full_text, 4000),
    }


def _extract_csv(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8", errors="replace", newline="") as f:
        reader = _csv.reader(f)
        rows = list(reader)
    sample = rows[:20]
    full_lines = []
    for r in sample:
        full_lines.append(" | ".join(r))
    full_text = "\n".join(full_lines)
    return {
        "format": "csv",
        "row_count": len(rows),
        "column_count": max((len(r) for r in rows), default=0),
        "sample_rows": sample,
        "full_text": full_text,
        "preview": _truncate(full_text, 4000),
    }


def _extract_text(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")
    return {
        "format": "text",
        "char_count": len(text),
        "full_text": text,
        "preview": _truncate(text, 4000),
    }


# -------------------- digest writer --------------------

def _write_digest(source_id: str, file_path: Path, source_meta: dict[str, Any], data: dict[str, Any]) -> Path:
    _ensure_digest_dir()
    md_path = DIGEST_DIR / f"{source_id}.md"
    json_path = DIGEST_DIR / f"{source_id}.json"

    md_lines = [
        f"# Ingest digest · {file_path.name}",
        "",
        f"- **Source ID**: `{source_id}`",
        f"- **Original name**: {file_path.name}",
        f"- **Source type**: {source_meta.get('source_type', '?')}",
        f"- **Authority**: {source_meta.get('authority', '?')}",
        f"- **Format**: {data.get('format')}",
        f"- **Uploaded**: {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
    ]
    if source_meta.get("notes"):
        md_lines += ["", f"**Notes**: {source_meta['notes']}"]
    md_lines += ["", "## Structural summary", ""]

    fmt = data.get("format")
    if fmt == "pdf":
        md_lines.append(f"- Pages: {data['page_count']} (extracted first {data['extracted_page_count']})")
        if data.get("truncated"):
            md_lines.append(f"- Note: truncated for performance; further pages not captured in this digest.")
        md_lines.append("")
        md_lines.append("### Per-page text excerpts")
        for p in data["pages"][:30]:
            md_lines.append(f"\n#### Page {p['page']}\n\n{p['text_excerpt']}")
    elif fmt == "xlsx":
        md_lines.append(f"- Sheet count: {data['sheet_count']}")
        for s in data["sheets"]:
            md_lines.append(f"\n### Sheet: {s['name']} ({s['dimensions']})")
            for r in s.get("sample_rows", []):
                md_lines.append("- " + " | ".join(r))
    elif fmt == "docx":
        md_lines.append(f"- Paragraph count: {data['paragraph_count']}")
        md_lines.append("")
        md_lines.append("### Body excerpt")
        md_lines.append("")
        md_lines.append(data["preview"])
    elif fmt == "csv":
        md_lines.append(f"- Row count: {data['row_count']}, columns: {data['column_count']}")
        md_lines.append("")
        md_lines.append("### Sample rows")
        for r in data["sample_rows"]:
            md_lines.append("- " + " | ".join(r))
    elif fmt == "text":
        md_lines.append(f"- Char count: {data['char_count']}")
        md_lines.append("")
        md_lines.append("### Body excerpt")
        md_lines.append("")
        md_lines.append(data["preview"])

    md_path.write_text("\n".join(md_lines), encoding="utf-8")

    # JSON sidecar: full structured data (may be large for PDFs, but useful)
    json_payload = {
        "source_id": source_id,
        "source_meta": source_meta,
        "data": {
            k: v for k, v in data.items()
            if k != "full_text"  # full_text duplicates pages/sheets content; keep digest lean
        },
    }
    json_path.write_text(json.dumps(json_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return md_path
