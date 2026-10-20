"""Audit / monitor database module.

monitor.db keeps strict-opsec per-diagnose event metadata and wiki-page
provenance. No query text, no diagnosis text, no user emails (only salted
SHA256 hashes). Used by Part 1 (admin monitor dashboard) and indirectly by
Part 5 (feedback) for joining the audit trail.

Three databases will eventually live in AKARI_DATA_DIR:
  monitor.db   — this file (audit + monitoring metadata, strict opsec)
  feedback.db  — Phase B (relaxed retention for feedback-bearing diagnoses)
  ingest.db    — Phase E (ingested_sources tracking)
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import time as _time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv

from api import user_labels


PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Load .env so AKARI_USER_HASH_SALT and AKARI_DATA_DIR are in os.environ
# (pydantic-settings reads .env into its own model, not os.environ).
load_dotenv(PROJECT_ROOT / ".env", override=False)


# -------------------- env + paths --------------------

def data_dir() -> Path:
    raw = os.environ.get("AKARI_DATA_DIR", "./data")
    p = Path(raw)
    if not p.is_absolute():
        p = (PROJECT_ROOT / p).resolve()
    p.mkdir(parents=True, exist_ok=True)
    return p


def monitor_db_path() -> Path:
    return data_dir() / "monitor.db"


def feedback_db_path() -> Path:
    return data_dir() / "feedback.db"


def ingest_db_path() -> Path:
    return data_dir() / "ingest.db"


def backup_dir() -> Path:
    p = data_dir().parent / "backup"
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_salt() -> str:
    salt = os.environ.get("AKARI_USER_HASH_SALT", "").strip()
    if not salt:
        raise RuntimeError(
            "AKARI_USER_HASH_SALT is missing or empty in environment. "
            "The audit system refuses to start without a deploy-stable salt. "
            "Generate one with: python -c 'import secrets; print(secrets.token_hex(32))' "
            "and add it to .env as AKARI_USER_HASH_SALT=<value>."
        )
    return salt


# -------------------- schema --------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS diagnose_events (
    diagnosis_id          TEXT PRIMARY KEY,
    ts                    TEXT NOT NULL,
    hashed_user           TEXT,
    depth_tier            TEXT,
    confidence            REAL,
    confidence_bucket     TEXT,
    coverage              TEXT,
    latency_ms            INTEGER,
    success               INTEGER NOT NULL,
    error_class           TEXT,
    image_used            INTEGER NOT NULL DEFAULT 0,
    pages_count           INTEGER,
    wiki_pages_used       TEXT,
    query_classification  TEXT,
    schema_version        INTEGER NOT NULL DEFAULT 3,
    prompt_tokens         INTEGER,
    response_tokens       INTEGER,
    total_tokens          INTEGER,
    tokens_per_second     REAL,
    inference_duration_ms INTEGER,
    gpu_util_percent_avg  REAL,
    vram_used_mb_peak     INTEGER,
    cpu_percent_avg       REAL,
    ram_used_mb_peak      INTEGER,
    problem_text          TEXT,
    model_input           TEXT,
    ips_log_summary       TEXT,
    full_response_text    TEXT
);

CREATE INDEX IF NOT EXISTS idx_events_ts ON diagnose_events(ts);
CREATE INDEX IF NOT EXISTS idx_events_user ON diagnose_events(hashed_user);
CREATE INDEX IF NOT EXISTS idx_events_depth ON diagnose_events(depth_tier);

CREATE TABLE IF NOT EXISTS wiki_page_history (
    path           TEXT NOT NULL,
    git_commit_id  TEXT NOT NULL,
    ts             TEXT NOT NULL,
    hashed_user    TEXT,
    change_type    TEXT NOT NULL,
    origin         TEXT NOT NULL,
    source_id      TEXT,
    diff_summary   TEXT,
    PRIMARY KEY (path, git_commit_id)
);

CREATE INDEX IF NOT EXISTS idx_wph_path ON wiki_page_history(path);
CREATE INDEX IF NOT EXISTS idx_wph_ts ON wiki_page_history(ts);
CREATE INDEX IF NOT EXISTS idx_wph_origin ON wiki_page_history(origin);

-- Admin-set status for usage-driven knowledge gaps (open vs addressed).
-- gap_key is "<model>::<theme>"; see knowledge_gaps() below.
CREATE TABLE IF NOT EXISTS knowledge_gap_status (
    gap_key      TEXT PRIMARY KEY,
    status       TEXT NOT NULL DEFAULT 'open',
    note         TEXT,
    updated_ts   TEXT NOT NULL,
    hashed_user  TEXT
);

-- Demo mode: pre-staged diagnoses keyed by a hash of (problem, depth tier).
-- When demo mode is on, /diagnose returns a matching cached response instantly
-- instead of running ~150s inference. Admin-curated; never auto-populated.
CREATE TABLE IF NOT EXISTS demo_cache (
    input_hash          TEXT PRIMARY KEY,
    problem             TEXT NOT NULL,
    model_input         TEXT,
    depth_tier          TEXT,
    response_json       TEXT NOT NULL,
    source_diagnosis_id TEXT,
    approved_at         TEXT NOT NULL,
    approved_by         TEXT
);
"""


def _connect(path: Optional[Path] = None) -> sqlite3.Connection:
    conn = sqlite3.connect(path or monitor_db_path())
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def _connect_feedback() -> sqlite3.Connection:
    return _connect(feedback_db_path())


def _connect_ingest() -> sqlite3.Connection:
    return _connect(ingest_db_path())


# Schema migrations on diagnose_events. All ALTERs are idempotent: each
# column is added only if PRAGMA table_info doesn't list it. Pre-existing
# rows stay valid with the new columns as NULL.
#
# v2 (2026-05-23): tokens + system-load metrics. Writers were reverted on
#                  2026-05-24 (CPU contention regression suspected); the
#                  columns are kept for a future out-of-process sampler.
# v3 (2026-05-24): full audit fields (user input + model output text).
_DIAGNOSE_EVENTS_LATER_COLUMNS = (
    # v2
    ("prompt_tokens",         "INTEGER"),
    ("response_tokens",       "INTEGER"),
    ("total_tokens",          "INTEGER"),
    ("tokens_per_second",     "REAL"),
    ("inference_duration_ms", "INTEGER"),
    ("gpu_util_percent_avg",  "REAL"),
    ("vram_used_mb_peak",     "INTEGER"),
    ("cpu_percent_avg",       "REAL"),
    ("ram_used_mb_peak",      "INTEGER"),
    # v3
    ("problem_text",          "TEXT"),
    ("model_input",           "TEXT"),
    ("ips_log_summary",       "TEXT"),
    ("full_response_text",    "TEXT"),
)


def _ensure_diagnose_events_columns(c: sqlite3.Connection) -> None:
    existing = {row["name"] for row in c.execute("PRAGMA table_info(diagnose_events)")}
    for name, kind in _DIAGNOSE_EVENTS_LATER_COLUMNS:
        if name not in existing:
            c.execute(f"ALTER TABLE diagnose_events ADD COLUMN {name} {kind}")


def init_monitor_db() -> Path:
    """Create monitor.db with the schema. Idempotent. Runs v1->v3 ALTERs in place."""
    p = monitor_db_path()
    with _connect(p) as c:
        c.executescript(SCHEMA)
        _ensure_diagnose_events_columns(c)
    return p


# -------------------- feedback.db schema --------------------

