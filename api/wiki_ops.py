"""Wiki content operations: tree, read/write/delete with git versioning,
search, citations, lint, gap analysis. Admin-only consumer.
"""
from __future__ import annotations

import difflib
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from api import db


PROJECT_ROOT = Path(__file__).resolve().parent.parent
WIKI_ROOT = PROJECT_ROOT / "wiki"

FRONTMATTER_RE = re.compile(r"^---\r?\n(.*?)\r?\n---\r?\n(.*)$", re.DOTALL)
WIKI_LINK_RE = re.compile(r"\[\[wiki/([^\]\s]+?)\]\]")
HEADING_RE = re.compile(r"^(#{1,4})\s+(.+)$", re.MULTILINE)


# -------------------- frontmatter --------------------

def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Light-weight YAML-frontmatter parser. Returns (fm, body).

    Handles scalar values, simple inline lists `[a, b, c]`, and ignores anything
    fancier (multi-line lists, nested dicts). Enough for AKARI's frontmatter
    conventions documented in SCHEMA.md.
    """
    m = FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    fm_text, body = m.group(1), m.group(2)
    fm: dict[str, Any] = {}
    for line in fm_text.splitlines():
        if ":" not in line or line.lstrip().startswith("#"):
            continue
        key, _, val = line.partition(":")
        key = key.strip()
        val = val.strip()
        if not key:
            continue
        if val.startswith("[") and val.endswith("]"):
            inner = val[1:-1].strip()
            fm[key] = [v.strip().strip("\"'") for v in inner.split(",") if v.strip()] if inner else []
        elif val:
            fm[key] = val.strip("\"'")
        else:
            fm[key] = None
    return fm, body


def _safe_resolve(wiki_relpath: str) -> Path:
    """Resolve a wiki-relative path, refusing anything that would escape wiki/."""
    if not wiki_relpath.startswith("wiki/"):
        raise ValueError(f"path must start with 'wiki/': {wiki_relpath}")
    if ".." in wiki_relpath.split("/"):
        raise ValueError(f"path traversal blocked: {wiki_relpath}")
    p = (PROJECT_ROOT / wiki_relpath).resolve()
    if not str(p).startswith(str(WIKI_ROOT)):
        raise ValueError(f"path escapes wiki directory: {wiki_relpath}")
    return p


# -------------------- tree walk --------------------

def list_wiki_tree() -> dict[str, Any]:
    if not WIKI_ROOT.exists():
        return {"type": "dir", "name": "wiki", "path": "wiki", "children": []}

    def walk(p: Path) -> Optional[dict[str, Any]]:
        if p.name.startswith("."):
            return None
        # _drafts/ is hidden from the regular tree; surfaced separately via
        # /admin/ingest/sources so the admin can approve/reject through that flow.
        if p.name == "_drafts" and p.is_dir():
            return None
        rel = "wiki/" + p.relative_to(WIKI_ROOT).as_posix() if p != WIKI_ROOT else "wiki"
        if p.is_file():
            if p.suffix != ".md":
                return None
            try:
                fm, _ = parse_frontmatter(p.read_text(encoding="utf-8", errors="replace"))
            except Exception:
                fm = {}
            return {
                "type": "file",
                "name": p.name,
                "path": rel,
                "fm_type": fm.get("type"),
                "last_updated": fm.get("last_updated"),
                "size": p.stat().st_size,
            }
        if p.is_dir():
            children = [walk(c) for c in sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name.lower()))]
            children = [c for c in children if c is not None]
            file_count = sum(1 for c in children if c["type"] == "file") + sum(c.get("file_count", 0) for c in children if c["type"] == "dir")
            return {"type": "dir", "name": p.name if p != WIKI_ROOT else "wiki", "path": rel, "children": children, "file_count": file_count}
        return None

    return walk(WIKI_ROOT) or {"type": "dir", "name": "wiki", "path": "wiki", "children": [], "file_count": 0}


# -------------------- read / write / delete --------------------

def get_page(wiki_relpath: str) -> Optional[dict[str, Any]]:
    path = _safe_resolve(wiki_relpath)
    if not path.exists():
        return None
    raw = path.read_text(encoding="utf-8", errors="replace")
    fm, body = parse_frontmatter(raw)
    return {"path": wiki_relpath, "frontmatter": fm, "body": body, "raw": raw}


def save_page(wiki_relpath: str, new_content: str, hashed_user: Optional[str] = None) -> dict[str, Any]:
    path = _safe_resolve(wiki_relpath)
    is_new = not path.exists()
    old_content = "" if is_new else path.read_text(encoding="utf-8", errors="replace")
    if not is_new and old_content == new_content:
        return {"changed": False, "is_new": False}

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(new_content, encoding="utf-8")

    short = (hashed_user or "admin")[:10]
    message = f"wiki: {'create' if is_new else 'edit'} {wiki_relpath} by {short}"
    commit = _git_commit(wiki_relpath, message)

    diff_summary = compute_diff_summary(old_content, new_content)

    db.write_page_history(
        path=wiki_relpath,
        git_commit_id=commit or "unknown",
        hashed_user=hashed_user,
        change_type="created" if is_new else "edited",
        origin="manual_edit",
        source_id=None,
        diff_summary=diff_summary,
    )

    return {"changed": True, "is_new": is_new, "commit": commit, "diff_summary": diff_summary}


def delete_page(wiki_relpath: str, hashed_user: Optional[str] = None) -> dict[str, Any]:
    path = _safe_resolve(wiki_relpath)
    if not path.exists():
        return {"deleted": False, "reason": "not_found"}
    path.unlink()

    short = (hashed_user or "admin")[:10]
    message = f"wiki: delete {wiki_relpath} by {short}"
    commit = _git_commit(wiki_relpath, message)

    db.write_page_history(
        path=wiki_relpath,
        git_commit_id=commit or "unknown",
        hashed_user=hashed_user,
        change_type="deleted",
        origin="manual_edit",
        source_id=None,
        diff_summary="page deleted",
    )
    return {"deleted": True, "commit": commit}


def _git_commit(rel_path: str, message: str) -> Optional[str]:
    """git add + git commit + return new HEAD. Returns None on failure (commit is best-effort)."""
    try:
        subprocess.run(
            ["git", "-C", str(PROJECT_ROOT), "add", "--", rel_path],
            capture_output=True, timeout=10,
        )
        result = subprocess.run(
            ["git", "-C", str(PROJECT_ROOT), "commit", "-m", message],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            head = subprocess.run(
                ["git", "-C", str(PROJECT_ROOT), "rev-parse", "HEAD"],
                capture_output=True, text=True, timeout=5,
            ).stdout.strip()
            return head or None
    except Exception as e:
        print(f"[wiki_ops] git commit failed: {e}", file=sys.stderr)
    return None


# -------------------- diff summary --------------------

def compute_diff_summary(old: str, new: str) -> str:
    old_lines = old.splitlines() if old else []
    new_lines = new.splitlines() if new else []
    diff = list(difflib.unified_diff(old_lines, new_lines, n=3, lineterm=""))
    added = sum(1 for l in diff if l.startswith("+") and not l.startswith("+++"))
    removed = sum(1 for l in diff if l.startswith("-") and not l.startswith("---"))

    parts: list[str] = []
    if added:
        parts.append(f"added {added} line" + ("s" if added != 1 else ""))
    if removed:
        parts.append(f"removed {removed} line" + ("s" if removed != 1 else ""))

    section: Optional[str] = None
    for line in diff:
        if line.startswith("@@"):
            m = re.match(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@", line)
            if not m:
                continue
            change_start = int(m.group(1))
            for i in range(min(change_start - 1, len(new_lines) - 1), -1, -1):
                h = HEADING_RE.match(new_lines[i] if i < len(new_lines) else "")
                if h:
                    section = h.group(2).strip()
                    break
            break

    if section:
        return ", ".join(parts) + f" in section '{section}'"
    return ", ".join(parts) if parts else "no content change"


# -------------------- search --------------------

def search_wiki(query: str, mode: str = "literal", max_per_page: int = 3) -> list[dict[str, Any]]:
    if not query.strip():
        return []
    if mode == "regex":
        try:
            pat = re.compile(query, re.IGNORECASE)
        except re.error:
            return []
    else:
        pat = re.compile(re.escape(query), re.IGNORECASE)

    results: list[dict[str, Any]] = []
    for path in WIKI_ROOT.rglob("*.md"):
        rel = "wiki/" + path.relative_to(WIKI_ROOT).as_posix()
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        filename_match = bool(pat.search(path.name))
        body_matches = []
        for m in list(pat.finditer(content))[:max_per_page]:
            start = max(0, m.start() - 40)
            end = min(len(content), m.end() + 60)
            snippet = content[start:end].replace("\n", " ").replace("\r", " ")
            body_matches.append({"snippet": snippet, "offset": m.start()})
        if filename_match or body_matches:
            results.append({
                "path": rel,
                "filename_match": filename_match,
                "body_matches": body_matches,
                "match_count": (1 if filename_match else 0) + len(body_matches),
            })
    results.sort(key=lambda r: (-r["match_count"], r["path"]))
    return results


# -------------------- history --------------------

def get_history(wiki_relpath: str) -> list[dict[str, Any]]:
    with db._connect() as c:
        rows = c.execute(
            "SELECT * FROM wiki_page_history WHERE path = ? ORDER BY ts DESC",
            (wiki_relpath,),
        ).fetchall()
    return [
        {k: r[k] for k in r.keys()} | {"git_commit_short": (r["git_commit_id"] or "")[:8]}
        for r in rows
    ]


def get_page_at_commit(wiki_relpath: str, commit: str) -> Optional[dict[str, Any]]:
    # Reject anything non-hex-ish to keep this off the shell-injection surface.
    if not re.match(r"^[a-fA-F0-9]{4,64}$", commit):
        return None
    try:
        result = subprocess.run(
            ["git", "-C", str(PROJECT_ROOT), "show", f"{commit}:{wiki_relpath}"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return None
        raw = result.stdout
        fm, body = parse_frontmatter(raw)
        return {"path": wiki_relpath, "commit": commit, "frontmatter": fm, "body": body, "raw": raw}
    except Exception as e:
        print(f"[wiki_ops] git show failed: {e}", file=sys.stderr)
        return None


# -------------------- citations (cited-by) --------------------

def get_citations(wiki_relpath: str, limit: int = 50) -> list[dict[str, Any]]:
    """Find diagnose_events that cite this wiki page.

    Uses SQLite json_each to scan diagnose_events.wiki_pages_used (a JSON
    array) and pick rows where any element's .path field equals the target.
    O(n) over diagnose_events today; for >10k events, consider a generated
    column + expression index. Out of scope for v0.1.
    """
    with db._connect() as c:
        rows = c.execute(
            """
            SELECT DISTINCT e.diagnosis_id, e.ts, e.depth_tier, e.confidence_bucket,
                   e.coverage, e.success, e.hashed_user
            FROM diagnose_events e, json_each(e.wiki_pages_used) je
            WHERE json_extract(je.value, '$.path') = ?
            ORDER BY e.ts DESC
            LIMIT ?
            """,
            (wiki_relpath, limit),
        ).fetchall()
    if not rows:
        return []
    diag_ids = [r["diagnosis_id"] for r in rows]
    fb_map: dict[str, dict[str, Any]] = {}
    placeholders = ",".join("?" * len(diag_ids))
    with db._connect_feedback() as fc:
        for r in fc.execute(
            f"SELECT diagnosis_id, worked, deleted FROM diagnoses_with_feedback WHERE diagnosis_id IN ({placeholders})",
            diag_ids,
        ):
            fb_map[r["diagnosis_id"]] = {"worked": r["worked"], "deleted": r["deleted"]}

    def feedback_status(diag_id: str) -> str:
        rec = fb_map.get(diag_id)
        if not rec:
            return "pending"
        if rec["deleted"]:
            return "deleted"
        return "worked" if rec["worked"] else "didnt_work"

    return [
        {
            "diagnosis_id": r["diagnosis_id"],
            "ts": r["ts"],
            "depth_tier": r["depth_tier"],
            "confidence_bucket": r["confidence_bucket"],
            "coverage": r["coverage"],
            "success": bool(r["success"]),
            "hashed_user_short": (r["hashed_user"] or "")[:10] if r["hashed_user"] else None,
            "feedback_status": feedback_status(r["diagnosis_id"]),
        }
        for r in rows
    ]


# -------------------- lint --------------------

def lint_wiki() -> dict[str, Any]:
    pages: dict[str, dict[str, Any]] = {}
    for path in WIKI_ROOT.rglob("*.md"):
        rel = "wiki/" + path.relative_to(WIKI_ROOT).as_posix()
        try:
            raw = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        fm, body = parse_frontmatter(raw)
        pages[rel] = {"path": rel, "fm": fm, "body": body, "size": path.stat().st_size}

    # Build incoming link map
    links_in: dict[str, set[str]] = {}
    for src, p in pages.items():
        for m in WIKI_LINK_RE.finditer(p["body"]):
            tgt = "wiki/" + m.group(1)
            if not tgt.endswith(".md"):
                tgt += ".md"
            links_in.setdefault(tgt, set()).add(src)

    # Orphans (excluding root entry pages and outputs/escalations which are workflow-owned)
    root_pages = {"wiki/index.md", "wiki/overview.md", "wiki/log.md", "wiki/glossary.md"}
    orphans: list[dict[str, Any]] = []
    for path in pages:
        if path in root_pages:
            continue
        if path not in links_in or not links_in[path]:
            orphans.append({"path": path, "fm_type": pages[path]["fm"].get("type")})

    # Dead links
    dead_links: list[dict[str, Any]] = []
    for src, p in pages.items():
        for m in WIKI_LINK_RE.finditer(p["body"]):
            tgt = "wiki/" + m.group(1)
            if not tgt.endswith(".md"):
                tgt += ".md"
            if tgt not in pages:
                dead_links.append({"source": src, "target": tgt})

    # Stale (>90 days since last_updated)
    cutoff = datetime.now(timezone.utc).date() - timedelta(days=90)
    stale: list[dict[str, Any]] = []
    for path, p in pages.items():
        lu = p["fm"].get("last_updated")
        if not isinstance(lu, str):
            continue
        try:
            lu_date = datetime.fromisoformat(lu).date()
            if lu_date < cutoff:
                stale.append({"path": path, "last_updated": lu})
        except Exception:
            pass

    return {
        "scanned_pages": len(pages),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "orphans": sorted(orphans, key=lambda x: x["path"]),
        "dead_links": sorted(dead_links, key=lambda x: (x["source"], x["target"])),
        "stale_pages": sorted(stale, key=lambda x: x["path"]),
    }


# -------------------- gap analysis --------------------

def gap_analysis() -> dict[str, Any]:
    pages: dict[str, dict[str, Any]] = {}
    for path in WIKI_ROOT.rglob("*.md"):
        rel = "wiki/" + path.relative_to(WIKI_ROOT).as_posix()
        try:
            raw = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        fm, body = parse_frontmatter(raw)
        pages[rel] = {"path": rel, "fm": fm, "body": body}

    # Group by model
    model_pages: dict[str, list[str]] = {}
    for rel in pages:
        m = re.match(r"^wiki/projectors/([^/]+)/", rel)
        if m:
            model_pages.setdefault(m.group(1), []).append(rel)

    coverage_low_models = [
        {"model": model, "page_count": len(paths)}
        for model, paths in sorted(model_pages.items())
        if len(paths) < 5
    ]

    # Error codes with low source_count
    error_codes_low: list[dict[str, Any]] = []
    for rel, p in pages.items():
        if not rel.startswith("wiki/error-codes/"):
            continue
        sc_raw = p["fm"].get("source_count")
        try:
            sc = int(sc_raw) if sc_raw not in (None, "") else 0
        except (TypeError, ValueError):
            sc = 0
        if sc < 3:
            error_codes_low.append({"path": rel, "code": p["fm"].get("code"), "source_count": sc})

    # Resolution gaps
    resolution_missing: list[dict[str, Any]] = []
    for rel, p in pages.items():
        if not rel.startswith("wiki/error-codes/"):
            continue
        body_lower = p["body"].lower()
        if "standard resolution sequence" not in body_lower and "resolution sequence" not in body_lower:
            resolution_missing.append({"path": rel, "code": p["fm"].get("code")})

    # Environment gaps per model
    environment_gaps: list[dict[str, Any]] = []
    for model, paths in sorted(model_pages.items()):
        has_env = any(re.match(rf"^wiki/projectors/{re.escape(model)}/environments/", x) for x in paths)
        if not has_env:
            environment_gaps.append({"model": model})

    return {
        "scanned_pages": len(pages),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "coverage_low_models": sorted(coverage_low_models, key=lambda x: x["page_count"]),
        "error_codes_low_source_count": sorted(error_codes_low, key=lambda x: x["source_count"]),
        "resolution_missing": sorted(resolution_missing, key=lambda x: x["path"]),
        "environment_gaps": environment_gaps,
        "notes": [
            "Cross-reference gap detection requires raw-source link tracking (planned for later).",
            "Contradiction and duplicate-content detection require LLM analysis (not in lint v1).",
        ],
    }


# -------------------- markdown report rendering --------------------

def render_lint_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# AKARI wiki lint report",
        "",
        f"Generated: {report.get('generated_at', '?')}  ",
        f"Scanned: **{report['scanned_pages']}** pages",
        "",
    ]
    lines.append("## Orphan pages")
    lines.append(f"_Pages not linked from any other wiki page (root entry pages excluded)._")
    lines.append("")
    if not report["orphans"]:
        lines.append("None.")
    else:
        for o in report["orphans"]:
            lines.append(f"- `{o['path']}` ({o.get('fm_type') or '—'})")
    lines.append("")

    lines.append("## Dead wiki links")
    lines.append(f"_`[[wiki/...]]` references pointing to a non-existent target._")
    lines.append("")
    if not report["dead_links"]:
        lines.append("None.")
    else:
        for d in report["dead_links"]:
            lines.append(f"- `{d['source']}` → `{d['target']}`")
    lines.append("")

    lines.append("## Stale pages")
    lines.append(f"_Pages whose `last_updated` is older than 90 days._")
    lines.append("")
    if not report["stale_pages"]:
        lines.append("None.")
    else:
        for s in report["stale_pages"]:
            lines.append(f"- `{s['path']}` (last_updated {s['last_updated']})")
    lines.append("")

    return "\n".join(lines)


def render_gaps_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# AKARI wiki gap analysis",
        "",
        f"Generated: {report.get('generated_at', '?')}  ",
        f"Scanned: **{report['scanned_pages']}** pages",
        "",
    ]
    lines.append("## Coverage gaps — models with fewer than 5 pages")
    lines.append("")
    if not report["coverage_low_models"]:
        lines.append("None.")
    else:
        for c in report["coverage_low_models"]:
            lines.append(f"- **{c['model']}** — only {c['page_count']} page(s)")
    lines.append("")

    lines.append("## Error codes with low source_count (<3)")
    lines.append("")
    if not report["error_codes_low_source_count"]:
        lines.append("None.")
    else:
        for e in report["error_codes_low_source_count"]:
            lines.append(f"- `{e['path']}` (code `{e['code']}`, source_count = {e['source_count']})")
    lines.append("")

    lines.append("## Error code pages missing a resolution sequence")
    lines.append("")
    if not report["resolution_missing"]:
        lines.append("None.")
    else:
        for r in report["resolution_missing"]:
            lines.append(f"- `{r['path']}` (code `{r['code']}`)")
    lines.append("")

    lines.append("## Models without environment-specific pages")
    lines.append("")
    if not report["environment_gaps"]:
        lines.append("None.")
    else:
        for e in report["environment_gaps"]:
            lines.append(f"- **{e['model']}**")
    lines.append("")

    for n in report.get("notes", []):
        lines.append(f"> {n}")

    return "\n".join(lines)