FEEDBACK_SCHEMA = """
CREATE TABLE IF NOT EXISTS diagnoses_with_feedback (
    diagnosis_id          TEXT PRIMARY KEY,
    problem_text          TEXT NOT NULL,
    diagnosis_response    TEXT NOT NULL,
    depth_tier            TEXT,
    wiki_pages_used       TEXT,
    visual_analysis       TEXT,
    hashed_user           TEXT NOT NULL,
    diagnosis_ts          TEXT NOT NULL,
    feedback_ts           TEXT NOT NULL,
    worked                INTEGER NOT NULL,
    what_fixed_it         TEXT,
    notes                 TEXT,
    last_updated          TEXT NOT NULL,
    deleted               INTEGER NOT NULL DEFAULT 0,
    schema_version        INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_fb_user ON diagnoses_with_feedback(hashed_user);
CREATE INDEX IF NOT EXISTS idx_fb_diag_ts ON diagnoses_with_feedback(diagnosis_ts);
CREATE INDEX IF NOT EXISTS idx_fb_worked ON diagnoses_with_feedback(worked);
CREATE INDEX IF NOT EXISTS idx_fb_deleted ON diagnoses_with_feedback(deleted);

-- Append-only follow-up notes. The initial feedback row above is immutable;
-- everything a user adds afterwards lands here as a new, never-edited row.
CREATE TABLE IF NOT EXISTS feedback_updates (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    diagnosis_id  TEXT NOT NULL,
    hashed_user   TEXT NOT NULL,
    update_ts     TEXT NOT NULL,
    text          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_fbu_diag ON feedback_updates(diagnosis_id);

-- Outbound email audit + idempotency (so a nudge is sent at most once).
CREATE TABLE IF NOT EXISTS email_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    diagnosis_id  TEXT,
    hashed_user   TEXT,
    kind          TEXT NOT NULL,   -- confirmation | update_receipt | nudge
    to_email      TEXT,
    status        TEXT NOT NULL,   -- sent | dry_run | failed | skipped_no_email
    provider_id   TEXT,
    error         TEXT,
    created_ts    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_email_diag ON email_log(diagnosis_id);
CREATE INDEX IF NOT EXISTS idx_email_kind ON email_log(kind);

-- Small key/value store for feature state (e.g. the nudge floor timestamp).
CREATE TABLE IF NOT EXISTS app_state (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


# Phase C (2026-08-28): Condition Diagnosis outcome loop.
_FEEDBACK_LATER_COLUMNS = (
    ("cd_verdict",        "TEXT"),   # verdict shown at diagnosis time (lsm/oe/...)
    ("cd_part_replaced",  "TEXT"),   # what the engineer actually replaced
)


def _ensure_feedback_columns(c: sqlite3.Connection) -> None:
    existing = {row["name"] for row in c.execute("PRAGMA table_info(diagnoses_with_feedback)")}
    for name, kind in _FEEDBACK_LATER_COLUMNS:
        if name not in existing:
            c.execute(f"ALTER TABLE diagnoses_with_feedback ADD COLUMN {name} {kind}")


# Which replaced parts count as "agreeing" with a verdict.
CD_VERDICT_AGREES = {
    "lsm": {"lsm"},
    "oe": {"oe", "pop"},
    "lsm_and_oe": {"lsm", "oe", "pop"},
    "lddr": {"lddr"},
    "no_part": {"none"},
    "calibrate_first": {"none"},
    "oe_or_ma": {"oe", "pop", "main_board"},
}


def metrics_cd_outcomes() -> dict[str, Any]:
    """Condition Diagnosis verdict vs actual part replaced, from feedback rows."""
    with _connect_feedback() as c:
        _ensure_feedback_columns(c)
        rows = c.execute(
            "SELECT cd_verdict, cd_part_replaced, worked FROM diagnoses_with_feedback "
            "WHERE deleted = 0 AND cd_verdict IS NOT NULL"
        ).fetchall()
    total = len(rows)
    with_part = agree = disagree = 0
    by_verdict: dict[str, dict[str, int]] = {}
    for r in rows:
        v = r["cd_verdict"] or "unknown"
        part = (r["cd_part_replaced"] or "").strip().lower()
        slot = by_verdict.setdefault(v, {"total": 0, "agree": 0, "disagree": 0, "no_part_info": 0, "worked": 0})
        slot["total"] += 1
        if r["worked"]:
            slot["worked"] += 1
        if not part:
            slot["no_part_info"] += 1
            continue
        with_part += 1
        if part in CD_VERDICT_AGREES.get(v, set()):
            agree += 1
            slot["agree"] += 1
        else:
            disagree += 1
            slot["disagree"] += 1
    return {
        "total_with_verdict": total,
        "with_part_info": with_part,
        "agree": agree,
        "disagree": disagree,
        "accuracy_pct": round(agree / with_part * 100.0, 1) if with_part else None,
        "by_verdict": by_verdict,
    }


def init_feedback_db() -> Path:
    """Create feedback.db with the schema. Idempotent."""
    p = feedback_db_path()
    with _connect_feedback() as c:
        c.executescript(FEEDBACK_SCHEMA)
    return p


# -------------------- ingest.db schema --------------------

INGEST_SCHEMA = """
CREATE TABLE IF NOT EXISTS ingested_sources (
    source_id      TEXT PRIMARY KEY,
    uploaded_at    TEXT NOT NULL,
    uploader       TEXT,
    original_name  TEXT NOT NULL,
    file_hash      TEXT NOT NULL UNIQUE,
    file_path      TEXT NOT NULL,
    source_type    TEXT NOT NULL,
    authority      TEXT,
    notes          TEXT,
    status         TEXT NOT NULL,
    status_detail  TEXT,
    extracted_at   TEXT,
    drafted_at     TEXT,
    approved_at    TEXT,
    rejected_at    TEXT,
    digest_path    TEXT,
    draft_dir      TEXT,
    schema_version INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_ingest_status ON ingested_sources(status);
CREATE INDEX IF NOT EXISTS idx_ingest_uploaded ON ingested_sources(uploaded_at);
CREATE INDEX IF NOT EXISTS idx_ingest_type ON ingested_sources(source_type);
"""


def init_ingest_db() -> Path:
    """Create ingest.db with the schema. Idempotent."""
    p = ingest_db_path()
    with _connect_ingest() as c:
        c.executescript(INGEST_SCHEMA)
    return p


# -------------------- ingest.db writers --------------------

def find_source_by_hash(file_hash: str) -> Optional[dict[str, Any]]:
    """Returns the existing source record for that hash, or None."""
    with _connect_ingest() as c:
        row = c.execute(
            "SELECT * FROM ingested_sources WHERE file_hash = ?", (file_hash,)
        ).fetchone()
    if not row:
        return None
    return {k: row[k] for k in row.keys()}


def insert_source(
    *,
    source_id: str,
    uploader: Optional[str],
    original_name: str,
    file_hash: str,
    file_path: str,
    source_type: str,
    authority: Optional[str],
    notes: Optional[str],
) -> dict[str, Any]:
    """Insert a new ingested_sources row with status='extracted_pending' (extraction will run next)."""
    now = now_utc_iso()
    with _connect_ingest() as c:
        c.execute(
            """
            INSERT INTO ingested_sources (
                source_id, uploaded_at, uploader, original_name, file_hash,
                file_path, source_type, authority, notes, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source_id, now, uploader, original_name, file_hash,
                file_path, source_type, authority, notes, "uploaded",
            ),
        )
    return get_source(source_id) or {}


def update_source_status(
    source_id: str,
    status: str,
    *,
    status_detail: Optional[str] = None,
    digest_path: Optional[str] = None,
    draft_dir: Optional[str] = None,
) -> None:
    """Update status with the right timestamp column."""
    ts_col_map = {
        "extracted":         "extracted_at",
        "drafted":           "drafted_at",
        "approved":          "approved_at",
        "rejected":          "rejected_at",
        "extraction_failed": "extracted_at",
        "drafting_failed":   "drafted_at",
    }
    ts_col = ts_col_map.get(status)
    now = now_utc_iso()
    fields = ["status = ?"]
    params: list[Any] = [status]
    if status_detail is not None:
        fields.append("status_detail = ?")
        params.append(status_detail)
    if digest_path is not None:
        fields.append("digest_path = ?")
        params.append(digest_path)
    if draft_dir is not None:
        fields.append("draft_dir = ?")
        params.append(draft_dir)
    if ts_col:
        fields.append(f"{ts_col} = ?")
        params.append(now)
    params.append(source_id)

    with _connect_ingest() as c:
        c.execute(
            f"UPDATE ingested_sources SET {', '.join(fields)} WHERE source_id = ?",
            params,
        )


def get_source(source_id: str) -> Optional[dict[str, Any]]:
    with _connect_ingest() as c:
        row = c.execute(
            "SELECT * FROM ingested_sources WHERE source_id = ?", (source_id,)
        ).fetchone()
    if not row:
        return None
    return {k: row[k] for k in row.keys()}


def list_sources(*, status: Optional[str] = None, limit: int = 200) -> list[dict[str, Any]]:
    where, params = "", []
    if status:
        where = "WHERE status = ?"
        params.append(status)
    with _connect_ingest() as c:
        rows = c.execute(
            f"SELECT * FROM ingested_sources {where} ORDER BY uploaded_at DESC LIMIT ?",
            params + [limit],
        ).fetchall()
    return [{k: r[k] for k in r.keys()} for r in rows]


def list_failed_sources() -> list[dict[str, Any]]:
    with _connect_ingest() as c:
        rows = c.execute(
            "SELECT * FROM ingested_sources WHERE status IN ('extraction_failed', 'drafting_failed') ORDER BY uploaded_at DESC"
        ).fetchall()
    return [{k: r[k] for k in r.keys()} for r in rows]


# -------------------- helpers --------------------

def hash_user(email: Optional[str]) -> Optional[str]:
    """SHA256(salt + email). Returns None if email is None/blank."""
    if not email or not email.strip():
        return None
    salt = get_salt()
    h = hashlib.sha256()
    h.update(salt.encode("utf-8"))
    h.update(email.strip().lower().encode("utf-8"))
    return h.hexdigest()


def hash_content(text: str) -> str:
    """SHA256 of raw file contents (for wiki page snapshots)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def git_head_commit(repo: Optional[Path] = None) -> Optional[str]:
    """Current HEAD commit ID, or None if git is unavailable."""
    try:
        result = subprocess.run(
            ["git", "-C", str(repo or PROJECT_ROOT), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=3,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None


def latest_origin_for_path(path_str: str) -> str:
    """Most recent origin label recorded for a wiki page, defaulting to 'original'."""
    try:
        with _connect() as c:
            row = c.execute(
                "SELECT origin FROM wiki_page_history WHERE path = ? ORDER BY ts DESC LIMIT 1",
                (path_str,),
            ).fetchone()
        if row:
            return row["origin"]
    except Exception:
        pass
    return "original"


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def confidence_bucket(c: Optional[float]) -> Optional[str]:
    if c is None:
        return None
    if c >= 0.75:
        return "high"
    if c >= 0.5:
        return "med"
    return "low"


# -------------------- writers --------------------

def write_diagnose_event(
    *,
    diagnosis_id: str,
    ts: str,
    hashed_user: Optional[str],
    depth_tier: Optional[str],
    confidence: Optional[float],
    coverage: Optional[str],
    latency_ms: int,
    success: bool,
    error_class: Optional[str],
    image_used: bool,
    pages_count: int,
    wiki_pages_used: list[dict[str, Any]],
    query_classification: dict[str, Any],
    prompt_tokens: Optional[int] = None,
    response_tokens: Optional[int] = None,
    total_tokens: Optional[int] = None,
    tokens_per_second: Optional[float] = None,
    inference_duration_ms: Optional[int] = None,
    gpu_util_percent_avg: Optional[float] = None,
    vram_used_mb_peak: Optional[int] = None,
    cpu_percent_avg: Optional[float] = None,
    ram_used_mb_peak: Optional[int] = None,
    problem_text: Optional[str] = None,
    model_input: Optional[str] = None,
    ips_log_summary: Optional[str] = None,
    full_response_text: Optional[str] = None,
) -> None:
    """Best-effort write of one diagnose event. Logs internally on failure but never raises.

    Schema v2 fields (prompt_tokens etc.) come from the in-process sampler
    (api/sampler.py). Schema v3 audit fields (problem_text, model_input,
    ips_log_summary, full_response_text) come from the request + parsed
    response. All admin-only; never exposed to the user UI.
    """
    try:
        with _connect() as c:
            c.execute(
                """
                INSERT OR REPLACE INTO diagnose_events (
                    diagnosis_id, ts, hashed_user, depth_tier,
                    confidence, confidence_bucket, coverage,
                    latency_ms, success, error_class,
                    image_used, pages_count,
                    wiki_pages_used, query_classification,
                    prompt_tokens, response_tokens, total_tokens,
                    tokens_per_second, inference_duration_ms,
                    gpu_util_percent_avg, vram_used_mb_peak,
                    cpu_percent_avg, ram_used_mb_peak,
                    problem_text, model_input, ips_log_summary, full_response_text
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    diagnosis_id,
                    ts,
                    hashed_user,
                    depth_tier,
                    confidence,
                    confidence_bucket(confidence),
                    coverage,
                    latency_ms,
                    1 if success else 0,
                    error_class,
                    1 if image_used else 0,
                    pages_count,
                    json.dumps(wiki_pages_used, separators=(",", ":")),
                    json.dumps(query_classification, separators=(",", ":")),
                    prompt_tokens,
                    response_tokens,
                    total_tokens,
                    tokens_per_second,
                    inference_duration_ms,
                    gpu_util_percent_avg,
                    vram_used_mb_peak,
                    cpu_percent_avg,
                    ram_used_mb_peak,
                    problem_text,
                    model_input,
                    ips_log_summary,
                    full_response_text,
                ),
            )
    except Exception as e:
        import sys
        print(f"[monitor] write_diagnose_event failed: {e}", file=sys.stderr)


def write_page_history(
    *,
    path: str,
    git_commit_id: str,
    ts: Optional[str] = None,
    hashed_user: Optional[str] = None,
    change_type: str,
    origin: str,
    source_id: Optional[str] = None,
    diff_summary: Optional[str] = None,
) -> bool:
    """Insert one row into wiki_page_history. Returns True if inserted, False if (path, commit) already exists."""
    try:
        with _connect() as c:
            existing = c.execute(
                "SELECT 1 FROM wiki_page_history WHERE path = ? AND git_commit_id = ?",
                (path, git_commit_id),
            ).fetchone()
            if existing:
                return False
            c.execute(
                """
                INSERT INTO wiki_page_history (
                    path, git_commit_id, ts, hashed_user,
                    change_type, origin, source_id, diff_summary
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    path,
                    git_commit_id,
                    ts or now_utc_iso(),
                    hashed_user,
                    change_type,
                    origin,
                    source_id,
                    diff_summary,
                ),
            )
        return True
    except Exception as e:
        import sys
        print(f"[monitor] write_page_history failed: {e}", file=sys.stderr)
        return False


# -------------------- feedback.db writers / readers --------------------

# 90 days in seconds, applied to diagnosis_ts to compute public-link expiry.
FEEDBACK_LINK_TTL_SECONDS = 90 * 24 * 60 * 60


def _now() -> str:
    return now_utc_iso()


def upsert_feedback(
    *,
    diagnosis_id: str,
    problem_text: str,
    diagnosis_response: dict[str, Any],
    depth_tier: Optional[str],
    wiki_pages_used: list[dict[str, Any]],
    visual_analysis: Optional[str],
    hashed_user: str,
    diagnosis_ts: str,
    worked: int,
    what_fixed_it: Optional[str],
    notes: Optional[str],
    cd_verdict: Optional[str] = None,
    cd_part_replaced: Optional[str] = None,
) -> dict[str, Any]:
    """Insert or update a feedback row. Returns the resulting row as a dict."""
    now = _now()
    with _connect_feedback() as c:
        _ensure_feedback_columns(c)
        existing = c.execute(
            "SELECT diagnosis_id, hashed_user, feedback_ts, deleted FROM diagnoses_with_feedback WHERE diagnosis_id = ?",
            (diagnosis_id,),
        ).fetchone()
        if existing is None:
            c.execute(
                """
                INSERT INTO diagnoses_with_feedback (
                    diagnosis_id, problem_text, diagnosis_response, depth_tier,
                    wiki_pages_used, visual_analysis, hashed_user,
                    diagnosis_ts, feedback_ts, worked, what_fixed_it, notes, last_updated,
                    cd_verdict, cd_part_replaced
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    diagnosis_id,
                    problem_text,
                    json.dumps(diagnosis_response, separators=(",", ":")),
                    depth_tier,
                    json.dumps(wiki_pages_used, separators=(",", ":")),
                    visual_analysis,
                    hashed_user,
                    diagnosis_ts,
                    now,
                    1 if worked else 0,
                    what_fixed_it,
                    notes,
                    now,
                    cd_verdict,
                    cd_part_replaced,
                ),
            )
        else:
            c.execute(
                """
                UPDATE diagnoses_with_feedback
                SET worked = ?, what_fixed_it = ?, notes = ?, last_updated = ?, deleted = 0
                WHERE diagnosis_id = ?
                """,
                (1 if worked else 0, what_fixed_it, notes, now, diagnosis_id),
            )
    return get_feedback(diagnosis_id) or {}


def get_feedback(diagnosis_id: str) -> Optional[dict[str, Any]]:
    """Read a feedback row (returns the row even if deleted=1; caller decides)."""
    with _connect_feedback() as c:
        row = c.execute(
            "SELECT * FROM diagnoses_with_feedback WHERE diagnosis_id = ?",
            (diagnosis_id,),
        ).fetchone()
    if not row:
        return None
    return {k: row[k] for k in row.keys()}


def soft_delete_feedback(diagnosis_id: str) -> bool:
    """Mark a feedback row as deleted. Returns True if a row was updated."""
    with _connect_feedback() as c:
        cur = c.execute(
            "UPDATE diagnoses_with_feedback SET deleted = 1, last_updated = ? WHERE diagnosis_id = ?",
            (_now(), diagnosis_id),
        )
    return cur.rowcount > 0


def is_public_link_expired(diagnosis_ts: str) -> bool:
    """True if the diagnosis was made more than FEEDBACK_LINK_TTL_SECONDS ago."""
    try:
        ts = datetime.fromisoformat(diagnosis_ts)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - ts).total_seconds()
        return age > FEEDBACK_LINK_TTL_SECONDS
    except Exception:
        return False


# -------------------- append-only feedback updates --------------------

def append_feedback_update(*, diagnosis_id: str, hashed_user: str, text: str) -> dict[str, Any]:
    """Add a follow-up note. Never edits the immutable initial feedback row;
    only bumps its last_updated so the admin view shows recent activity."""
    now = _now()
    with _connect_feedback() as c:
        c.execute(
            "INSERT INTO feedback_updates (diagnosis_id, hashed_user, update_ts, text) VALUES (?, ?, ?, ?)",
            (diagnosis_id, hashed_user, now, text),
        )
        c.execute(
            "UPDATE diagnoses_with_feedback SET last_updated = ? WHERE diagnosis_id = ?",
            (now, diagnosis_id),
        )
    return {"diagnosis_id": diagnosis_id, "update_ts": now, "text": text}


def get_feedback_updates(diagnosis_id: str) -> list[dict[str, Any]]:
    with _connect_feedback() as c:
        rows = c.execute(
            "SELECT id, update_ts, text, hashed_user FROM feedback_updates "
            "WHERE diagnosis_id = ? ORDER BY update_ts ASC, id ASC",
            (diagnosis_id,),
        ).fetchall()
    return [
        {"id": r["id"], "update_ts": r["update_ts"], "text": r["text"], "hashed_user": r["hashed_user"]}
        for r in rows
    ]


# -------------------- email log + feature state --------------------

def record_email(*, diagnosis_id: Optional[str], hashed_user: Optional[str], kind: str,
                 to_email: Optional[str], status: str, provider_id: Optional[str] = None,
                 error: Optional[str] = None) -> None:
    with _connect_feedback() as c:
        c.execute(
            "INSERT INTO email_log (diagnosis_id, hashed_user, kind, to_email, status, "
            "provider_id, error, created_ts) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (diagnosis_id, hashed_user, kind, to_email, status, provider_id, error, _now()),
        )


def email_already_sent(diagnosis_id: str, kind: str) -> bool:
    """True if a send of this kind was already attempted (sent or dry-run),
    so we never double-nudge."""
    with _connect_feedback() as c:
        row = c.execute(
            "SELECT 1 FROM email_log WHERE diagnosis_id = ? AND kind = ? "
            "AND status IN ('sent', 'dry_run') LIMIT 1",
            (diagnosis_id, kind),
        ).fetchone()
    return row is not None


def app_state_get(key: str, default: Optional[str] = None) -> Optional[str]:
    with _connect_feedback() as c:
        row = c.execute("SELECT value FROM app_state WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def app_state_set(key: str, value: str) -> None:
    with _connect_feedback() as c:
        c.execute(
            "INSERT INTO app_state (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


# -------------------- demo mode --------------------

DEMO_MODE_KEY = "demo_mode"


def demo_mode_enabled() -> bool:
    return (app_state_get(DEMO_MODE_KEY, "off") or "off").lower() == "on"


def demo_mode_set(enabled: bool) -> None:
    app_state_set(DEMO_MODE_KEY, "on" if enabled else "off")


def demo_cache_key(problem: Optional[str], depth_tier: Optional[str]) -> str:
    """Stable key for a demo query. Normalizes whitespace + case on the problem
    and the depth tier so the same typed query maps to the same staged answer.
    Deliberately ignores the IPS log: demo queries are staged by problem text,
    and the stored response already reflects whatever log was used."""
    norm_problem = " ".join((problem or "").split()).lower()
    norm_depth = (depth_tier or "fast").lower()
    return hashlib.sha256(f"{norm_problem}|{norm_depth}".encode("utf-8")).hexdigest()


def demo_cache_get(input_hash: str) -> Optional[dict[str, Any]]:
    with _connect() as c:
        row = c.execute(
            "SELECT * FROM demo_cache WHERE input_hash = ?", (input_hash,)
        ).fetchone()
    return dict(row) if row else None


def demo_cache_count() -> int:
    with _connect() as c:
        return c.execute("SELECT COUNT(*) AS n FROM demo_cache").fetchone()["n"]


def demo_cache_list() -> list[dict[str, Any]]:
    with _connect() as c:
        rows = c.execute(
            "SELECT input_hash, problem, model_input, depth_tier, "
            "source_diagnosis_id, approved_at, approved_by "
            "FROM demo_cache ORDER BY approved_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def demo_cache_delete(input_hash: str) -> bool:
    with _connect() as c:
        cur = c.execute("DELETE FROM demo_cache WHERE input_hash = ?", (input_hash,))
        return cur.rowcount > 0


def demo_cache_approve(diagnosis_id: str, approved_by: Optional[str] = None) -> Optional[dict[str, Any]]:
    """Stage a past diagnose_event as a demo response. Reads the stored problem,
    depth tier, and validated response text from monitor.db and upserts a
    demo_cache row keyed the same way /diagnose looks it up. Returns None if the
    event is missing or has no stored response text."""
    with _connect() as c:
        row = c.execute(
            "SELECT problem_text, model_input, depth_tier, full_response_text "
            "FROM diagnose_events WHERE diagnosis_id = ?", (diagnosis_id,)
        ).fetchone()
        if not row or not row["full_response_text"] or not row["problem_text"]:
            return None
        key = demo_cache_key(row["problem_text"], row["depth_tier"])
        c.execute(
            "INSERT INTO demo_cache (input_hash, problem, model_input, depth_tier, "
            "response_json, source_diagnosis_id, approved_at, approved_by) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(input_hash) DO UPDATE SET "
            "problem=excluded.problem, model_input=excluded.model_input, "
            "depth_tier=excluded.depth_tier, response_json=excluded.response_json, "
            "source_diagnosis_id=excluded.source_diagnosis_id, "
            "approved_at=excluded.approved_at, approved_by=excluded.approved_by",
            (key, row["problem_text"], row["model_input"], row["depth_tier"],
             row["full_response_text"], diagnosis_id, now_utc_iso(), approved_by),
        )
    return {"input_hash": key, "problem": row["problem_text"]}


def diagnoses_needing_nudge(*, floor_ts: str, older_than_hours: int = 24,
                            limit: int = 50) -> list[dict[str, Any]]:
    """Successful diagnoses older than N hours, after the feature floor, that
    have no feedback and no prior nudge. Cross-DB, so filtered in Python."""
    cutoff = _cutoff_iso(older_than_hours * 3600)  # ts <= cutoff => older than N hours
    with _connect() as c:  # monitor.db
        rows = c.execute(
            """
            SELECT diagnosis_id, ts, hashed_user, problem_text
            FROM diagnose_events
            WHERE success = 1 AND hashed_user IS NOT NULL
              AND ts <= ? AND ts >= ?
            ORDER BY ts DESC LIMIT ?
            """,
            (cutoff, floor_ts, limit * 4),
        ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        did = r["diagnosis_id"]
        if get_feedback(did):                 # already engaged
            continue
        if email_already_sent(did, "nudge"):  # already nudged
            continue
        out.append({
            "diagnosis_id": did, "ts": r["ts"],
            "hashed_user": r["hashed_user"], "problem_text": r["problem_text"],
        })
        if len(out) >= limit:
            break
    return out


# -------------------- admin metrics --------------------

def _cutoff_iso(seconds_ago: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)).isoformat(timespec="seconds")


def _percentile(sorted_values: list[float], q: float) -> Optional[float]:
    if not sorted_values:
        return None
    idx = max(0, min(len(sorted_values) - 1, int(round(q * (len(sorted_values) - 1)))))
    return float(sorted_values[idx])


def metrics_overview() -> dict[str, Any]:
    """Headline metrics: counts/rates at 1h, 24h, 7d windows + global counters."""
    out: dict[str, Any] = {"windows": {}}
    with _connect() as c:
        out["total_events"] = c.execute("SELECT COUNT(*) FROM diagnose_events").fetchone()[0]
        latest = c.execute(
            "SELECT ts FROM diagnose_events WHERE success = 1 ORDER BY ts DESC LIMIT 1"
        ).fetchone()
        out["last_successful_ts"] = latest["ts"] if latest else None
        out["unique_hashed_users_all_time"] = c.execute(
            "SELECT COUNT(DISTINCT hashed_user) FROM diagnose_events WHERE hashed_user IS NOT NULL"
        ).fetchone()[0]
        # Named per-user breakdown (admin-only display; NULL folds into "Service / headless").
        user_rows = c.execute(
            "SELECT hashed_user, COUNT(*) AS n FROM diagnose_events GROUP BY hashed_user"
        ).fetchall()
        out["users_named"] = user_labels.named_breakdown(
            [(r["hashed_user"], r["n"]) for r in user_rows]
        )

        for label, secs in (("1h", 3600), ("24h", 86400), ("7d", 7 * 86400)):
            cutoff = _cutoff_iso(secs)
            row = c.execute(
                """
                SELECT
                    COUNT(*) AS n,
                    SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) AS ok,
                    SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) AS err,
                    SUM(CASE WHEN image_used = 1 THEN 1 ELSE 0 END) AS img,
                    COUNT(DISTINCT hashed_user) AS users
                FROM diagnose_events
                WHERE ts >= ?
                """,
                (cutoff,),
            ).fetchone()
            n = row["n"] or 0
            out["windows"][label] = {
                "total": n,
                "success": row["ok"] or 0,
                "error": row["err"] or 0,
                "error_rate": ((row["err"] or 0) / n) if n else None,
                "image_assisted_rate": ((row["img"] or 0) / n) if n else None,
                "unique_users": row["users"] or 0,
            }
    return out


def metrics_activity(window_hours: int = 24) -> dict[str, Any]:
    """Hourly bucketed event counts for the trailing window_hours."""
    cutoff = _cutoff_iso(window_hours * 3600)
    with _connect() as c:
        rows = c.execute(
            """
            SELECT substr(ts, 1, 13) AS hour_key, COUNT(*) AS n
            FROM diagnose_events
            WHERE ts >= ?
            GROUP BY hour_key
            ORDER BY hour_key
            """,
            (cutoff,),
        ).fetchall()
    return {"window_hours": window_hours, "buckets": [{"hour": r["hour_key"], "n": r["n"]} for r in rows]}


def metrics_performance(window_hours: int = 24) -> dict[str, Any]:
    """Latency stats per depth_tier and overall."""
    cutoff = _cutoff_iso(window_hours * 3600)
    with _connect() as c:
        rows = c.execute(
            "SELECT depth_tier, latency_ms FROM diagnose_events WHERE ts >= ? AND latency_ms IS NOT NULL",
            (cutoff,),
        ).fetchall()
    by_tier: dict[str, list[int]] = {}
    for r in rows:
        tier = (r["depth_tier"] or "unknown").lower()
        by_tier.setdefault(tier, []).append(r["latency_ms"])

    def summarise(values: list[int]) -> dict[str, Any]:
        if not values:
            return {"n": 0}
        s = sorted(values)
        return {
            "n": len(s),
            "min_ms": s[0],
            "median_ms": int(_percentile(s, 0.5) or 0),
            "p95_ms": int(_percentile(s, 0.95) or 0),
            "p99_ms": int(_percentile(s, 0.99) or 0),
            "max_ms": s[-1],
        }

    overall = [v for vs in by_tier.values() for v in vs]
    return {
        "window_hours": window_hours,
        "overall": summarise(overall),
        "by_tier": {tier: summarise(vs) for tier, vs in by_tier.items()},
    }


def metrics_quality(window_hours: int = 24) -> dict[str, Any]:
    """Confidence bucket + coverage distribution."""
    cutoff = _cutoff_iso(window_hours * 3600)
    with _connect() as c:
        conf_rows = c.execute(
            """
            SELECT COALESCE(confidence_bucket, 'unknown') AS bucket, COUNT(*) AS n
            FROM diagnose_events
            WHERE ts >= ?
            GROUP BY bucket
            """,
            (cutoff,),
        ).fetchall()
        cov_rows = c.execute(
            """
            SELECT COALESCE(coverage, 'unknown') AS cov, COUNT(*) AS n
            FROM diagnose_events
            WHERE ts >= ?
            GROUP BY cov
            """,
            (cutoff,),
        ).fetchall()
    return {
        "window_hours": window_hours,
        "confidence": {r["bucket"]: r["n"] for r in conf_rows},
        "coverage": {r["cov"]: r["n"] for r in cov_rows},
    }


def metrics_tokens() -> dict[str, Any]:
    """Token consumption + per-tier throughput (admin Overview card)."""
    cutoff_7d = _cutoff_iso(7 * 86400)
    with _connect() as c:
        tot_all = c.execute(
            "SELECT COALESCE(SUM(total_tokens), 0) FROM diagnose_events WHERE total_tokens IS NOT NULL"
        ).fetchone()[0]
        tot_7d = c.execute(
            "SELECT COALESCE(SUM(total_tokens), 0) FROM diagnose_events WHERE total_tokens IS NOT NULL AND ts >= ?",
            (cutoff_7d,),
        ).fetchone()[0]
        per_diag_values = [
            r[0] for r in c.execute(
                "SELECT total_tokens FROM diagnose_events WHERE total_tokens IS NOT NULL ORDER BY total_tokens"
            ).fetchall()
        ]
        tps_rows = c.execute(
            "SELECT depth_tier, AVG(tokens_per_second) AS tps "
            "FROM diagnose_events "
            "WHERE tokens_per_second IS NOT NULL AND depth_tier IS NOT NULL "
            "GROUP BY depth_tier"
        ).fetchall()

    if per_diag_values:
        s = sorted(per_diag_values)
        per_diag = {
            "min": int(s[0]),
            "median": int(_percentile(s, 0.5) or 0),
            "max": int(s[-1]),
            "n": len(s),
        }
    else:
        per_diag = {"min": None, "median": None, "max": None, "n": 0}

    return {
        "total_all_time": int(tot_all),
        "total_7d": int(tot_7d),
        "per_diagnosis": per_diag,
        "tokens_per_second_by_tier": {
            r["depth_tier"]: round(float(r["tps"]), 2) for r in tps_rows
        },
    }


def metrics_resolution_kpi(window_hours: Optional[int] = None) -> dict[str, Any]:
    """Worked / didn't work / no_feedback across diagnose_events, joined with feedback.db."""
    where = ""
    params: tuple = ()
    if window_hours is not None:
        where = "WHERE ts >= ?"
        params = (_cutoff_iso(window_hours * 3600),)

    with _connect() as c:
        diag_rows = c.execute(
            f"SELECT diagnosis_id, depth_tier FROM diagnose_events {where}",
            params,
        ).fetchall()

    if not diag_rows:
        return {"worked": 0, "didnt_work": 0, "no_feedback": 0, "by_tier": {}}

    diag_ids = [r["diagnosis_id"] for r in diag_rows]
    tier_by_id = {r["diagnosis_id"]: (r["depth_tier"] or "unknown") for r in diag_rows}
    fb_map: dict[str, dict[str, Any]] = {}
    chunk = 500
    with _connect_feedback() as fc:
        for i in range(0, len(diag_ids), chunk):
            batch = diag_ids[i : i + chunk]
            placeholders = ",".join("?" * len(batch))
            for r in fc.execute(
                f"SELECT diagnosis_id, worked, deleted FROM diagnoses_with_feedback WHERE diagnosis_id IN ({placeholders})",
                batch,
            ):
                fb_map[r["diagnosis_id"]] = {"worked": r["worked"], "deleted": r["deleted"]}

    def status_for(diag_id: str) -> str:
        rec = fb_map.get(diag_id)
        if not rec or rec["deleted"]:
            return "no_feedback"
        return "worked" if rec["worked"] else "didnt_work"

    total = {"worked": 0, "didnt_work": 0, "no_feedback": 0}
    by_tier: dict[str, dict[str, int]] = {}
    for diag_id in diag_ids:
        s = status_for(diag_id)
        total[s] += 1
        tier = tier_by_id[diag_id]
        by_tier.setdefault(tier, {"worked": 0, "didnt_work": 0, "no_feedback": 0})[s] += 1
    total["by_tier"] = by_tier
    return total


# -------------------- knowledge gaps (usage-driven) --------------------
#
# Surfaces what the wiki is WEAK on, derived from real /diagnose traffic, so an
# admin knows what to ingest next. This complements wiki_ops.gap_analysis(),
# which only inspects the wiki's own structure (orphans, low source_count) and
# has no idea what users actually asked. A diagnose event counts as "weak" when
# any of: coverage poor/partial, confidence low, <=1 wiki page used, or the user
# said it didn't work. Weak events are grouped by (detected model, theme), where
# theme is a coarse keyword bucket over the problem text.

_GAP_THEME_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("color/tint",     ("color", "colour", "tint", "yellow", "magenta", "hue", "banding", "stain", "blemish")),
    ("touch/pen",      ("touch", "pen", "finger", "interactive", "calibrat", "stylus")),
    ("lamp/light",     ("lamp", "bulb", "laser", "brightness", "dim", "luminance", "elplp")),
    ("thermal/fan",    ("fan", "overheat", "temperature", "thermal", "cooling", "filter", "dust")),
    ("signal/hdmi",    ("hdmi", "no signal", "input", "source", "flicker", "sync", "edid", "hdbaset")),
    ("network/lan",    ("network", "lan", "wifi", "wi-fi", "wireless", "ethernet", "iprojection")),
    ("lens/focus",     ("lens", "focus", "zoom", "keystone", "blurry", "geometr")),
    ("audio",          ("audio", "sound", "speaker", "volume", "mute")),
    ("usb/media",      ("usb", "media", "playback", "sd card")),
    ("power/boot",     ("no power", "dead", "boot", "standby", "shutdown", "shuts down", "restart", "reboot")),
    ("remote/control", ("remote", "button", "menu")),
    ("firmware/sw",    ("firmware", "update", "software", "freeze", "hang")),
    ("image/optical",  ("no image", "image", "picture", "display", "projection", "optical", "panel")),
)


def _classify_theme(text: Optional[str]) -> str:
    t = (text or "").lower()
    if not t.strip():
        return "unspecified"
    for theme, kws in _GAP_THEME_KEYWORDS:
        if any(kw in t for kw in kws):
            return theme
    return "other"


def _suggest_gap_action(model: str, theme: str) -> str:
    m = model if model and model.lower() not in ("unknown", "auto", "") else "the detected model"
    return (f"Missing wiki coverage for {m} + {theme}. Search for and upload a "
            f"{theme} source for {m} (service manual chapter, technical bulletin, "
            f"or field repair data), then ingest it to add or extend the matching wiki page.")


def knowledge_gaps(window_hours: Optional[int] = None,
                   include_addressed: bool = False) -> dict[str, Any]:
    """Rank (model, theme) pairs the wiki answers poorly, from real diagnose traffic."""
    where, params = "", ()
    if window_hours is not None:
        where = "WHERE ts >= ?"
        params = (_cutoff_iso(window_hours * 3600),)

    with _connect() as c:
        rows = c.execute(
            f"""SELECT diagnosis_id, ts, model_input, coverage, confidence_bucket,
                       pages_count, problem_text
                FROM diagnose_events {where}""",
            params,
        ).fetchall()
        status_rows = c.execute(
            "SELECT gap_key, status, note, updated_ts FROM knowledge_gap_status"
        ).fetchall()

    status_map = {
        r["gap_key"]: {"status": r["status"], "note": r["note"], "updated_ts": r["updated_ts"]}
        for r in status_rows
    }
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    if not rows:
        return {"window_hours": window_hours, "generated_at": generated_at,
                "total_events": 0, "gap_count": 0, "gaps": []}

    # feedback lookup (chunked IN, same pattern as metrics_resolution_kpi)
    diag_ids = [r["diagnosis_id"] for r in rows]
    fb_map: dict[str, dict[str, Any]] = {}
    chunk = 500
    with _connect_feedback() as fc:
        for i in range(0, len(diag_ids), chunk):
            batch = diag_ids[i : i + chunk]
            ph = ",".join("?" * len(batch))
            for r in fc.execute(
                f"SELECT diagnosis_id, worked, deleted FROM diagnoses_with_feedback WHERE diagnosis_id IN ({ph})",
                batch,
            ):
                fb_map[r["diagnosis_id"]] = {"worked": r["worked"], "deleted": r["deleted"]}

    groups: dict[tuple[str, str], dict[str, Any]] = {}
    for r in rows:
        model = (r["model_input"] or "unknown").strip() or "unknown"
        theme = _classify_theme(r["problem_text"])
        g = groups.setdefault((model, theme), {
            "model": model, "theme": theme, "total": 0, "weak": 0,
            "poor_coverage": 0, "partial_coverage": 0, "low_confidence": 0,
            "thin_pages": 0, "didnt_work": 0, "last_seen": "", "examples": [],
        })
        g["total"] += 1

        cov = (r["coverage"] or "").lower()
        conf = (r["confidence_bucket"] or "").lower()
        pages = r["pages_count"]
        fb = fb_map.get(r["diagnosis_id"])
        didnt_work = bool(fb and not fb["deleted"] and fb["worked"] == 0)

        weak = False
        if cov == "poor":
            g["poor_coverage"] += 1; weak = True
        elif cov == "partial":
            g["partial_coverage"] += 1; weak = True
        if conf == "low":
            g["low_confidence"] += 1; weak = True
        if pages is not None and pages <= 1:
            g["thin_pages"] += 1; weak = True
        if didnt_work:
            g["didnt_work"] += 1; weak = True

        if weak:
            g["weak"] += 1
            if (r["ts"] or "") > g["last_seen"]:
                g["last_seen"] = r["ts"] or ""
            if len(g["examples"]) < 5 and r["problem_text"]:
                g["examples"].append({"ts": r["ts"], "text": r["problem_text"][:160]})

    gaps: list[dict[str, Any]] = []
    for (model, theme), g in groups.items():
        if g["weak"] == 0:
            continue
        gap_key = f"{model}::{theme}"
        st = status_map.get(gap_key, {"status": "open", "note": None, "updated_ts": None})
        if st["status"] == "addressed" and not include_addressed:
            continue
        # "didn't work" is the strongest signal (a real failure), weight it.
        score = g["weak"] + g["didnt_work"] * 2
        gaps.append({
            **g,
            "gap_key": gap_key,
            "weak_pct": round(100 * g["weak"] / g["total"], 1) if g["total"] else 0,
            "score": score,
            "status": st["status"],
            "note": st["note"],
            "status_updated": st["updated_ts"],
            "suggested_action": _suggest_gap_action(model, theme),
        })

    gaps.sort(key=lambda x: (-x["score"], -x["weak"], -x["total"]))
    return {"window_hours": window_hours, "generated_at": generated_at,
            "total_events": len(rows), "gap_count": len(gaps), "gaps": gaps}


def set_knowledge_gap_status(gap_key: str, status: str,
                             note: Optional[str] = None,
                             hashed_user: Optional[str] = None) -> dict[str, Any]:
    if status not in ("open", "addressed"):
        raise ValueError("status must be 'open' or 'addressed'")
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _connect() as c:
        c.execute(
            """INSERT INTO knowledge_gap_status (gap_key, status, note, updated_ts, hashed_user)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(gap_key) DO UPDATE SET
                   status=excluded.status, note=excluded.note,
                   updated_ts=excluded.updated_ts, hashed_user=excluded.hashed_user""",
            (gap_key, status, note, ts, hashed_user),
        )
    return {"gap_key": gap_key, "status": status, "updated_ts": ts}


# A = remote desktop (primary, "remote"), B = local PC (backup, "local-pc").
_SRC_CODE = {"remote": "A", "local-pc": "B"}


def _src_code_from_qc(qc_text: Optional[str]) -> Optional[str]:
    """Opaque source-tier code (A primary / B backup / C external) from the
    stored backend label. None for rows predating failover (no backend recorded)."""
    if not qc_text:
        return None
    try:
        backend = json.loads(qc_text).get("backend") or {}
        return _SRC_CODE.get(backend.get("label"))
    except Exception:
        return None


def list_diagnoses(limit: int = 50, offset: int = 0, depth: Optional[str] = None) -> dict[str, Any]:
    """Paginated diagnose_events with feedback status joined from feedback.db."""
    where, params = "", []
    if depth:
        where = "WHERE depth_tier = ?"
        params.append(depth.lower())
    with _connect() as c:
        total = c.execute(f"SELECT COUNT(*) FROM diagnose_events {where}", params).fetchone()[0]
        rows = c.execute(
            f"""
            SELECT diagnosis_id, ts, hashed_user, depth_tier, confidence_bucket,
                   coverage, latency_ms, success, error_class, image_used, pages_count,
                   prompt_tokens, response_tokens, tokens_per_second,
                   gpu_util_percent_avg, vram_used_mb_peak, inference_duration_ms,
                   query_classification
            FROM diagnose_events
            {where}
            ORDER BY ts DESC
            LIMIT ? OFFSET ?
            """,
            params + [limit, offset],
        ).fetchall()

    diag_ids = [r["diagnosis_id"] for r in rows]
    fb_map: dict[str, dict[str, Any]] = {}
    if diag_ids:
        placeholders = ",".join("?" * len(diag_ids))
        with _connect_feedback() as fc:
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

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": [
            {
                "diagnosis_id": r["diagnosis_id"],
                "ts": r["ts"],
                "hashed_user_short": (r["hashed_user"] or "")[:10] if r["hashed_user"] else None,
                "user_label": user_labels.resolve(r["hashed_user"]),
                "depth_tier": r["depth_tier"],
                "confidence_bucket": r["confidence_bucket"],
                "coverage": r["coverage"],
                "latency_ms": r["latency_ms"],
                "success": bool(r["success"]),
                "error_class": r["error_class"],
                "image_used": bool(r["image_used"]),
                "pages_count": r["pages_count"],
                "src": _src_code_from_qc(r["query_classification"]),
                "feedback_status": feedback_status(r["diagnosis_id"]),
                "prompt_tokens": r["prompt_tokens"],
                "response_tokens": r["response_tokens"],
                "tokens_per_second": r["tokens_per_second"],
                "gpu_util_percent_avg": r["gpu_util_percent_avg"],
                "vram_used_mb_peak": r["vram_used_mb_peak"],
                "inference_duration_ms": r["inference_duration_ms"],
            }
            for r in rows
        ],
    }


def get_diagnosis_detail(diagnosis_id: str) -> Optional[dict[str, Any]]:
    """Full audit trail for one diagnose_event including per-page history lookups + feedback."""
    with _connect() as c:
        row = c.execute(
            "SELECT * FROM diagnose_events WHERE diagnosis_id = ?", (diagnosis_id,)
        ).fetchone()
        if not row:
            return None
        wiki_pages = json.loads(row["wiki_pages_used"]) if row["wiki_pages_used"] else []
        query_class = json.loads(row["query_classification"]) if row["query_classification"] else {}

        # Per-page history lookups: most recent change for each path
        for page in wiki_pages:
            path = page.get("path")
            if not path:
                continue
            hist_rows = c.execute(
                """
                SELECT git_commit_id, ts, change_type, origin, source_id, diff_summary
                FROM wiki_page_history
                WHERE path = ?
                ORDER BY ts DESC
                """,
                (path,),
            ).fetchall()
            page["history"] = [
                {
                    "git_commit_id": h["git_commit_id"],
                    "git_commit_short": h["git_commit_id"][:8],
                    "ts": h["ts"],
                    "change_type": h["change_type"],
                    "origin": h["origin"],
                    "source_id": h["source_id"],
                    "diff_summary": h["diff_summary"],
                }
                for h in hist_rows
            ]

        full_response: Optional[dict[str, Any]] = None
        if row["full_response_text"]:
            try:
                full_response = json.loads(row["full_response_text"])
            except Exception:
                full_response = None

        detail = {
            "diagnosis_id": row["diagnosis_id"],
            "ts": row["ts"],
            "hashed_user": row["hashed_user"],
            "user_label": user_labels.resolve(row["hashed_user"]),
            "depth_tier": row["depth_tier"],
            "confidence": row["confidence"],
            "confidence_bucket": row["confidence_bucket"],
            "coverage": row["coverage"],
            "latency_ms": row["latency_ms"],
            "success": bool(row["success"]),
            "error_class": row["error_class"],
            "image_used": bool(row["image_used"]),
            "pages_count": row["pages_count"],
            "wiki_pages_used": wiki_pages,
            "query_classification": query_class,
            "prompt_tokens": row["prompt_tokens"],
            "response_tokens": row["response_tokens"],
            "total_tokens": row["total_tokens"],
            "tokens_per_second": row["tokens_per_second"],
            "inference_duration_ms": row["inference_duration_ms"],
            "gpu_util_percent_avg": row["gpu_util_percent_avg"],
            "vram_used_mb_peak": row["vram_used_mb_peak"],
            "cpu_percent_avg": row["cpu_percent_avg"],
            "ram_used_mb_peak": row["ram_used_mb_peak"],
            "problem_text": row["problem_text"],
            "model_input": row["model_input"],
            "ips_log_summary": row["ips_log_summary"],
            "full_response": full_response,
        }

    # Feedback record if present
    fb = get_feedback(diagnosis_id)
    if fb and not fb.get("deleted"):
        detail["feedback"] = {
            "worked": bool(fb["worked"]),
            "what_fixed_it": fb["what_fixed_it"],
            "notes": fb["notes"],
            "feedback_ts": fb["feedback_ts"],
            "last_updated": fb["last_updated"],
            "problem_text": fb["problem_text"],
            "diagnosis_response": json.loads(fb["diagnosis_response"]) if fb["diagnosis_response"] else None,
            "updates": get_feedback_updates(diagnosis_id),
        }
    elif fb and fb.get("deleted"):
        detail["feedback"] = {"deleted": True, "last_updated": fb["last_updated"]}
    else:
        detail["feedback"] = None

    return detail


def export_feedback_rows() -> list[dict[str, Any]]:
    """All feedback rows for CSV export (admin-only consumer)."""
    with _connect_feedback() as c:
        rows = c.execute(
            """
            SELECT diagnosis_id, diagnosis_ts, feedback_ts, last_updated, depth_tier,
                   hashed_user, worked, what_fixed_it, notes, deleted
            FROM diagnoses_with_feedback
            ORDER BY diagnosis_ts DESC
            """
        ).fetchall()
    return [
        {
            "diagnosis_id": r["diagnosis_id"],
            "diagnosis_ts": r["diagnosis_ts"],
            "feedback_ts": r["feedback_ts"],
            "last_updated": r["last_updated"],
            "depth_tier": r["depth_tier"],
            "hashed_user": r["hashed_user"],
            "user_label": user_labels.resolve(r["hashed_user"]),
            "worked": "yes" if r["worked"] else "no",
            "what_fixed_it": (r["what_fixed_it"] or "").replace("\n", " ").strip(),
            "notes": (r["notes"] or "").replace("\n", " ").strip(),
            "deleted": "yes" if r["deleted"] else "no",
        }
        for r in rows
    ]


# -------------------- backup --------------------

BACKUP_INTERVAL_SECONDS = 7 * 24 * 60 * 60   # weekly
BACKUP_KEEP = 4                               # rolling, oldest pruned


def backup_db_once(src_path: Path, name_prefix: str) -> Optional[Path]:
    """Use SQLite VACUUM INTO to create a safe online snapshot.

    Returns the snapshot path on success, None on failure.
    """
    if not src_path.exists():
        return None
    bdir = backup_dir()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = bdir / f"{name_prefix}-{stamp}.db"
    try:
        if out.exists():
            out.unlink()
        with sqlite3.connect(src_path) as src:
            src.execute(f"VACUUM INTO '{out.as_posix()}'")
        return out
    except Exception as e:
        import sys
        print(f"[backup] {name_prefix}: {e}", file=sys.stderr)
        return None


def prune_old_backups(name_prefix: str, keep: int = BACKUP_KEEP) -> int:
    snaps = sorted(backup_dir().glob(f"{name_prefix}-*.db"), reverse=True)
    deleted = 0
    for old in snaps[keep:]:
        try:
            old.unlink()
            deleted += 1
        except Exception:
            pass
    return deleted


def maybe_run_weekly_backup(name_prefix: str, src_path: Path) -> bool:
    """If no snapshot exists in the last BACKUP_INTERVAL_SECONDS, create one and prune."""
    if not src_path.exists():
        return False
    snaps = sorted(backup_dir().glob(f"{name_prefix}-*.db"), reverse=True)
    if snaps:
        age = _time.time() - snaps[0].stat().st_mtime
        if age < BACKUP_INTERVAL_SECONDS:
            return False
    p = backup_db_once(src_path, name_prefix)
    if p:
        prune_old_backups(name_prefix)
        return True
    return False


def run_all_backups() -> dict[str, bool]:
    """One-shot helper: try to back up all three DBs."""
    return {
        "monitor":  maybe_run_weekly_backup("monitor",  monitor_db_path()),
        "feedback": maybe_run_weekly_backup("feedback", feedback_db_path()),
        "ingest":   maybe_run_weekly_backup("ingest",   ingest_db_path()),
    }


# -------------------- audit snapshot helper --------------------

def page_snapshot_for_event(page_path: Path, repo_root: Path, head_commit: Optional[str]) -> dict[str, Any]:
    """Build the per-page audit record embedded in a diagnose_event."""
    rel = page_path.relative_to(repo_root).as_posix() if repo_root in page_path.parents else page_path.as_posix()
    try:
        content = page_path.read_text(encoding="utf-8")
        content_hash = hash_content(content)
    except Exception:
        content_hash = None
    origin = latest_origin_for_path(rel)
    return {
        "path": rel,
        "content_sha256": content_hash,
        "git_commit_id": head_commit,
        "origin": origin,
        "ingested_from_source_id": None,
    }
