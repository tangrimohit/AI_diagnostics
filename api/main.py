from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shutil
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from ollama import AsyncClient
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from api import db  # audit / monitor DB module
from api import drafter  # LLM drafter for ingestion pipeline
from api import emailer  # outbound email (feedback confirmations + nudges)
from api import extractor  # source extraction (pdf / xlsx / docx / csv / text)
from api import gpu_watch  # local GPU power-cap watcher (failover trigger + admin alert)
from api import inference  # backend failover across Ollama hosts for /diagnose
from api import ips_knowledge  # deterministic IPS log decoder (codes, YE factors, I2C)
from api import cd_gate  # Condition Diagnosis ask-for-values gate
from api import cd_knowledge  # Condition Diagnosis deterministic verdict (Phase B)
from api import ips_log_parser  # IPS Tool TSV parser
from api import sampler  # GPU / CPU / RAM metrics sampling
from api import user_labels  # hash -> display-name registry (admin-only)
from api import wiki_ops  # wiki content management


PROJECT_ROOT = Path(__file__).resolve().parent.parent

MAX_IPS_LOG_CHARS = 8_000   # cap log sent to LLM; prevents context overflow on large TSV exports


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    ollama_host: str = "http://localhost:11434"
    # Header the identity-aware reverse proxy sets with the logged-in user email.
    auth_email_header: str = "x-authenticated-user-email"
    # Priority-ordered failover list (comma-separated). Empty -> [ollama_host].
    # e.g. "http://localhost:11434,http://192.168.1.50:11434" (local PC then remote host).
    ollama_hosts: str = ""
    ollama_health_timeout: float = 2.0
    wiki_path: Path = PROJECT_ROOT / "wiki"
    raw_path: Path = PROJECT_ROOT / "raw"
    model_fast: str = "gemma3:4b"
    model_deep: str = "gemma4:e2b"
    # How long Ollama keeps a model resident after a request. Must be a Go
    # duration string (the python client rejects the int sentinel "-1"). "24h"
    # keeps the model warm across a full work day so repeated same-tier queries
    # stay warm instead of re-paying the ~90s reload, and it auto-releases after
    # a full idle day. Was "30m", which unloaded on idle and made every first
    # query after a short gap slow.
    ollama_keep_alive: str = "24h"
    log_level: str = "INFO"
    # Condition Diagnosis (IPS Tool 2.4.2): ask-for-values gate + evaluator policy.
    cd_warmup_minutes: int = 20          # under this, values are reference only
    cd_gap_threshold: int = 20           # OE-Sensor / actual-Sensor decision gap
    cd_help_url: str = ""                # internal article on how to run and read it


settings = Settings()
if not settings.wiki_path.is_absolute():
    settings.wiki_path = (PROJECT_ROOT / settings.wiki_path).resolve()
if not settings.raw_path.is_absolute():
    settings.raw_path = (PROJECT_ROOT / settings.raw_path).resolve()

ollama = AsyncClient(host=settings.ollama_host, timeout=600)

app = FastAPI(title="AKARI Diagnostic", version="0.1.1")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def _startup_audit() -> None:
    # Refuse to boot without a stable hash salt — opsec requirement.
    db.get_salt()
    db.init_monitor_db()
    db.init_feedback_db()
    db.init_ingest_db()
    # Try a backup immediately on startup if one is overdue, then keep checking every 6h.
    asyncio.create_task(_backup_loop())
    # Set the nudge floor once: only diagnoses from this point on are eligible for
    # the no-feedback reminder, so we never spam the historical backlog.
    if not db.app_state_get("nudge_floor_ts"):
        db.app_state_set("nudge_floor_ts", db.now_utc_iso())
    asyncio.create_task(_nudge_loop())
    # Watch the local GPU for the recurring power-cap throttle. On a confirmed
    # cap it flips inference's degraded flag (routes /diagnose to Plan B/C) and
    # emails the admins; recovery restores local routing.
    asyncio.create_task(gpu_watch.watch_loop(_gpu_alert))
    # Warm models into VRAM so the first user request after a cold boot doesn't
    # exceed the reverse proxy's 100s edge timeout while ollama loads weights.
    asyncio.create_task(_warmup_models())


async def _warmup_models() -> None:
    # On the RTX 3050 (4 GB), only one model fits in VRAM at a time —
    # warming both would just evict whichever loaded first. Warm only
    # the Fast tier (the default for most users); Balanced/Deep loads
    # on first use, paying a ~90s reload cost that the polling pattern
    # tolerates.
    model_name = settings.model_fast
    t0 = time.perf_counter()
    try:
        host = await inference.select_backend(settings, model_name=model_name)
        if host is None:
            print(f"[warmup] no backend serves {model_name}; skipping", file=sys.stderr, flush=True)
            return
        client = inference._client_for(host)
        await client.generate(
            model=model_name,
            prompt="ok",
            keep_alive=settings.ollama_keep_alive,
            # Match the diagnose num_ctx (16384) so the warm model is actually
            # reused; a smaller warmup ctx forces a full reload on the first real query.
            options={"num_predict": 1, "num_ctx": 16384, "temperature": 0.0},
        )
        elapsed = time.perf_counter() - t0
        print(f"[warmup] {model_name} resident on {inference.label_for_host(host)} after {elapsed:.1f}s", file=sys.stderr, flush=True)
    except Exception as e:
        print(f"[warmup] {model_name} failed: {type(e).__name__}: {e}", file=sys.stderr, flush=True)


async def _backup_loop() -> None:
    while True:
        try:
            done = await asyncio.to_thread(db.run_all_backups)
            for name, ran in done.items():
                if ran:
                    print(f"[backup] weekly snapshot created for {name}.db", file=sys.stderr)
        except Exception as e:
            print(f"[backup loop] error: {e}", file=sys.stderr)
        await asyncio.sleep(6 * 60 * 60)


# ---------- Feedback email (confirmations + nudges) ----------

def _send_and_log(*, diagnosis_id: Optional[str], hashed_user: Optional[str], kind: str,
                  subject: str, html: str, text: str) -> None:
    """Resolve the user's email, send (or dry-run), and record the attempt.
    Synchronous + exception-safe; callers run it off the request path via a thread."""
    to_email = user_labels.email_for_hash(hashed_user)
    if not to_email:
        db.record_email(diagnosis_id=diagnosis_id, hashed_user=hashed_user, kind=kind,
                        to_email=None, status="skipped_no_email")
        return
    res = emailer.send(to_email, subject, html, text)
    db.record_email(diagnosis_id=diagnosis_id, hashed_user=hashed_user, kind=kind,
                    to_email=to_email, status=res.get("status", "failed"),
                    provider_id=res.get("id"), error=res.get("error"))


def _fire_email(**kwargs) -> None:
    """Fire-and-forget: never blocks or breaks the request that triggered it."""
    try:
        asyncio.create_task(asyncio.to_thread(_send_and_log, **kwargs))
    except Exception:
        pass


async def _nudge_loop() -> None:
    # Sweep for diagnoses that got no feedback after the delay, and send one nudge.
    # Both knobs are env-driven: production is 24h delay / hourly sweep; for the
    # demo set AKARI_NUDGE_DELAY_HOURS=0 + a short AKARI_NUDGE_SWEEP_SECONDS so a
    # no-feedback diagnosis gets nudged almost immediately. Flip back for wide use.
    delay_hours = int(os.environ.get("AKARI_NUDGE_DELAY_HOURS", "24"))
    sweep_secs = max(15, int(os.environ.get("AKARI_NUDGE_SWEEP_SECONDS", "3600")))
    print(f"[nudge] loop start: delay={delay_hours}h sweep={sweep_secs}s", file=sys.stderr)
    while True:
        try:
            floor = db.app_state_get("nudge_floor_ts") or db.now_utc_iso()
            due = await asyncio.to_thread(
                db.diagnoses_needing_nudge, floor_ts=floor, older_than_hours=delay_hours, limit=50
            )
            for d in due:
                subject, html, text = emailer.nudge_email(
                    diagnosis_id=d["diagnosis_id"],
                    problem_text=d.get("problem_text"),
                    diagnosis_ts=d.get("ts"),
                )
                await asyncio.to_thread(
                    _send_and_log,
                    diagnosis_id=d["diagnosis_id"], hashed_user=d["hashed_user"],
                    kind="nudge", subject=subject, html=html, text=text,
                )
            if due:
                print(f"[nudge] processed {len(due)} reminder(s)", file=sys.stderr)
        except Exception as e:
            print(f"[nudge loop] error: {e}", file=sys.stderr)
        await asyncio.sleep(sweep_secs)


# ---------- GPU power-cap alerts (admin channel) ----------

def _gpu_admin_recipients() -> list[str]:
    raw = os.environ.get(
        "AKARI_GPU_ALERT_TO", ""
    )
    return [a.strip() for a in raw.split(",") if a.strip() and "@" in a]


def _gpu_alert(kind: str, snap: dict) -> None:
    """Watcher callback. Email the admins on a confirmed throttle or recovery.
    Admin channel only, so GPU/backend detail is fine here (never user-facing).
    Offloaded to a thread; never blocks or breaks the watch loop."""
    last = snap.get("last") or {}
    detail = (
        f"power_limit={last.get('power_limit_w')}W  pstate={last.get('pstate')}  "
        f"temp={last.get('temp_c')}C  reasons={last.get('throttle_reasons')}  "
        f"at {last.get('ts')}"
    )
    if kind == "throttle":
        subject = "AKARI alert: local GPU power-capped, failover active"
        text = (
            "AKARI detected the recurring GPU power cap on the local machine.\n\n"
            f"Reading: {detail}\n"
            f"Floor that tripped it: {snap.get('floor_w')}W (normal is 35-40W).\n"
            f"Throttle episodes since last restart: {snap.get('episodes')}.\n\n"
            "Diagnoses are now routing to the backup node automatically, so "
            "the site keeps answering while capped.\n\n"
            "No software clears this cap (the power-limit override is blocked and a "
            "service bounce does not work). Only a reboot of the local machine "
            "restores full local inference. The reboot itself is a roughly 3 minute "
            "full outage of the site (everything runs on that machine), so pick a "
            "quiet window. The watcher will email again once it recovers."
        )
    elif kind == "recover":
        subject = "AKARI: local GPU recovered, local inference restored"
        text = (
            "The local GPU power cap has cleared and AKARI has switched diagnoses "
            "back to local inference.\n\n"
            f"Reading: {detail}\n"
            f"Total throttle episodes since last restart: {snap.get('episodes')}.\n"
        )
    else:
        return

    html = f"<pre style='font-family:Segoe UI,Arial,sans-serif;white-space:pre-wrap'>{text}</pre>"

    def _send_all() -> None:
        for to in _gpu_admin_recipients():
            try:
                res = emailer.send(to, subject, html, text)
                print(f"[gpu-watch] alert '{kind}' to {to}: {res.get('status')}",
                      file=sys.stderr, flush=True)
            except Exception as e:
                print(f"[gpu-watch] alert send failed to {to}: {e}", file=sys.stderr)

    try:
        asyncio.create_task(asyncio.to_thread(_send_all))
    except Exception:
        pass


def _hashed_user_from_request(request: Optional[Request]) -> Optional[str]:
    if request is None:
        return None
    # The identity-aware reverse proxy populates this header for browser sessions.
    email = request.headers.get(settings.auth_email_header)
    # Auto-learn a display name for new authenticated users (admin-only label
    # registry; the audit DB still stores only the hash). Exception-safe no-op
    # for already-known users.
    user_labels.note_user(email)
    return db.hash_user(email)


class DiagnoseRequest(BaseModel):
    problem: str = Field(..., description="User-described problem text")
    ips_log: Optional[str] = Field(None, description="IPS Tool log content")
    model: Optional[str] = Field(None, description="Projector model, e.g. EB-X49")
    use_thinking: bool = Field(False, description="Use the deeper model")
    depth_tier: Optional[str] = Field(
        None, description="UI-side depth label: 'fast' | 'balanced' | 'deep'"
    )
    image: Optional[str] = Field(
        None, description="Base64-encoded photo of the symptom (optional). Raw base64 or a data: URL."
    )
    cd_values: Optional["CDValues"] = Field(
        None, description="IPS Tool Condition Diagnosis values entered by the engineer (optional)."
    )


class CDValues(BaseModel):
    """The six on-screen Condition Diagnosis items plus what the engineer saw.
    All optional; the evaluator says what is missing."""
    ld_calibration: str = ""            # "OK" | "Not Yet"
    lddr: str = ""                      # "OK" | "NG"
    oe_pct: Optional[float] = None      # OE (or OE&LSM on fixed-phosphor models), 0..100
    sensor_pct: Optional[float] = None  # R/B sensor drop vs factory, 0..100
    lsm_by: Optional[float] = None      # 0..200, 100 = balanced white
    actual_brightness_pct: Optional[float] = None  # 9-point measurement vs spec, 0..100
    observed_color: str = ""            # "" | neutral | yellowish | bluish | other
    warmup_minutes: Optional[float] = None
    visibly_dirty: bool = False
    # Phase C: 9-point lumens (workbook sheet) and the flicker flow answers.
    measured_lumens: Optional[float] = None   # mean(9 lux) * screen area m2
    spec_lumens: Optional[float] = None       # catalogue brightness of the model
    flicker_normal_clears: str = ""           # "" | yes | no
    flicker_rasters: str = ""                 # "" | one | rg | all | none


class CDAnalysis(BaseModel):
    """Deterministic Condition Diagnosis verdict (cd_knowledge). Prose-free
    structure; the model never writes into it."""
    verdict: str = ""
    headline: str = ""
    findings: list[str] = []
    remedy: list[str] = []
    caveats: list[str] = []
    values: dict = {}
    reference_only: bool = False
    help_url: str = ""


class Diagnosis(BaseModel):
    primary_cause: str
    confidence: float = Field(..., ge=0.0, le=1.0)
    reasoning: str


class Solution(BaseModel):
    rank: int
    difficulty: str
    cost: str
    action: str
    estimated_time_minutes: int = 0
    estimated_cost_usd: float = 0.0
    reasoning: str
    wiki_sources: list[str] = []


class EscalationDraft(BaseModel):
    # Mirrors the common L3 escalation checklist so the draft is a complete,
    # send-in-one-message handover. AKARI fills what it can infer; fields that
    # only the engineer can know carry a ⟨...⟩ placeholder (rendered highlighted
    # in the UI) so nothing is silently dropped. No support-level wording.
    summary: str = ""
    model: str = ""
    serial: str = ""
    firmware_version: str = ""
    symptoms: str = ""
    error_evidence: str = ""
    references_checked: str = ""
    tried_steps: str = ""
    environment: str = ""
    connection_type: str = ""
    reproduction: str = ""
    diagnostic_logs: str = ""
    impact: str = ""
    suspected_cause: str = ""
    recommended_next: str = ""


class DiagnoseMetadata(BaseModel):
    diagnosis_id: str = ""
    wiki_pages_used: list[str] = []
    model_used: str = ""
    elapsed_seconds: float = 0.0
    wiki_coverage: str = "poor"
    output_format: str = "json"


class IpsAnalysis(BaseModel):
    """One concise read-out of the uploaded IPS log, only when the log shows
    something notable. summary is LLM prose; findings + severity are the
    deterministic decode (ips_knowledge), so structure is always valid."""
    summary: str = ""
    findings: list[str] = []
    severity: str = "info"  # critical | high | medium | low | info


class InfoRequest(BaseModel):
    """Set when the symptom is thin and no IPS log was attached: a prompt to
    the engineer to upload the log."""
    want: str = ""          # "ips_log" | "condition_diagnosis"
    message: str = ""
    help_url: str = ""      # optional link to the internal how-to article


class DiagnoseResponse(BaseModel):
    diagnosis: Diagnosis
    solutions: list[Solution]
    escalation_draft: EscalationDraft
    metadata: DiagnoseMetadata
    # Optional; absent renders nothing in the UI.
    ips_analysis: Optional[IpsAnalysis] = None
    info_request: Optional[InfoRequest] = None
    cd_analysis: Optional[CDAnalysis] = None


DiagnoseRequest.model_rebuild()


MODEL_RE = re.compile(
    # EB/CB/VS allow a glued tail (EBX49); CO/EH require a separator so prose
    # words like "control" or "eh" never match.
    r"\b(?:(?:EB|CB|VS)[- ]?[A-Z0-9]{2,}|(?:CO|EH)[- ][A-Z0-9]{2,})\b",
    re.IGNORECASE,
)
KNOWN_ERROR_CODES = {
    "TH", "FN", "LD", "MA", "IC", "YE", "PS", "OP", "SE",
    "YE-LDTH", "YE-LDFN", "YE-MA",
}


def canonicalize_model(raw: str) -> str:
    """Normalize a model string to "<PREFIX>-<TAIL>" form (e.g. "EB-X49").

    Handles "EBX49", "EB-X49", "EB X49", "eb-x49" → all become "EB-X49".
    Wiki dirs use the dashed form (wiki/projectors/eb-x49/), so the picker
    only finds pages when the model code is canonical.
    """
    m = raw.upper().replace(" ", "").replace("_", "")
    for prefix in ("EB", "CB", "VS", "CO", "EH"):
        if m.startswith(prefix):
            tail = m[len(prefix):].lstrip("-")
            if tail:
                return f"{prefix}-{tail}"
    return m


def detect_model(problem_text: Optional[str], log_extracted_model: str) -> Optional[str]:
    """Resolve the projector model the engineer is asking about.

    Priority: explicit code in the typed problem wins, IPS-log model is the
    fallback. Engineers sometimes paste mismatched logs, so the typed problem
    is treated as the authoritative signal.

    Returns the model code canonicalized to "<PREFIX>-<TAIL>" (e.g. "EB-X49"),
    or None when nothing was extractable — caller falls back to auto-mode
    retrieval across all models.
    """
    if problem_text:
        hits = MODEL_RE.findall(problem_text)
        if hits:
            return canonicalize_model(hits[0])
    if log_extracted_model:
        first = log_extracted_model.split("/")[0].strip()
        if first:
            return canonicalize_model(first)
    return None


# Specific symptom vocabulary. If the problem text carries any of these, the
# engineer has given us something concrete to diagnose, so we do NOT pester for
# the IPS log. Used by the thin-symptom gate.
STRONG_SYMPTOM_RE = re.compile(
    r"\b(no\s*power|won'?t\s*(turn\s*on|power|start)|dead|no\s*light|no\s*image|no\s*picture|"
    r"flicker|flash|blink|dim|brightness|bright|dark|colou?r|tint|yellow|green|magenta|cyan|"
    r"red|blue|purple|hue|shadow|spot|stain|blob|uniformity|focus|blur|"
    r"overheat|hot|temperatur|thermal|fan|noise|noisy|rattle|buzz|smell|burn|"
    r"shutdown|shuts?\s*down|reboot|restart|freez|hang|crash|"
    r"lamp|laser|light\s*source|ballast|lens|shift|shutter|filter|dust|"
    r"error\s*code|warning|blinking\s*light|indicator|led|hdmi|signal|usb|network|wifi|wireless)\b",
    re.IGNORECASE,
)

DEFAULT_ASK_LOG_MSG = (
    "Attach the IPS Tool log (.tsv) for a precise read. The symptom is brief, so the log's "
    "error and warning counters and the laser/thermal detail would sharpen this a lot. "
    "Capture it in VCOM mode via the IPS Tool (Get Error Log), or describe the symptom in more detail."
)


def is_thin_symptom(problem: Optional[str], detected_model: Optional[str], error_codes: list[str]) -> bool:
    """True when the problem is too sparse to diagnose well: no model, no error
    code, short, and no specific symptom keyword. Drives the ask-for-log prompt."""
    text = (problem or "").strip()
    if detected_model or error_codes:
        return False
    if STRONG_SYMPTOM_RE.search(text):
        return False
    return len(text.split()) < 8


def extract_entities(text: str) -> dict[str, list[str]]:
    models = sorted({m.upper().replace(" ", "") for m in MODEL_RE.findall(text)})
    up = text.upper()
    # Boundary on ASCII alphanumerics only, NOT \b. Python's \b treats CJK as
    # word chars, so `\bYE\b` fails to match "YEエラー" (no boundary before the
    # Japanese エ). Japanese is a primary language of the evaluation
    # traffic, so a code glued to Japanese text must still be detected. These
    # lookarounds are equivalent to \b for ASCII (so English is unchanged) but
    # treat any non-ASCII-alnum char (incl. CJK) as a boundary.
    codes = sorted({
        c for c in KNOWN_ERROR_CODES
        if re.search(rf"(?<![A-Z0-9]){re.escape(c)}(?![A-Z0-9])", up)
    })
    return {"models": models, "error_codes": codes}


MODEL_ROOT_PAGES = (
    "index.md",
    "known-failures.md",
    "critical-issues.md",
    "parts-reference.md",
    "specs.md",
)

# IPS error codes are abbreviations (TH, FN, SE...) but the wiki error-code
# pages are named by description (temp, fan, thermistor...). Map code -> slug so
# a detected code actually retrieves its page.
ERROR_CODE_PAGE = {
    "TH": "temp", "FN": "fan", "SE": "thermistor", "IC": "i2c",
    "YE": "ye", "PS": "power-supply-ballast", "PB": "power-supply-ballast",
    "DR": "dr", "IV": "iv",
}

# Per-code pages that are lamp 3LCD chassis (X49 / H971) specific. For a laser
# model the platform family page carries the laser error reference, so these are
# skipped to avoid leaking lamp part numbers (e.g. the X49 MA Board PN) into a
# laser diagnosis. ye.md is laser-specific and is never in this set.
LAMP_ONLY_ERROR_PAGES = {
    "temp", "fan", "thermistor", "ram", "inner", "dr", "iv", "i2c",
    "auto-iris", "power-supply-ballast",
}

# Optional `keywords: [..]` frontmatter list, matched against the query in
# addition to the filename slug. Lets a page surface on natural-language terms
# its slug does not contain (e.g. "wifi" -> wi-spy-dbx, "screen mirroring" ->
# miracast, "disassembly" -> internal-structure). Purely additive.
_KEYWORDS_RE = re.compile(r"^keywords:\s*\[(.*?)\]", re.M)


def _page_keywords(path: Path) -> list[str]:
    # Read only the frontmatter head. Called only for pages a slug match missed,
    # so at most ~one small read per candidate page per query. Not cached, so a
    # live admin edit to a page's keywords takes effect on the next query.
    try:
        head = path.read_text(encoding="utf-8")[:1500]
    except Exception:
        return []
    m = _KEYWORDS_RE.search(head)
    if not m:
        return []
    return [k.strip().strip("\"'").lower() for k in m.group(1).split(",") if k.strip()]


def _query_matches_page(query_lower: str, slug_words: set[str], path: Path) -> bool:
    """True if any distinctive slug word OR any declared keyword appears as a
    whole word/phrase in the query."""
    if any(re.search(rf"\b{re.escape(w)}\b", query_lower) for w in slug_words):
        return True
    return any(re.search(rf"\b{re.escape(k)}\b", query_lower) for k in _page_keywords(path))


def pick_wiki_pages(
    entities: dict[str, list[str]], wiki_root: Path, query_text: str = ""
) -> list[Path]:
    picked: list[Path] = []
    # The catalog index.md is intentionally NOT fed to the model: it is a link
    # list naming every family, which adds noise and biases the small model
    # toward whichever family is most prominent (causing cross-family answers).
    # Substantive pages (model, family, error-code, procedure, concept) carry
    # the real content.
    query_lower = query_text.lower()

    models = entities.get("models", [])
    # Auto mode (no model resolved) is handled AFTER keyword matching below, so
    # symptom-matched error-code / procedure / concept pages and rich platform
    # family pages claim slots first. Previously the modeless path pre-loaded
    # every projector index stub here and filled the entire 10-page budget,
    # starving every concept/procedure page (they were appended later, then
    # truncated). Deferring the stub backfill fixes that.

    model_is_platform: list[bool] = []
    for model in models:
        is_platform_model = False
        slug = model.lower()
        model_dir = wiki_root / "projectors" / slug
        for sub in MODEL_ROOT_PAGES:
            p = model_dir / sub
            if p.exists():
                picked.append(p)

        # A model page is a thin stub that links to its shared family page;
        # pull that family page in so the LLM gets the real failure knowledge.
        model_index = model_dir / "index.md"
        if model_index.is_file():
            try:
                idx_txt = model_index.read_text(encoding="utf-8")
            except Exception:
                idx_txt = ""
            is_platform_model = bool(re.search(r"\[\[wiki/platforms/", idx_txt))
            for fmatch in re.finditer(r"\[\[(wiki/platforms/[^\]\s]+?)\]\]", idx_txt):
                rel = fmatch.group(1)
                if not rel.endswith(".md"):
                    rel += ".md"
                fp = PROJECT_ROOT / rel
                if fp.is_file():
                    picked.append(fp)
            # A thin sibling stub may link to a hub model (e.g. the EB-X49
            # lamp family hub). Pull the hub's key pages so siblings inherit
            # the shared chassis knowledge (critical issues, known failures).
            for hmatch in re.finditer(r"\[\[wiki/projectors/([^/\]\s]+)/index\]\]", idx_txt):
                hub_slug = hmatch.group(1)
                if hub_slug == slug:
                    continue
                hub_dir = wiki_root / "projectors" / hub_slug
                for sub in MODEL_ROOT_PAGES:
                    hp = hub_dir / sub
                    if hp.is_file():
                        picked.append(hp)

        env_dir = model_dir / "environments"
        if env_dir.exists():
            picked.extend(sorted(env_dir.glob("*.md")))

        issues_dir = model_dir / "issues"
        if issues_dir.exists():
            stopwords = {
                "error", "issue", "issues", "problem", "fail", "failure",
                "failures", "not", "the", "and", "for", "with", "on", "off",
                "in", "of", "is", "to", "a", "an",
            }
            issue_pages = sorted(issues_dir.glob("*.md"))
            for p in issue_pages:
                slug_words = {
                    w for w in p.stem.lower().replace("_", "-").split("-")
                    if w and w not in stopwords
                }
                if any(re.search(rf"\b{re.escape(w)}\b", query_lower) for w in slug_words):
                    picked.append(p)

        model_is_platform.append(is_platform_model)

    # Laser / platform models carry their full error reference on the platform
    # family page. The per-code pages under error-codes/ are lamp 3LCD chassis
    # (X49 / H971) and would inject lamp part numbers into a laser diagnosis, so
    # skip the lamp-only ones when EVERY detected model is a laser/platform
    # model. Auto mode (no model) leaves the list empty and keeps lamp pages.
    laser_only = bool(model_is_platform) and all(model_is_platform)

    for code in entities.get("error_codes", []):
        slug = ERROR_CODE_PAGE.get(code.upper(), code.lower())
        p = wiki_root / "error-codes" / f"{slug}.md"
        if p.exists() and p not in picked and not (
            laser_only and slug in LAMP_ONLY_ERROR_PAGES
        ):
            picked.append(p)

    error_codes_dir = wiki_root / "error-codes"
    if error_codes_dir.exists():
        # Generic words are excluded so a multi-word error slug (e.g.
        # "power-supply-ballast", which is lamp-specific) only matches on its
        # distinctive term ("ballast"), not on a common word like "power".
        ec_stopwords = {"error", "issue", "the", "and", "for", "with", "code", "codes",
                        "power", "supply", "system", "board", "internal"}
        for p in sorted(error_codes_dir.glob("*.md")):
            slug_words = {
                w for w in p.stem.lower().replace("_", "-").split("-")
                if w and w not in ec_stopwords
            }
            if _query_matches_page(query_lower, slug_words, p) \
                    and p not in picked \
                    and not (laser_only and p.stem in LAMP_ONLY_ERROR_PAGES):
                picked.append(p)

    procedures_dir = wiki_root / "procedures"
    if procedures_dir.exists():
        proc_stopwords = {
            "the", "and", "for", "with", "of", "to", "a", "an",
            "procedure", "troubleshooting", "projector",
        }
        for p in sorted(procedures_dir.glob("*.md")):
            slug_words = {
                w for w in p.stem.lower().replace("_", "-").split("-")
                if w and w not in proc_stopwords
            }
            if _query_matches_page(query_lower, slug_words, p):
                picked.append(p)

    concepts_dir = wiki_root / "concepts"
    if concepts_dir.exists():
        concept_stopwords = {
            "the", "and", "for", "with", "of", "to", "a", "an",
            "vs", "tool", "projector",
        }
        for p in sorted(concepts_dir.glob("*.md")):
            slug_words = {
                w for w in p.stem.lower().replace("_", "-").split("-")
                if w and w not in concept_stopwords
            }
            if _query_matches_page(query_lower, slug_words, p):
                picked.append(p)

    # Auto-mode fallback: no model resolved. ONLY when nothing specific matched
    # (no error-code / procedure / concept page hit the query) do we fall back
    # to broad cross-model context: rich platform family pages, then thin
    # per-model index/critical-issues stubs. If specific pages DID match, we
    # trust them and stop here. The platform/model stubs are dominated by
    # optical-engine / air-filter / thermal field-failure text, so padding a
    # focused query (e.g. Miracast, HDR, HDMI) with ~8 of them dilutes the small
    # model's context and it answers from the noise instead of the one relevant
    # page. Focused context beats padded context for the on-box model.
    if not models and not picked:
        platforms_root = wiki_root / "platforms"
        if platforms_root.exists():
            for plat_dir in sorted(platforms_root.iterdir()):
                p = plat_dir / "index.md"
                if p.is_file():
                    picked.append(p)
        projectors_root = wiki_root / "projectors"
        if projectors_root.exists():
            for model_dir in sorted(projectors_root.iterdir()):
                if not model_dir.is_dir():
                    continue
                for sub in ("index.md", "critical-issues.md"):
                    p = model_dir / sub
                    if p.exists():
                        picked.append(p)

    seen: set[Path] = set()
    result: list[Path] = []
    for p in picked:
        if p in seen:
            continue
        seen.add(p)
        result.append(p)
        if len(result) >= 10:
            break
    # Hard guard: pages under wiki/_drafts/ must NEVER reach the retrieval
    # pipeline, even if a future picker rule accidentally adds them. Drafts
    # are provisional and admin-only until approved.
    result = [p for p in result if "_drafts" not in p.parts]
    return result


def load_pages(pages: list[Path]) -> str:
    chunks: list[str] = []
    for p in pages:
        rel = p.relative_to(PROJECT_ROOT).as_posix()
        chunks.append(f"\n\n=== {rel} ===\n\n{p.read_text(encoding='utf-8')}")
    return "".join(chunks) if chunks else "(no relevant wiki pages found)"


def assess_coverage(pages: list[Path]) -> str:
    """Estimate how well the wiki covers a query from the retrieved pages.

    Counts content pages (everything except the root catalog index.md) and gives
    a bonus when a substantial page is present. Under the family-page design a
    model often retrieves a thin stub plus ONE rich shared family page, so a raw
    page count understates coverage; the rich-page bonus corrects for that.
    """
    content = [
        p for p in pages
        if not (p.name == "index.md" and p.parent.name == "wiki")
    ]
    rich = any(
        ("/platforms/" in p.as_posix())
        or ("/concepts/" in p.as_posix())
        or ("/procedures/" in p.as_posix())
        or p.name in ("critical-issues.md", "known-failures.md", "parts-reference.md")
        for p in content
    )
    n = len(content) + (2 if rich else 0)
    if n >= 5:
        return "good"
    if n >= 2:
        return "partial"
    return "poor"


def page_paths_for_metadata(pages: list[Path]) -> list[str]:
    return [p.relative_to(PROJECT_ROOT).as_posix() for p in pages]


DIAGNOSE_PROMPT = """You are AKARI, a diagnostic assistant for Epson projectors. Answer only from the reference material below.

USER PROBLEM:
{problem}

IPS LOG:
{ips_log}

PROJECTOR MODEL: {model}

REFERENCE MATERIAL:
{wiki_content}

Rules:
1. Use ONLY the reference material as ground truth. Do not invent failure modes. CRITICAL: never state a specific part number, part name or code, error code, or measurement unless it appears verbatim in the reference material or the provided IPS log. If you lack the exact part or code, name the affected component in plain words (for example "the power supply board" or "the optical engine") and lower confidence, instead of inventing a plausible-looking number. A fabricated part number or code is a critical error that misleads the technician; omitting an unknown specific is correct, guessing one is not.
2. If the reference material has no relevant content, RETURN THE NO-DATA EXAMPLE BELOW. Do not return empty objects.
3. Give the top 2 to 3 solutions only (not five), cheapest/easiest first. Keep each solution's "action" to one clear step and its "reasoning" to a single short sentence.
4. Do not use em-dashes (long dashes) anywhere. Use parens or commas.
5. Always fill every field. Never return {{}}.
6. Output technical content only: symptoms, root cause, parts, error codes, and repair steps. NEVER mention or hint at specific case numbers, escalation or ticket or report IDs (such as TESC, SR, END, ENC, MSD numbers), customer or partner names, country or region names, incident dates, or internal project or platform codenames. If the reference text contains any such reference, silently drop it and state only the technical conclusion and solution.
7. "wiki_sources" is internal traceability only and is never shown to the user. Put an entry ONLY if it is a page path copied verbatim from a heading that appears in the REFERENCE MATERIAL above; if you are not copying an exact path shown above, leave it empty. Never invent, guess, or paraphrase a page name. Never put a case ID, customer, or country there.
8. Calibrate "confidence" to how directly the reference material addresses THIS specific symptom and cause: above 0.8 only when it explicitly documents this exact problem and its fix; 0.5 to 0.7 when it partially covers it; below 0.5 when it lacks specific coverage for it. Do not be confident just because the model is known.
9. Do not claim or invent any IPS log, error code, measurement, or test result that was not provided in the input. If no IPS log was given, do not refer to one. Diagnose only the model named in the problem; do not attribute the fault to a different projector family.
10. IPS LOG: when an "IPS LOG FINDINGS" block is present below, those codes/factors were decoded from the real uploaded log. Write a short "ips_analysis.summary" (1 to 2 sentences) that ties the most important finding to its likely cause and fix, and say whether each is an Error (image projection stops to protect the unit) or a Warning (projection continues with a limitation such as reduced brightness). Use only the findings given; do not invent codes. If no findings block is present, omit ips_analysis entirely.
11. ASK FOR LOG: only when told below that the symptom is sparse and no log was attached, set "info_request" to ask the engineer to attach the IPS Tool log. Otherwise omit info_request.
12. PRESENTATION: write every user-visible field (primary_cause, reasoning, action, ips_analysis.summary, escalation fields) as direct technical findings. NEVER reveal or name the internal knowledge base or how the answer was produced: do not write "wiki", "knowledge base", "reference material", "reference pages", "database", "sources", "documentation", or phrases like "the wiki says" or "per the reference". State the conclusion itself, not where it came from.
14. CONDITION DIAGNOSIS: when a "CONDITION DIAGNOSIS VERDICT" block is present below, it was computed deterministically from the engineer's measured values. Copy its conclusion into primary_cause and order the solutions to match its remedy list; do NOT re-derive, restate as different numbers, or contradict it. If it says reference only, keep confidence at 0.5 or lower and say the measurement must be repeated after full warm-up.
13. ESCALATION DRAFT: fill ONLY these four fields, each grounded in the input, as full sentences (not fragments): "summary" (one line: model + symptom + suspected cause), "symptoms" (what happens, when it started, and how often; note if it began after an update, a part replacement, or a specific event), "suspected_cause" (the failure mechanism), "recommended_next" (a short prioritized list of next actions). Set EVERY OTHER escalation field to "" (empty string). Those remaining fields (serial, firmware_version, error_evidence, references_checked, tried_steps, environment, connection_type, reproduction, diagnostic_logs, impact) are completed automatically afterward from the log and from engineer-input prompts, so do NOT guess or invent values for them. Never put a case number, ticket ID, customer, partner, country, or date in any escalation field. Never mention support levels (no L1/L2/L3 wording).
14. BREVITY (keeps response time low): keep every field tight. "diagnosis.reasoning" is at most 2 sentences; each solution "reasoning" is one sentence; each filled escalation field is one sentence. Do not restate the user's problem and do not pad. A shorter, correct, grounded answer is better than a long one.

NO-DATA EXAMPLE (use this shape when there is no relevant content for this problem):
{{
  "diagnosis": {{
    "primary_cause": "Not enough information to isolate a specific fault for this model and symptom yet.",
    "confidence": 0.0,
    "reasoning": "The reported symptoms or model are not yet covered. Provide the exact model and more symptom detail, or attach the IPS Tool log, for a precise diagnosis."
  }},
  "solutions": [{{
    "rank": 1,
    "difficulty": "easy",
    "cost": "free",
    "action": "Confirm the basics: power source, lamp/light source hours, cooling vents clear, firmware version current.",
    "estimated_time_minutes": 10,
    "estimated_cost_usd": 0.0,
    "reasoning": "Generic first-pass checks to narrow the fault.",
    "wiki_sources": []
  }}],
  "escalation_draft": {{
    "summary": "Insufficient data; escalation drafted from a generic template.",
    "model": "<projector model>",
    "serial": "⟨from the unit label or IPS log⟩",
    "firmware_version": "⟨from the IPS log or the projector menu⟩",
    "symptoms": "<copied from user>",
    "error_evidence": "⟨exact on-screen error codes or messages, with a photo if visible⟩",
    "references_checked": "⟨service manual sections and any TIs you reviewed⟩",
    "tried_steps": "⟨each step you took and its result; note any parts replaced⟩",
    "environment": "⟨end user, OS, network, power, install and usage environment⟩",
    "connection_type": "⟨USB, Ethernet, wireless, or serial⟩",
    "reproduction": "⟨how to reproduce, or note if it is not reproducible on demand⟩",
    "diagnostic_logs": "⟨attach the IPS Tool log, any system or event logs, and a config backup⟩",
    "impact": "⟨number of units affected and severity⟩",
    "suspected_cause": "Not yet determined.",
    "recommended_next": "Engineer follow-up with full diagnostic per service manual."
  }}
}}

Return ONE JSON object with this exact shape and no other text. The first three keys are always required. "ips_analysis" and "info_request" are optional (include them only per rules 10 and 11):
{{
  "diagnosis": {{"primary_cause": str, "confidence": float between 0 and 1, "reasoning": str}},
  "solutions": [{{"rank": int, "difficulty": "easy"|"medium"|"hard", "cost": "free"|"low"|"medium"|"high", "action": str, "estimated_time_minutes": int, "estimated_cost_usd": float, "reasoning": str, "wiki_sources": [str]}}],
  "escalation_draft": {{"summary": str, "model": str, "serial": str, "firmware_version": str, "symptoms": str, "error_evidence": str, "references_checked": str, "tried_steps": str, "environment": str, "connection_type": str, "reproduction": str, "diagnostic_logs": str, "impact": str, "suspected_cause": str, "recommended_next": str}},
  "ips_analysis": {{"summary": str, "findings": [str], "severity": "critical"|"high"|"medium"|"low"|"info"}},
  "info_request": {{"want": "ips_log", "message": str}}
}}
"""


def empty_wiki_response(req: DiagnoseRequest, model_label: Optional[str] = None) -> dict:
    return {
        "diagnosis": {
            "primary_cause": "Not enough information to isolate a specific fault for this model and symptom yet.",
            "confidence": 0.0,
            "reasoning": "The reported model or symptoms are not yet covered. Provide the exact model and more symptom detail, or attach the IPS Tool log, for a precise diagnosis.",
        },
        "solutions": [
            {
                "rank": 1,
                "difficulty": "easy",
                "cost": "free",
                "action": "Confirm power source, light-source hours, cooling vents, and firmware version.",
                "estimated_time_minutes": 10,
                "estimated_cost_usd": 0.0,
                "reasoning": "Generic first-pass checks to narrow the fault.",
                "wiki_sources": [],
            }
        ],
        "escalation_draft": {
            "summary": "Insufficient data; generic template.",
            "model": model_label or req.model or "(unknown)",
            "serial": "⟨from the unit label or IPS log⟩",
            "firmware_version": "⟨from the IPS log or the projector menu⟩",
            "symptoms": req.problem,
            "error_evidence": "⟨exact on-screen error codes or messages, with a photo if visible⟩",
            "references_checked": "⟨service manual sections and any TIs you reviewed⟩",
            "tried_steps": "⟨each step you took and its result; note any parts replaced⟩",
            "environment": "⟨end user, OS, network, power, install and usage environment⟩",
            "connection_type": "⟨USB, Ethernet, wireless, or serial⟩",
            "reproduction": "⟨how to reproduce, or note if it is not reproducible on demand⟩",
            "diagnostic_logs": "⟨attach the IPS Tool log, any system or event logs, and a config backup⟩",
            "impact": "⟨number of units affected and severity⟩",
            "suspected_cause": "Not yet determined.",
            "recommended_next": "Engineer follow-up per service manual.",
        },
    }


def merge_sparse_response(parsed: dict, req: DiagnoseRequest, model_label: Optional[str] = None) -> dict:
    """Fill missing required fields from a stub so small models that emit partial JSON still validate."""
    stub = empty_wiki_response(req, model_label)
    for key, default in stub.items():
        if key not in parsed or not parsed[key]:
            parsed[key] = default
    return parsed


def strip_fabricated_sources(parsed: dict, pages: list[Path], wiki_path: Path) -> dict:
    """Deterministic grounding guard: drop any wiki_sources citation that does not
    correspond to a page we actually retrieved, so a fabricated page name can never
    survive into the audit trail even if the model invents one. wiki_sources is
    internal-only, so filtering aggressively here is safe."""
    valid: set[str] = set()
    for p in pages:
        try:
            rel = p.relative_to(wiki_path).as_posix().lower()
        except Exception:
            rel = p.name.lower()
        valid.update({rel, p.name.lower(), p.stem.lower()})

    def grounded(src) -> bool:
        s = str(src).strip().lower().replace("\\", "/").lstrip("/")
        if not s:
            return False
        return any(s == v or s.endswith(v) or v.endswith(s) or (len(s) > 4 and s in v) for v in valid)

    for sol in parsed.get("solutions", []) or []:
        if isinstance(sol, dict) and isinstance(sol.get("wiki_sources"), list):
            sol["wiki_sources"] = [x for x in sol["wiki_sources"] if grounded(x)]
    return parsed


def _extract_image_b64(raw: Optional[str]) -> Optional[str]:
    """Normalize an uploaded photo to raw base64 (strip a data: URL prefix if present)."""
    if not raw or not isinstance(raw, str):
        return None
    s = raw.strip()
    if s.startswith("data:"):
        comma = s.find(",")
        if comma != -1:
            s = s[comma + 1:]
    return s or None


# Opsec scrub net: the model is told (rule 12) never to name the internal
# knowledge base, but as a last resort we rewrite any meta-reference that leaks
# into a user-visible field. This only rewrites the wording, not the technical
# content (causes, parts, steps are untouched), so the diagnosis is unchanged.
_WIKI_META_RE = re.compile(
    r"\b(?:the\s+|our\s+|this\s+|in\s+the\s+)?"
    r"wiki(?:\s+(?:content|pages?|entry|entries|articles?|data|knowledge\s*base))?\b",
    re.IGNORECASE,
)
_KB_META_RE = re.compile(r"\bknowledge\s*base\b", re.IGNORECASE)


def _is_blank_or_placeholder(v) -> bool:
    """True if an escalation field is empty or still holds an engineer ⟨...⟩ gap,
    so a deterministic value (model/serial/firmware from the log) may fill it."""
    return (not isinstance(v, str)) or (not v.strip()) or ("⟨" in v)


# Canonical engineer-input prompts. The ⟨...⟩ marker is what the UI highlights and
# what copy-to-clipboard turns into [ ] fill-in blanks. These fields can only come
# from the engineer (or the decoded log), so we never let the small model guess them.
ESC_GAPS = {
    "serial": "⟨from the unit label or IPS log⟩",
    "firmware_version": "⟨from the IPS log or the projector menu⟩",
    "error_evidence": "⟨exact on-screen error codes or messages, with a photo if visible⟩",
    "references_checked": "⟨service manual sections and any TIs you reviewed⟩",
    "tried_steps": "⟨each step you took and its result; note any parts replaced⟩",
    "environment": "⟨end user, OS, network, power, install and usage environment⟩",
    "connection_type": "⟨USB, Ethernet, wireless, or serial⟩",
    "reproduction": "⟨how to reproduce, or note if it is not reproducible on demand⟩",
    "diagnostic_logs": "⟨attach the IPS Tool log, any system or event logs, and a config backup⟩",
    "impact": "⟨number of units affected and severity⟩",
}


def _finalize_escalation(esc, *, log_summary, ips_findings, detected_model, has_log) -> None:
    """Deterministically complete the escalation draft so every checklist item is
    present and nothing is fabricated. Engineer-only fields are forced to ⟨...⟩
    gaps (the small model otherwise invents environment/connection/impact and can
    leak internal source paths into references_checked). Fields AKARI can source
    (model, serial, firmware, error evidence) are filled from the decoded log.
    The model keeps only the grounded prose fields: summary, symptoms,
    suspected_cause, recommended_next."""
    if not isinstance(esc, dict):
        return
    # Fields that can ONLY come from the engineer: override whatever the model wrote.
    for k in ("references_checked", "tried_steps", "environment",
              "connection_type", "reproduction", "impact"):
        esc[k] = ESC_GAPS[k]
    # Model identity from detection.
    if detected_model and _is_blank_or_placeholder(esc.get("model")):
        esc["model"] = detected_model
    # Serial + firmware: straight from the decoded log, else an engineer gap.
    serial = (log_summary.get("serial_number") or "").strip() if log_summary else ""
    fw = (log_summary.get("fw_version") or "").strip() if log_summary else ""
    esc["serial"] = serial or ESC_GAPS["serial"]
    esc["firmware_version"] = fw or ESC_GAPS["firmware_version"]
    # Error evidence: decoded codes when the log is notable, else an engineer gap.
    if ips_findings and ips_findings.get("notable"):
        fnds = [f for f in (ips_findings.get("findings") or []) if isinstance(f, str) and f.strip()]
        esc["error_evidence"] = "; ".join(fnds[:3]) if fnds else ESC_GAPS["error_evidence"]
    else:
        esc["error_evidence"] = ESC_GAPS["error_evidence"]
    # Diagnostic logs: reflect whether a log was actually attached.
    if has_log:
        esc["diagnostic_logs"] = "IPS Tool log attached. ⟨add any system or event logs and a config backup⟩"
    else:
        esc["diagnostic_logs"] = ESC_GAPS["diagnostic_logs"]


def _scrub_user_text(s):
    if not isinstance(s, str) or not s:
        return s
    out = _WIKI_META_RE.sub("the reference data", s)
    out = _KB_META_RE.sub("reference data", out)
    out = re.sub(r"\bthe the\b", "the", out, flags=re.IGNORECASE)
    out = re.sub(r"[ \t]{2,}", " ", out).strip()
    return out


def scrub_response_for_user(parsed: dict) -> dict:
    """Strip any internal-knowledge-base mention from every user-visible string
    field, in place. Does not touch wiki_sources (internal/audit, not rendered)
    or the deterministic ips_analysis.findings."""
    d = parsed.get("diagnosis")
    if isinstance(d, dict):
        for k in ("primary_cause", "reasoning"):
            if k in d:
                d[k] = _scrub_user_text(d[k])
    for sol in (parsed.get("solutions") or []):
        if isinstance(sol, dict):
            for k in ("action", "reasoning"):
                if k in sol:
                    sol[k] = _scrub_user_text(sol[k])
    esc = parsed.get("escalation_draft")
    if isinstance(esc, dict):
        # model/serial/firmware are codes; don't run them through the meta-scrub.
        for k in ("summary", "symptoms", "error_evidence", "references_checked",
                  "tried_steps", "environment", "connection_type", "reproduction",
                  "diagnostic_logs", "impact", "suspected_cause", "recommended_next"):
            if k in esc:
                esc[k] = _scrub_user_text(esc[k])
    ia = parsed.get("ips_analysis")
    if isinstance(ia, dict) and ia.get("summary"):
        ia["summary"] = _scrub_user_text(ia["summary"])
    ir = parsed.get("info_request")
    if isinstance(ir, dict) and ir.get("message"):
        ir["message"] = _scrub_user_text(ir["message"])
    return parsed


UI_PATH = PROJECT_ROOT / "ui" / "index.html"
FEEDBACK_UI_PATH = PROJECT_ROOT / "ui" / "feedback.html"
ADMIN_UI_PATH = PROJECT_ROOT / "ui" / "admin.html"
UI_ASSETS_PATH = PROJECT_ROOT / "ui" / "assets"

if UI_ASSETS_PATH.exists():
    app.mount("/assets", StaticFiles(directory=str(UI_ASSETS_PATH)), name="assets")


@app.middleware("http")
async def noindex_admin_paths(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/admin"):
        response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    return response


@app.get("/robots.txt", response_class=PlainTextResponse)
async def robots_txt():
    return "User-agent: *\nDisallow: /admin/\nDisallow: /feedback/\n"


# ---------- PWA (installable Chrome app, same pattern as Action Tracker) ----------
# Manifest and service worker are served from the root so the SW scope is "/".

MANIFEST_PATH = PROJECT_ROOT / "ui" / "manifest.webmanifest"
SW_PATH = PROJECT_ROOT / "ui" / "sw.js"


@app.get("/manifest.webmanifest", include_in_schema=False)
async def pwa_manifest():
    if not MANIFEST_PATH.exists():
        raise HTTPException(status_code=404)
    return FileResponse(MANIFEST_PATH, media_type="application/manifest+json")


@app.get("/sw.js", include_in_schema=False)
async def pwa_service_worker():
    if not SW_PATH.exists():
        raise HTTPException(status_code=404)
    return FileResponse(
        SW_PATH,
        media_type="application/javascript",
        headers={"Cache-Control": "no-cache"},
    )


@app.get("/", response_class=HTMLResponse)
async def root_ui():
    if UI_PATH.exists():
        return FileResponse(UI_PATH, media_type="text/html")
    return HTMLResponse(
        "<h1>AKARI</h1><p>UI not built yet. Use POST /diagnose directly.</p>",
        status_code=200,
    )


@app.get("/feedback/{diagnosis_id}", response_class=HTMLResponse)
async def feedback_page(diagnosis_id: str):
    if FEEDBACK_UI_PATH.exists():
        return FileResponse(FEEDBACK_UI_PATH, media_type="text/html")
    return HTMLResponse(
        "<h1>AKARI</h1><p>Feedback page not built yet.</p>",
        status_code=200,
    )


# ---------- Feedback API ----------

CD_PART_CHOICES = ("", "none", "lsm", "oe", "pop", "lddr", "lmdr", "main_board", "other")


class FeedbackSubmit(BaseModel):
    worked: bool
    what_fixed_it: Optional[str] = None
    notes: Optional[str] = None
    # Phase C outcome loop: which part was actually replaced after a
    # Condition Diagnosis verdict (feeds the accuracy metric).
    cd_part_replaced: Optional[str] = None
    # The client sends these on first submission (from localStorage); ignored on update.
    diagnosis_response: Optional[dict] = None
    problem_text: Optional[str] = None
    depth_tier: Optional[str] = None
    wiki_pages_used: Optional[list] = None
    visual_analysis: Optional[str] = None
    diagnosis_ts: Optional[str] = None


@app.get("/api/feedback/{diagnosis_id}")
async def get_feedback_state(diagnosis_id: str, request: Request):
    row = db.get_feedback(diagnosis_id)
    if not row:
        return {"status": "not_submitted", "diagnosis_id": diagnosis_id}
    if row.get("deleted"):
        return {"status": "deleted", "diagnosis_id": diagnosis_id}
    if db.is_public_link_expired(row["diagnosis_ts"]):
        return {
            "status": "expired",
            "diagnosis_id": diagnosis_id,
            "message": "This feedback window has closed (90 days after diagnosis).",
        }
    hashed_caller = _hashed_user_from_request(request)
    if hashed_caller and row["hashed_user"] != hashed_caller:
        raise HTTPException(status_code=403, detail="Not the original user")
    return {
        "status": "submitted",
        "diagnosis_id": diagnosis_id,
        "worked": bool(row["worked"]),
        "what_fixed_it": row["what_fixed_it"],
        "notes": row["notes"],
        "diagnosis_ts": row["diagnosis_ts"],
        "feedback_ts": row["feedback_ts"],
        "last_updated": row["last_updated"],
        "diagnosis_response": json.loads(row["diagnosis_response"]) if row["diagnosis_response"] else None,
        "problem_text": row["problem_text"],
        "updates": db.get_feedback_updates(diagnosis_id),
    }


@app.post("/api/feedback/{diagnosis_id}")
async def submit_feedback(diagnosis_id: str, body: FeedbackSubmit, request: Request):
    hashed_caller = _hashed_user_from_request(request)
    if not hashed_caller:
        raise HTTPException(
            status_code=401,
            detail="No authenticated user (auth header missing). Browser flows require email-OTP login.",
        )

    existing = db.get_feedback(diagnosis_id)
    if existing:
        # Initial feedback is immutable. Further input goes through the append
        # endpoint, never an edit. Direct the caller there.
        raise HTTPException(
            status_code=409,
            detail="Feedback already submitted for this diagnosis. Add an update instead.",
        )

    # First-time submission. Client MUST supply the diagnosis context from localStorage.
    if not body.diagnosis_response or not body.problem_text or not body.diagnosis_ts:
        raise HTTPException(
            status_code=400,
            detail=(
                "First-time feedback for this diagnosis requires the diagnosis context. "
                "If you reached this page on a different device, return to the device "
                "where the diagnosis was issued and submit feedback there once."
            ),
        )
    if db.is_public_link_expired(body.diagnosis_ts):
        raise HTTPException(status_code=410, detail="Feedback window closed")

    result = db.upsert_feedback(
        diagnosis_id=diagnosis_id,
        problem_text=body.problem_text,
        diagnosis_response=body.diagnosis_response,
        depth_tier=body.depth_tier,
        wiki_pages_used=body.wiki_pages_used or [],
        visual_analysis=body.visual_analysis,
        hashed_user=hashed_caller,
        diagnosis_ts=body.diagnosis_ts,
        worked=1 if body.worked else 0,
        what_fixed_it=(body.what_fixed_it or "").strip()[:4000] or None,
        notes=(body.notes or "").strip()[:4000] or None,
        cd_verdict=(((body.diagnosis_response or {}).get("cd_analysis") or {}).get("verdict") or None),
        cd_part_replaced=(body.cd_part_replaced or "").strip().lower() if (body.cd_part_replaced or "").strip().lower() in CD_PART_CHOICES else None,
    )
    # E1: confirmation + summary, right after the initial submission.
    _fire_email(
        diagnosis_id=diagnosis_id, hashed_user=hashed_caller, kind="confirmation",
        **dict(zip(
            ("subject", "html", "text"),
            emailer.confirmation_email(
                diagnosis_id=diagnosis_id, diagnosis_response=body.diagnosis_response,
                problem_text=body.problem_text, diagnosis_ts=body.diagnosis_ts,
                worked=body.worked,
            ),
        )),
    )
    return {"status": "submitted", "diagnosis_id": diagnosis_id, "feedback_ts": result.get("feedback_ts")}


class FeedbackUpdate(BaseModel):
    text: str


@app.post("/api/feedback/{diagnosis_id}/update")
async def append_feedback(diagnosis_id: str, body: FeedbackUpdate, request: Request):
    """Append an additional note. Does NOT touch the immutable initial feedback."""
    hashed_caller = _hashed_user_from_request(request)
    if not hashed_caller:
        raise HTTPException(status_code=401, detail="Not authenticated")
    existing = db.get_feedback(diagnosis_id)
    if not existing:
        raise HTTPException(status_code=404, detail="No initial feedback to update")
    if existing["hashed_user"] != hashed_caller:
        raise HTTPException(status_code=403, detail="Not the original user")
    if existing.get("deleted"):
        raise HTTPException(status_code=410, detail="This feedback record was removed")
    if db.is_public_link_expired(existing["diagnosis_ts"]):
        raise HTTPException(status_code=410, detail="Feedback window closed")
    text = (body.text or "").strip()[:4000]
    if not text:
        raise HTTPException(status_code=400, detail="Update text is empty")
    db.append_feedback_update(diagnosis_id=diagnosis_id, hashed_user=hashed_caller, text=text)
    # Light receipt for the appended update.
    _fire_email(
        diagnosis_id=diagnosis_id, hashed_user=hashed_caller, kind="update_receipt",
        **dict(zip(
            ("subject", "html", "text"),
            emailer.update_receipt_email(
                diagnosis_id=diagnosis_id, update_text=text,
                diagnosis_ts=existing["diagnosis_ts"],
            ),
        )),
    )
    return {"status": "update_added", "diagnosis_id": diagnosis_id}


@app.get("/admin/feedback/{diagnosis_id}/thread")
async def admin_feedback_thread(diagnosis_id: str):
    """Admin-only: initial feedback + the append-only update thread + email log."""
    row = db.get_feedback(diagnosis_id)
    if not row:
        raise HTTPException(status_code=404, detail="No feedback record")
    return {
        "diagnosis_id": diagnosis_id,
        "worked": bool(row["worked"]),
        "what_fixed_it": row["what_fixed_it"],
        "notes": row["notes"],
        "feedback_ts": row["feedback_ts"],
        "last_updated": row["last_updated"],
        "deleted": bool(row["deleted"]),
        "updates": db.get_feedback_updates(diagnosis_id),
    }


@app.delete("/admin/feedback/{diagnosis_id}")
async def admin_delete_feedback(diagnosis_id: str):
    """Admin-only soft delete (behind the /admin reverse-proxy access policy).
    Users can no longer remove feedback; this is the escape hatch for mistakes."""
    existing = db.get_feedback(diagnosis_id)
    if not existing:
        raise HTTPException(status_code=404, detail="No feedback record")
    db.soft_delete_feedback(diagnosis_id)
    return {"status": "deleted", "diagnosis_id": diagnosis_id}


# ---------- Admin: monitor dashboard ----------

@app.get("/admin/", response_class=HTMLResponse)
@app.get("/admin", response_class=HTMLResponse)
async def admin_ui():
    if ADMIN_UI_PATH.exists():
        return FileResponse(ADMIN_UI_PATH, media_type="text/html")
    return HTMLResponse("<h1>Admin UI not built yet</h1>", status_code=200)


@app.get("/admin/metrics/overview")
async def admin_overview():
    return db.metrics_overview()


@app.get("/admin/metrics/activity")
async def admin_activity(window_hours: int = 24):
    return db.metrics_activity(window_hours=window_hours)


@app.get("/admin/metrics/performance")
async def admin_performance(window_hours: int = 24):
    return db.metrics_performance(window_hours=window_hours)


@app.get("/admin/metrics/quality")
async def admin_quality(window_hours: int = 24):
    return db.metrics_quality(window_hours=window_hours)


@app.get("/admin/metrics/resolution")
async def admin_resolution(window_hours: Optional[int] = None):
    return db.metrics_resolution_kpi(window_hours=window_hours)


@app.get("/admin/metrics/cd-outcomes")
async def admin_cd_outcomes():
    """Condition Diagnosis accuracy: verdict vs the part the engineer actually replaced."""
    return db.metrics_cd_outcomes()


@app.get("/admin/metrics/tokens")
async def admin_tokens():
    return db.metrics_tokens()


@app.get("/admin/system")
async def admin_system():
    snap = await asyncio.to_thread(sampler.read_system_snapshot)
    # Include the GPU power-cap watcher state so the admin dashboard can show a
    # live throttle/failover indicator alongside the live load metrics.
    snap["gpu_watch"] = gpu_watch.snapshot()
    return snap


@app.get("/admin/diagnoses")
async def admin_diagnoses(limit: int = 50, offset: int = 0, depth: Optional[str] = None):
    # Cap raised so the admin Diagnoses table can pull the full history in one
    # fetch and do hide/filter/sort/paginate client-side (admin-only, read-only).
    limit = max(1, min(5000, limit))
    offset = max(0, offset)
    return db.list_diagnoses(limit=limit, offset=offset, depth=depth)


@app.get("/admin/diagnoses/{diagnosis_id}")
async def admin_diagnosis_detail(diagnosis_id: str):
    detail = db.get_diagnosis_detail(diagnosis_id)
    if not detail:
        raise HTTPException(status_code=404, detail="No such diagnosis_id")
    return detail


# ---------- Admin: demo mode ----------

class DemoToggle(BaseModel):
    enabled: bool


class DemoApprove(BaseModel):
    diagnosis_id: str


@app.get("/admin/demo")
async def admin_demo_status():
    return {
        "enabled": db.demo_mode_enabled(),
        "count": db.demo_cache_count(),
        "items": db.demo_cache_list(),
    }


@app.post("/admin/demo/toggle")
async def admin_demo_toggle(body: DemoToggle):
    db.demo_mode_set(body.enabled)
    return {"enabled": db.demo_mode_enabled(), "count": db.demo_cache_count()}


@app.post("/admin/demo/approve")
async def admin_demo_approve(body: DemoApprove, request: Request):
    approved_by = request.headers.get(settings.auth_email_header)
    result = db.demo_cache_approve(body.diagnosis_id, approved_by=approved_by)
    if result is None:
        raise HTTPException(
            status_code=404,
            detail="Diagnosis not found, or it has no stored response text to stage.",
        )
    return {"ok": True, "input_hash": result["input_hash"], "count": db.demo_cache_count()}


@app.delete("/admin/demo/{input_hash}")
async def admin_demo_delete(input_hash: str):
    return {"deleted": db.demo_cache_delete(input_hash), "count": db.demo_cache_count()}


# ---------- Admin: wiki browser + editor ----------

class WikiSave(BaseModel):
    content: str


@app.get("/admin/wiki/tree")
async def admin_wiki_tree():
    return wiki_ops.list_wiki_tree()


@app.get("/admin/wiki/page")
async def admin_wiki_page(path: str):
    try:
        p = wiki_ops.get_page(path)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not p:
        raise HTTPException(status_code=404, detail="Page not found")
    return p


@app.post("/admin/wiki/page")
async def admin_wiki_save(path: str, body: WikiSave, request: Request):
    hashed = _hashed_user_from_request(request)
    try:
        return wiki_ops.save_page(path, body.content, hashed_user=hashed)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/admin/wiki/page")
async def admin_wiki_delete(path: str, request: Request):
    hashed = _hashed_user_from_request(request)
    try:
        result = wiki_ops.delete_page(path, hashed_user=hashed)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not result.get("deleted"):
        raise HTTPException(status_code=404, detail="Page not found")
    return result


@app.get("/admin/wiki/search")
async def admin_wiki_search(q: str, mode: str = "literal"):
    if mode not in ("literal", "regex"):
        raise HTTPException(status_code=400, detail="mode must be 'literal' or 'regex'")
    return {"query": q, "mode": mode, "results": wiki_ops.search_wiki(q, mode=mode)}


@app.get("/admin/wiki/history")
async def admin_wiki_history(path: str):
    return {"path": path, "entries": wiki_ops.get_history(path)}


@app.get("/admin/wiki/commit")
async def admin_wiki_at_commit(path: str, commit: str):
    p = wiki_ops.get_page_at_commit(path, commit)
    if not p:
        raise HTTPException(status_code=404, detail="Page at commit not found")
    return p


@app.get("/admin/wiki/cited-by")
async def admin_wiki_cited_by(path: str, limit: int = 50):
    limit = max(1, min(200, limit))
    return {"path": path, "citations": wiki_ops.get_citations(path, limit=limit)}


@app.get("/admin/wiki/lint")
async def admin_wiki_lint(format: str = "json"):
    report = wiki_ops.lint_wiki()
    if format == "md":
        md = wiki_ops.render_lint_markdown(report)
        fname = f"akari-lint-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.md"
        return Response(
            md,
            media_type="text/markdown",
            headers={
                "Content-Disposition": f'attachment; filename="{fname}"',
                "X-Robots-Tag": "noindex, nofollow, noarchive",
            },
        )
    return report


@app.get("/admin/wiki/gaps")
async def admin_wiki_gaps(format: str = "json"):
    report = wiki_ops.gap_analysis()
    if format == "md":
        md = wiki_ops.render_gaps_markdown(report)
        fname = f"akari-gaps-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.md"
        return Response(
            md,
            media_type="text/markdown",
            headers={
                "Content-Disposition": f'attachment; filename="{fname}"',
                "X-Robots-Tag": "noindex, nofollow, noarchive",
            },
        )
    return report


# ---------- Admin: knowledge gaps (usage-driven) ----------

@app.get("/admin/knowledge-gaps")
async def admin_knowledge_gaps(window_hours: Optional[int] = None, include_addressed: bool = False):
    return db.knowledge_gaps(window_hours=window_hours, include_addressed=include_addressed)


class GapStatus(BaseModel):
    gap_key: str
    status: str
    note: Optional[str] = None


@app.post("/admin/knowledge-gaps/status")
async def admin_set_knowledge_gap_status(body: GapStatus, request: Request):
    hashed = _hashed_user_from_request(request)
    try:
        return db.set_knowledge_gap_status(body.gap_key, body.status, note=body.note, hashed_user=hashed)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ---------- Admin: ingestion pipeline ----------

ALLOWED_SOURCE_TYPES = {"manuals", "tis", "msd", "depot2", "web", "other"}
ALLOWED_AUTHORITIES = {"high", "medium", "low", ""}
MAX_UPLOAD_BYTES = 100 * 1024 * 1024  # 100 MB


def _run_ingest_pipeline_sync(source_id: str, file_path: Path, source_meta: dict) -> None:
    """Sync pipeline: extract then draft. Runs in a thread (BackgroundTasks via asyncio.to_thread)."""
    try:
        extract_result = extractor.extract_source(file_path, source_id, source_meta)
        if not extract_result["ok"]:
            db.update_source_status(
                source_id, "extraction_failed",
                status_detail=extract_result["error"] or "unknown extractor error",
            )
            print(f"[ingest] {source_id} extraction failed: {extract_result['error']}", file=sys.stderr)
            return
        db.update_source_status(source_id, "extracted", digest_path=extract_result["digest_path"])

        digest_md = Path(extract_result["digest_path"]).read_text(encoding="utf-8", errors="replace")
        draft_result = drafter.draft_pages_from_digest(digest_md, source_meta)
        if not draft_result["ok"]:
            db.update_source_status(
                source_id, "drafting_failed",
                status_detail=draft_result["error"] or "unknown drafter error",
            )
            print(f"[ingest] {source_id} drafting failed: {draft_result['error']}", file=sys.stderr)
            return

        draft_dir = drafter.write_drafts_to_disk(source_id, draft_result["pages"])
        rel_draft_dir = "wiki/_drafts/" + source_id
        db.update_source_status(
            source_id, "drafted",
            draft_dir=rel_draft_dir,
            status_detail=(draft_result.get("reasoning") or "")[:500],
        )
        print(f"[ingest] {source_id} drafted {len(draft_result['pages'])} pages → {rel_draft_dir}", file=sys.stderr)
    except Exception as e:
        db.update_source_status(source_id, "drafting_failed", status_detail=f"pipeline crashed: {type(e).__name__}: {e}")
        print(f"[ingest] {source_id} pipeline crashed: {e}", file=sys.stderr)


async def _kick_ingest_pipeline(source_id: str, file_path: Path, source_meta: dict) -> None:
    await asyncio.to_thread(_run_ingest_pipeline_sync, source_id, file_path, source_meta)


@app.post("/admin/ingest/upload")
async def admin_ingest_upload(
    request: Request,
    file: UploadFile = File(...),
    source_type: str = Form(...),
    authority: str = Form(""),
    notes: str = Form(""),
):
    if source_type not in ALLOWED_SOURCE_TYPES:
        raise HTTPException(status_code=400, detail=f"source_type must be one of {sorted(ALLOWED_SOURCE_TYPES)}")
    if authority and authority not in ALLOWED_AUTHORITIES:
        raise HTTPException(status_code=400, detail=f"authority must be one of {sorted(a for a in ALLOWED_AUTHORITIES if a)}")
    if not file.filename:
        raise HTTPException(status_code=400, detail="filename required")

    contents = await file.read()
    if len(contents) == 0:
        raise HTTPException(status_code=400, detail="empty file")
    if len(contents) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=f"file exceeds {MAX_UPLOAD_BYTES // (1024*1024)}MB limit")

    file_hash = hashlib.sha256(contents).hexdigest()
    existing = db.find_source_by_hash(file_hash)
    if existing:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "duplicate_file",
                "message": (
                    f"This file was already ingested as source {existing['source_id']} "
                    f"on {existing['uploaded_at']} (original name: {existing['original_name']}, "
                    f"status: {existing['status']})."
                ),
                "existing_source": existing,
            },
        )

    # Persist to raw/<source_type>/<original_name> (disambiguate on collision with a hash suffix).
    safe_name = re.sub(r"[^A-Za-z0-9._-]", "-", file.filename) or "uploaded.bin"
    target_dir = PROJECT_ROOT / "raw" / source_type
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / safe_name
    if target.exists():
        stem, suffix = target.stem, target.suffix
        target = target_dir / f"{stem}-{file_hash[:8]}{suffix}"
    target.write_bytes(contents)

    source_id = uuid.uuid4().hex
    hashed_user = _hashed_user_from_request(request)
    rel_path = "raw/" + source_type + "/" + target.name

    db.insert_source(
        source_id=source_id,
        uploader=hashed_user,
        original_name=file.filename,
        file_hash=file_hash,
        file_path=rel_path,
        source_type=source_type,
        authority=authority or None,
        notes=notes or None,
    )

    source_meta = {
        "source_id": source_id,
        "source_type": source_type,
        "authority": authority or None,
        "notes": notes or None,
        "original_name": file.filename,
    }
    asyncio.create_task(_kick_ingest_pipeline(source_id, target, source_meta))

    return {
        "source_id": source_id,
        "status": "uploaded",
        "file_path": rel_path,
        "file_hash": file_hash,
        "message": "Upload received; extraction and drafting are running in the background.",
    }


@app.get("/admin/ingest/sources")
async def admin_ingest_list(status: Optional[str] = None, limit: int = 200):
    return {
        "sources": db.list_sources(status=status, limit=max(1, min(500, limit))),
        "failed": db.list_failed_sources(),
    }


@app.get("/admin/ingest/source/{source_id}")
async def admin_ingest_source(source_id: str):
    src = db.get_source(source_id)
    if not src:
        raise HTTPException(status_code=404, detail="source not found")

    # Augment with the draft manifest + each draft file's parsed content if drafted
    manifest = drafter.read_draft_manifest(source_id)
    src["draft_manifest"] = manifest
    drafts: list[dict] = []
    if manifest:
        for entry in manifest:
            draft_rel = entry["draft_path"]
            full_path = PROJECT_ROOT / draft_rel
            if full_path.exists():
                raw = full_path.read_text(encoding="utf-8", errors="replace")
                fm, body = wiki_ops.parse_frontmatter(raw)
                drafts.append({
                    "draft_path": draft_rel,
                    "proposed_destination": entry["proposed_destination"],
                    "frontmatter": fm,
                    "body": body,
                    "size": full_path.stat().st_size,
                })
    src["drafts"] = drafts
    return src


class ApprovePageSelection(BaseModel):
    draft_path: str
    destination: str
    include: bool = True


class ApproveRequest(BaseModel):
    selections: list[ApprovePageSelection]


@app.post("/admin/ingest/source/{source_id}/approve")
async def admin_ingest_approve(source_id: str, body: ApproveRequest, request: Request):
    src = db.get_source(source_id)
    if not src:
        raise HTTPException(status_code=404, detail="source not found")
    if src["status"] != "drafted":
        raise HTTPException(status_code=400, detail=f"source must be in 'drafted' status (current: {src['status']})")

    hashed = _hashed_user_from_request(request)
    approved: list[dict] = []

    for sel in body.selections:
        if not sel.include:
            continue

        # Validate draft path
        if not sel.draft_path.startswith(f"wiki/_drafts/{source_id}/") or not sel.draft_path.endswith(".md"):
            raise HTTPException(status_code=400, detail=f"invalid draft_path: {sel.draft_path}")
        draft_full = (PROJECT_ROOT / sel.draft_path).resolve()
        if not draft_full.exists():
            raise HTTPException(status_code=400, detail=f"draft file not found: {sel.draft_path}")
        if not str(draft_full).startswith(str((PROJECT_ROOT / "wiki" / "_drafts").resolve())):
            raise HTTPException(status_code=400, detail="draft_path escapes _drafts/")

        # Validate destination
        dest_rel = sel.destination.strip()
        if not dest_rel.startswith("wiki/") or not dest_rel.endswith(".md"):
            raise HTTPException(status_code=400, detail=f"destination must be wiki/...md: {dest_rel}")
        if "_drafts" in dest_rel.split("/"):
            raise HTTPException(status_code=400, detail="destination cannot be inside _drafts/")
        if ".." in dest_rel.split("/"):
            raise HTTPException(status_code=400, detail="path traversal blocked")
        dest_full = (PROJECT_ROOT / dest_rel).resolve()
        if not str(dest_full).startswith(str((PROJECT_ROOT / "wiki").resolve())):
            raise HTTPException(status_code=400, detail="destination escapes wiki/")
        if dest_full.exists():
            raise HTTPException(status_code=409, detail=f"destination already exists: {dest_rel}")

        # Read draft, write to destination
        content = draft_full.read_text(encoding="utf-8")
        dest_full.parent.mkdir(parents=True, exist_ok=True)
        dest_full.write_text(content, encoding="utf-8")

        # Git commit and history row
        short = (hashed or "admin")[:10]
        msg = f"wiki: ingest {dest_rel} from source {source_id[:8]} by {short}"
        commit = wiki_ops._git_commit(dest_rel, msg)
        db.write_page_history(
            path=dest_rel,
            git_commit_id=commit or "unknown",
            hashed_user=hashed,
            change_type="created",
            origin="ingested",
            source_id=source_id,
            diff_summary=f"Ingested from source {source_id[:8]} ({src['original_name']})",
        )
        approved.append({"path": dest_rel, "commit": commit})

    # Clean up the draft directory and mark source approved
    draft_dir = PROJECT_ROOT / "wiki" / "_drafts" / source_id
    if draft_dir.exists():
        shutil.rmtree(draft_dir)
    db.update_source_status(
        source_id, "approved",
        status_detail=f"{len(approved)} page(s) approved",
    )
    return {"approved_count": len(approved), "files": approved}


@app.post("/admin/ingest/source/{source_id}/reject")
async def admin_ingest_reject(source_id: str, request: Request):
    src = db.get_source(source_id)
    if not src:
        raise HTTPException(status_code=404, detail="source not found")
    if src["status"] not in ("drafted", "drafting_failed", "extraction_failed"):
        raise HTTPException(
            status_code=400,
            detail=f"source must be in a reviewable status (current: {src['status']})",
        )

    draft_dir = PROJECT_ROOT / "wiki" / "_drafts" / source_id
    if draft_dir.exists():
        shutil.rmtree(draft_dir)
    db.update_source_status(source_id, "rejected", status_detail="rejected by admin")
    return {"status": "rejected", "source_id": source_id}


@app.get("/admin/export/feedback.csv")
async def admin_export_feedback_csv():
    import csv, io
    rows = db.export_feedback_rows()
    cols = [
        "diagnosis_id", "diagnosis_ts", "feedback_ts", "last_updated", "depth_tier",
        "hashed_user", "worked", "what_fixed_it", "notes", "deleted",
    ]

    def gen():
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=cols)
        writer.writeheader()
        yield buf.getvalue()
        buf.seek(0); buf.truncate(0)
        for r in rows:
            writer.writerow({k: r.get(k, "") for k in cols})
            yield buf.getvalue()
            buf.seek(0); buf.truncate(0)

    fname = f"akari-feedback-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.csv"
    return StreamingResponse(
        gen(),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{fname}"',
            "X-Robots-Tag": "noindex, nofollow, noarchive",
        },
    )


import os as _os_dbg
_DEBUG_PID = _os_dbg.getpid()


@app.get("/health")
async def health():
    # Public liveness probe. Reachable by any authenticated user, so it stays
    # opaque on purpose: status plus the A/B/C/none serving code only. No model
    # names, host, or backend detail here. Rich diagnostics live at /admin/health.
    backends = await inference.backends_status(settings)
    serving = backends["serving"]
    return {"status": "ok" if serving != "none" else "degraded", "serving": serving}


# Self-contained dark "sci-fi" status dashboard for /admin/health. Vanilla JS,
# no deps. Fetches its own data from /admin/health?format=json and refreshes
# every 5s. Admin-only endpoint, so backend/model detail is allowed here.
ADMIN_HEALTH_HTML = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow"><title>AKARI · System Status</title>
<style>
  :root{--bg:#070b14;--panel:#0f1626;--panel2:#0b1120;--border:#1d2942;--txt:#cdd6e8;
    --muted:#6b7794;--mono:"SF Mono",Consolas,"Liberation Mono",monospace;
    --ok:#2ee6a6;--amber:#ffb02e;--red:#ff4d5e;--blue:#3b82f6;}
  *{box-sizing:border-box}
  body{margin:0;background-color:var(--bg);background-image:radial-gradient(1200px 600px at 50% -10%,rgba(46,230,166,0.07),transparent 60%);
    color:var(--txt);font-family:var(--mono);min-height:100vh;padding:30px 16px}
  .grid-bg{position:fixed;inset:0;z-index:0;opacity:.22;pointer-events:none;
    background-image:linear-gradient(rgba(59,130,246,.07) 1px,transparent 1px),linear-gradient(90deg,rgba(59,130,246,.07) 1px,transparent 1px);
    background-size:40px 40px}
  .wrap{position:relative;z-index:1;max-width:780px;margin:0 auto}
  .head{display:flex;align-items:center;gap:14px;padding:18px 22px;border:1px solid var(--border);
    border-radius:14px;background:linear-gradient(180deg,var(--panel),var(--panel2));margin-bottom:14px}
  .dot{width:12px;height:12px;border-radius:50%;flex:none;display:inline-block}
  .dot.ok{background:var(--ok);box-shadow:0 0 10px var(--ok)}
  .dot.amber{background:var(--amber);box-shadow:0 0 10px var(--amber)}
  .dot.red{background:var(--red);box-shadow:0 0 10px var(--red)}
  .dot.pulse{animation:pulse 2.4s infinite}
  @keyframes pulse{0%{opacity:1}50%{opacity:.35}100%{opacity:1}}
  .title{font-size:12px;letter-spacing:3px;color:var(--muted)}
  .state{font-size:22px;font-weight:700;letter-spacing:2px;margin-top:2px}
  .tier{margin-left:auto;text-align:right;font-size:11px;letter-spacing:2px;color:var(--muted)}
  .tier b{display:block;font-size:20px;letter-spacing:3px;color:var(--txt)}
  .cards{display:grid;grid-template-columns:1fr 1fr;gap:12px}
  .card{border:1px solid var(--border);border-radius:12px;background:var(--panel);padding:14px 16px}
  .card.wide{grid-column:1 / -1}
  .lbl{font-size:10px;letter-spacing:2px;color:var(--muted);margin-bottom:10px}
  .row{display:flex;align-items:center;gap:10px;padding:5px 0;font-size:13px}
  .row .v{margin-left:auto;color:var(--muted);text-align:right}
  .big{font-size:18px;font-weight:700;letter-spacing:1px}
  .bar{height:8px;border-radius:6px;background:#16203a;overflow:hidden;margin:8px 0 4px}
  .bar>i{display:block;height:100%;background:linear-gradient(90deg,var(--blue),var(--ok));transition:width .4s}
  .chips{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}
  .chip{font-size:11px;color:var(--muted);border:1px solid var(--border);border-radius:999px;padding:3px 9px}
  .foot{margin-top:14px;text-align:center;color:var(--muted);font-size:11px;letter-spacing:1px}
  .err{color:var(--red)}
  @media(max-width:620px){.cards{grid-template-columns:1fr}}
</style></head>
<body><div class="grid-bg"></div>
<div class="wrap" id="app"><div class="foot">linking…</div></div>
<script>
function dot(s){return '<span class="dot '+s+'"></span>';}
function esc(x){return String(x==null?'':x).replace(/[&<>]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;'}[c];});}
var SRC_LABEL={A:'PRIMARY NODE',B:'BACKUP NODE'};
async function tick(){
  var d;
  try{ var r=await fetch('/admin/health?format=json',{headers:{'accept':'application/json'},cache:'no-store'}); d=await r.json(); }
  catch(e){ render({_offline:true}); return; }
  render(d);
}
function render(d){
  var app=document.getElementById('app');
  if(d._offline){ app.innerHTML='<div class="head">'+dot('red pulse')+'<div><div class="title">AKARI · SYSTEM STATUS</div><div class="state err">UNREACHABLE</div></div></div>'; return; }
  var ok=d.status==='ok', serving=d.serving||'none';
  var gw=d.gpu_watch||{}, last=gw.last||{};
  var draw=last.power_draw_w, lim=last.power_limit_w;
  var pct=(draw!=null&&lim)?Math.min(100,Math.round(draw/lim*100)):0;
  var gpuState=!gw.available?'amber':(gw.degraded===true?'red':'ok');
  var gpuTxt=!gw.available?'n/a':(gw.degraded===true?'FAILOVER':'nominal');
  var sources=(d.backends&&d.backends.sources)||[];
  var models=d.models_available||[];
  var nodes=sources.map(function(s){return '<div class="row">'+dot(s.alive?'ok':'red')+'<span>'+esc(SRC_LABEL[s.code]||s.code)+'</span><span class="v">'+esc(s.host)+'</span></div>';}).join('');
  app.innerHTML=
   '<div class="head">'+dot((ok?'ok':'red')+' pulse')+
     '<div><div class="title">AKARI · SYSTEM STATUS</div><div class="state">'+(ok?'SYSTEM ONLINE':'DEGRADED')+'</div></div>'+
     '<div class="tier">SERVING<b>TIER '+esc(serving==='none'?'—':serving)+'</b></div></div>'+
   '<div class="cards">'+
     '<div class="card"><div class="lbl">INFERENCE NODES</div>'+nodes+'</div>'+
     '<div class="card"><div class="lbl">GPU</div>'+
       '<div class="row">'+dot(gpuState)+'<span class="big">'+esc(last.pstate||'?')+'</span><span class="v">'+esc(gpuTxt)+'</span></div>'+
       '<div class="row"><span>power draw</span><span class="v">'+(draw!=null?esc(draw):'?')+' / '+(lim?esc(lim):'?')+' W</span></div>'+
       '<div class="bar"><i style="width:'+pct+'%"></i></div>'+
       '<div class="row"><span>temp</span><span class="v">'+(last.temp_c!=null?esc(last.temp_c)+'°C':'?')+'</span></div>'+
       '<div class="row"><span>failover episodes</span><span class="v">'+esc(gw.episodes!=null?gw.episodes:'?')+'</span></div>'+
     '</div>'+
     '<div class="card"><div class="lbl">RESPONSE DEPTH</div>'+
       '<div class="row">'+dot('ok')+'<span>standard</span><span class="v">'+esc(d.model_fast||'?')+'</span></div>'+
       '<div class="row">'+dot('ok')+'<span>deep</span><span class="v">'+esc(d.model_deep||'?')+'</span></div>'+
     '</div>'+
     '<div class="card"><div class="lbl">MODELS LOADED · '+models.length+'</div><div class="chips">'+
       (models.length?models.map(function(m){return '<span class="chip">'+esc(m)+'</span>';}).join(''):'<span class="chip">none</span>')+
       '</div>'+(d.error?'<div class="row err" style="margin-top:8px">'+esc(d.error)+'</div>':'')+'</div>'+
   '</div>'+
   '<div class="foot">node pid '+esc(d.debug_pid)+' · auto-refresh 5s · '+new Date().toLocaleTimeString()+'</div>';
}
tick(); setInterval(tick,5000);
</script></body></html>"""


@app.get("/admin/health")
async def admin_health(request: Request, format: Optional[str] = None):
    # Admin-only via the reverse-proxy /admin policy (+ noindex middleware).
    # Safe to expose model names, host, and backend detail here.
    backends = await inference.backends_status(settings)
    out = {
        "status": "ok" if backends["serving"] != "none" else "degraded",
        "serving": backends["serving"],
        "backends": backends,
        "gpu_watch": gpu_watch.snapshot(),
        "ollama_host": settings.ollama_host,
        "model_fast": settings.model_fast,
        "model_deep": settings.model_deep,
        "debug_pid": _DEBUG_PID,
    }
    try:
        resp = await ollama.list()
        out["models_available"] = [m.model for m in resp.models]
    except Exception as e:
        out["models_available"] = []
        out["error"] = str(e)
    # Browser navigation gets the graphical dashboard; scripts/curl and an
    # explicit ?format=json still get raw JSON (the dashboard itself fetches
    # ?format=json). Keeps every existing JSON consumer working.
    if format != "json" and "text/html" in request.headers.get("accept", ""):
        return HTMLResponse(ADMIN_HEALTH_HTML)
    return out


@app.get("/stats")
async def stats():
    if not settings.wiki_path.exists():
        return {"wiki_exists": False, "wiki_path": str(settings.wiki_path)}

    pages = [p for p in sorted(settings.wiki_path.rglob("*.md")) if "_drafts" not in p.parts]
    by_dir: dict[str, int] = {}
    for p in pages:
        rel = p.relative_to(settings.wiki_path).parent.as_posix() or "(root)"
        by_dir[rel] = by_dir.get(rel, 0) + 1

    return {
        "wiki_exists": True,
        "wiki_path": str(settings.wiki_path),
        "total_pages": len(pages),
        "pages_by_dir": by_dir,
    }


class DiagnoseAck(BaseModel):
    diagnosis_id: str
    status: str = "pending"


# In-memory job registry. Cleared on process restart — a restart loses
# pending requests, which is acceptable since restart would have killed
# the original HTTP connection anyway. Completed jobs are kept for
# JOB_TTL_SECONDS so a slow poller can still retrieve results.
_diagnose_jobs: dict[str, dict] = {}
_JOB_TTL_SECONDS = 3600


def _purge_old_diagnose_jobs() -> None:
    now = time.time()
    stale = [
        jid for jid, job in _diagnose_jobs.items()
        if job["status"] != "pending"
        and (now - job.get("finished_wall", now)) > _JOB_TTL_SECONDS
    ]
    for jid in stale:
        _diagnose_jobs.pop(jid, None)


@app.post("/diagnose")
async def diagnose(req: DiagnoseRequest, request: Request) -> DiagnoseAck:
    # Inference can take 60-200s on the RTX 3050 with a 46k-token wiki prompt;
    # The reverse proxy caps HTTP requests at ~100s, so we return an id
    # immediately and let the client poll GET /diagnose/{id}.
    _purge_old_diagnose_jobs()
    diagnosis_id = uuid.uuid4().hex
    hashed_user = _hashed_user_from_request(request)
    head_commit = db.git_head_commit(PROJECT_ROOT)
    _diagnose_jobs[diagnosis_id] = {
        "status": "pending",
        "started_at": time.perf_counter(),
        "started_wall": time.time(),
        "finished_wall": None,
        "result": None,
        "error": None,
        # Phase-progress fields surfaced by the polling endpoint and the
        # frontend's step list. Updated as _run_diagnose advances through
        # the pipeline: queued → detecting → consulting → analyzing → drafting.
        "current_step": "queued",
        "progress": {
            "detected_model": None,
            "pages_count": None,
        },
    }
    # Demo mode: serve a pre-staged answer instantly when one matches; otherwise
    # fall through to live inference (a non-staged query still runs normally).
    if db.demo_mode_enabled():
        try:
            cached = db.demo_cache_get(db.demo_cache_key(req.problem, req.depth_tier))
        except Exception:
            cached = None
        if cached:
            try:
                job = _diagnose_jobs[diagnosis_id]
                job["result"] = json.loads(cached["response_json"])
                job["status"] = "done"
                job["current_step"] = "done"
                job["finished_wall"] = time.time()
                job["src_code"] = "demo"
                return DiagnoseAck(diagnosis_id=diagnosis_id)
            except Exception:
                # Corrupt cache row: fall through to live inference.
                _diagnose_jobs[diagnosis_id]["status"] = "pending"
    asyncio.create_task(_run_diagnose(diagnosis_id, req, hashed_user, head_commit))
    return DiagnoseAck(diagnosis_id=diagnosis_id)


@app.get("/diagnose/{diagnosis_id}")
async def diagnose_status(diagnosis_id: str, response: Response):
    job = _diagnose_jobs.get(diagnosis_id)
    if job is None:
        raise HTTPException(
            status_code=404,
            detail="diagnosis_id not found (server restarted, or older than 1h)",
        )
    elapsed = round(time.perf_counter() - job["started_at"], 2)
    if job["status"] == "pending":
        response.status_code = 202
        return {
            "diagnosis_id": diagnosis_id,
            "status": "pending",
            "elapsed_seconds": elapsed,
            "current_step": job.get("current_step", "queued"),
            "progress": job.get("progress", {}),
        }
    if job["status"] == "failed":
        raise HTTPException(status_code=502, detail=job["error"] or "Unknown error")
    # Private, low-attention indicator: which source served this answer (A/B/C).
    # Not in the body, not in any UI; read it in the network tab when we care.
    response.headers["X-Akari-Src"] = job.get("src_code", "?")
    return job["result"]


async def _run_diagnose(
    diagnosis_id: str,
    req: DiagnoseRequest,
    hashed_user: Optional[str],
    head_commit: Optional[str],
) -> None:
    t0 = time.perf_counter()
    print(
        f"[DBG-DIAGNOSE] pid={_DEBUG_PID} "
        f"diagnosis_id={diagnosis_id} "
        f"depth={req.depth_tier!r} use_thinking={req.use_thinking} "
        f"model={req.model!r} "
        f"problem_len={len(req.problem or '')} "
        f"log_len={len(req.ips_log or '')} "
        f"log_first_80={(req.ips_log or '')[:80]!r} "
        f"log_last_80={(req.ips_log or '')[-80:]!r}",
        file=sys.stderr,
        flush=True,
    )
    success = False
    error_class: Optional[str] = None
    confidence: Optional[float] = None
    coverage: str = "poor"
    pages: list[Path] = []
    page_snapshots: list[dict] = []
    query_classification: dict = {}
    full_response_text: Optional[str] = None
    log_summary_text_for_audit: Optional[str] = None
    ips_findings: Optional[dict] = None
    ask_for_log: bool = False
    ask_for_cd: bool = False
    cd_reason: str = ""
    cd_classes: list[str] = []
    cd_result: Optional[dict] = None
    prompt_tokens: Optional[int] = None
    response_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    tokens_per_second: Optional[float] = None
    inference_duration_ms: Optional[int] = None
    system_metrics: dict[str, Optional[float]] = {
        "gpu_util_percent_avg": None,
        "vram_used_mb_peak": None,
        "cpu_percent_avg": None,
        "ram_used_mb_peak": None,
    }

    try:
        # Parse the IPS log into a compact structured summary (if present).
        # Replaces the previous raw-truncation path: gemma4:e2b was getting
        # attention-distracted by raw TSV noise and returning the NO-DATA
        # template. Parser failure falls back to capped raw text further down.
        log_summary: Optional[dict] = None
        log_summary_text: Optional[str] = None
        log_parse_error: Optional[str] = None
        log_extracted_codes: list[str] = []
        log_extracted_model: str = ""
        if req.ips_log:
            try:
                parsed_log = ips_log_parser.parse_tsv(req.ips_log)
                log_summary = ips_log_parser.summarize_log(parsed_log)
                log_summary_text = ips_log_parser.format_summary_for_prompt(log_summary)
                log_extracted_codes = ips_log_parser.error_codes_from_summary(log_summary)
                log_extracted_model = (log_summary.get("model") or "").strip()
                # Deterministic decode of the log against the IPS error dictionary.
                # Findings ground the prompt and back-fill ips_analysis if the model omits it.
                try:
                    ips_findings = ips_knowledge.analyze(log_summary, parsed_log)
                except Exception as ke:
                    print(f"[ips_knowledge] analyze failed: {ke}", file=sys.stderr, flush=True)
            except Exception as e:
                log_parse_error = f"{type(e).__name__}: {e}"

        # ── Phase: detecting model ──
        _diagnose_jobs[diagnosis_id]["current_step"] = "detecting"
        # The model dropdown is authoritative (problem isolation): a specific
        # selection scopes retrieval to that model and its family; "all" forces
        # the cross-wiki search. Typed-text detection is only a fallback for
        # when no selection was sent.
        selected_model = (req.model or "").strip()
        if selected_model.lower() in ("all", "all models", "*"):
            detected_model = None
        elif selected_model:
            detected_model = canonicalize_model(selected_model)
        else:
            detected_model = detect_model(req.problem, log_extracted_model)
        text_for_retrieval = req.problem or ""
        entities = extract_entities(text_for_retrieval)
        if detected_model:
            entities["models"] = [detected_model]
        _diagnose_jobs[diagnosis_id]["progress"]["detected_model"] = detected_model or "auto"

        # Error codes: symptom-derived codes + log-derived active codes.
        entities["error_codes"] = sorted(
            set(entities.get("error_codes", []) + log_extracted_codes)
        )

        # Ask-for-log gate: only when the symptom is sparse AND no log was given.
        ask_for_log = (not req.ips_log) and is_thin_symptom(
            req.problem, detected_model, entities["error_codes"]
        )
        # Condition Diagnosis gate: supported laser model + image-quality
        # complaint (or a light-source hint in the decoded log). Never fires on
        # thermal / power / comms faults or lamp models.
        cd_in = req.cd_values.model_dump() if req.cd_values else None
        if cd_in and not cd_knowledge.has_values(cd_in):
            cd_in = None
        ask_for_cd, cd_reason, cd_classes = cd_gate.should_suggest(
            detected_model, req.problem, ips_findings, cd_in
        )
        if cd_in:
            cd_result = cd_knowledge.evaluate(
                cd_in, model=detected_model,
                gap_threshold=settings.cd_gap_threshold,
                warmup_minutes=settings.cd_warmup_minutes,
            )

        # ── Phase: consulting wiki ──
        _diagnose_jobs[diagnosis_id]["current_step"] = "consulting"
        pages = pick_wiki_pages(entities, settings.wiki_path, text_for_retrieval)
        coverage = assess_coverage(pages)
        wiki_content = load_pages(pages)
        _diagnose_jobs[diagnosis_id]["progress"]["pages_count"] = len(pages)
        model_name = settings.model_deep if req.use_thinking else settings.model_fast

        # Build the per-page audit snapshots (path, content hash, HEAD commit, origin).
        page_snapshots = [
            db.page_snapshot_for_event(p, PROJECT_ROOT, head_commit) for p in pages
        ]
        query_classification = {
            "models": entities.get("models", []),
            "error_codes": entities.get("error_codes", []),
            "depth_tier_requested": req.depth_tier,
            "use_thinking": req.use_thinking,
            # IPS decode forensics (admin-only; never rendered to users).
            "ips": {
                "log_present": bool(req.ips_log),
                "notable": bool(ips_findings and ips_findings.get("notable")),
                "codes": (ips_findings or {}).get("codes", []),
                "severity": (ips_findings or {}).get("severity"),
                "ask_for_log": ask_for_log,
            },
            "cd": {
                "suggested": ask_for_cd, "reason": cd_reason, "classes": cd_classes,
                "values_given": bool(cd_result),
                "verdict": (cd_result or {}).get("verdict"),
                "reference_only": (cd_result or {}).get("reference_only", False),
            },
        }

        # Prefer the structured summary. Fall back to capped raw text only if
        # the parser failed (so the LLM still gets *something*).
        if log_summary_text:
            ips_log_block = log_summary_text
            # Append the deterministic decode so the model reasons from decoded
            # codes/factors, not raw counters.
            if ips_findings and ips_findings.get("text"):
                ips_log_block += "\n\n" + ips_findings["text"]
            log_block_source = "parsed_summary"
            log_summary_text_for_audit = ips_log_block
        elif req.ips_log:
            capped = req.ips_log[:MAX_IPS_LOG_CHARS]
            if len(req.ips_log) > MAX_IPS_LOG_CHARS:
                capped += "\n[Log truncated; full export not shown]"
            prefix = f"[Log parser failed: {log_parse_error}; partial raw text follows]\n" if log_parse_error else ""
            ips_log_block = prefix + capped
            log_block_source = "raw_fallback"
        else:
            ips_log_block = "(not provided)"
            log_block_source = "absent"

        print(
            f"[DBG-CAPPED] pid={_DEBUG_PID} "
            f"log_block_source={log_block_source} "
            f"ips_log_block_len={len(ips_log_block)} "
            f"first_80={ips_log_block[:80]!r} "
            f"wiki_content_len={len(wiki_content)} "
            f"pages_picked={len(pages)} "
            f"log_codes={log_extracted_codes} "
            f"log_model={log_extracted_model!r}",
            file=sys.stderr,
            flush=True,
        )

        prompt = DIAGNOSE_PROMPT.format(
            problem=req.problem,
            ips_log=ips_log_block,
            model=detected_model or "(auto-detect across all models)",
            wiki_content=wiki_content,
        )
        if not detected_model:
            # No model in the query: the wiki content is several models' pages at
            # once, which tempts the small model to bail with the no-data
            # template. Nudge it to still give general first-line help.
            prompt += (
                "\n\nNOTE: No specific projector model was identified in the problem. "
                "Do NOT return the no-data template. Give general first-line diagnostics "
                "for the reported symptom using the reference material above, keep confidence at "
                "0.5 or lower, and in recommended_next ask the engineer to provide the exact "
                "model number for a precise diagnosis."
            )
        if ips_findings and ips_findings.get("notable"):
            prompt += (
                "\n\nNOTE: An IPS log was uploaded and decoded (see the IPS LOG FINDINGS block). "
                "Populate ips_analysis per rule 10, grounded only in those findings."
            )
        if ask_for_cd:
            prompt += (
                "\n\nNOTE: This is an image-quality complaint on a laser model that supports the "
                "IPS Tool Condition Diagnosis measurement, and no measurement values were given. "
                "Do NOT decide between the light source module and the optical engine yet; say that "
                "the Condition Diagnosis values (LD calibration, LDDR, OE, Sensor, LSM B/Y) are needed "
                "to separate them, keep the cheapest steps first (clean the optics, light source "
                "calibration), and keep confidence at 0.6 or lower. Do not invent any measurement."
            )
        if cd_result:
            prompt += (
                "\n\nCONDITION DIAGNOSIS VERDICT (deterministic, from the engineer's measured values; "
                "copy it, do not re-derive):\n"
                f"Verdict: {cd_result['headline']}\n"
                + "".join(f"- {f}\n" for f in cd_result["findings"])
                + "Remedy order:\n"
                + "".join(f"{i + 1}. {r}\n" for i, r in enumerate(cd_result["remedy"]))
                + ("Reference only: short warm-up, repeat after full warm-up.\n" if cd_result["reference_only"] else "")
                + "Apply rule 14."
            )
        if ask_for_log:
            prompt += (
                "\n\nNOTE: The symptom is sparse and no IPS log was attached. Populate info_request "
                "per rule 11 (want=\"ips_log\") asking the engineer to attach the IPS Tool log."
            )

        img_b64 = _extract_image_b64(req.image)
        if img_b64:
            prompt += (
                "\n\nNOTE: A PHOTO of the symptom is attached. First state what is visibly wrong in the "
                "image (colors, bright/dark regions, bands, lines, pixels, on-screen text or error codes), "
                "then diagnose using that plus the reference material. Describe only what is actually "
                "visible; do not invent details the photo does not show."
            )

        # ── Phase: selecting engine (probe the A/B/C tiers in priority order) ──
        _diagnose_jobs[diagnosis_id]["current_step"] = "selecting"
        chosen_host = await inference.select_backend(settings, model_name=model_name)

        # ── Phase: analyzing (the big wait, the model call) ──
        _diagnose_jobs[diagnosis_id]["current_step"] = "analyzing"
        smp = sampler.SystemSampler()
        try:
            with smp:
                result = await inference.generate_diagnosis(
                    prompt=prompt,
                    model_name=model_name,
                    options={"temperature": 0.2, "num_ctx": 16384},
                    settings=settings,
                    host=chosen_host,
                    images=[img_b64] if img_b64 else None,
                )
        except Exception as e:
            error_class = "inference_failed"
            raise RuntimeError(f"Inference failed: {e}")
        system_metrics = smp.metrics()

        # Record which backend actually served. This stays server-side only:
        # the precise host/model goes into the audit DB (query_classification,
        # which the admin panel never renders), and the job carries an opaque
        # source code (A/B/C) for the private response header. Nothing here
        # reaches the user UI or the admin panel.
        served_model = getattr(result, "model", None) or model_name
        backend_label = getattr(result, "backend", None)
        query_classification["backend"] = {
            "kind": getattr(result, "backend_kind", "ollama"),
            "label": backend_label,
            "host": getattr(result, "host", None),
            "model": served_model,
        }
        job = _diagnose_jobs.get(diagnosis_id)
        if job is not None:
            job["src_code"] = inference.src_code(backend_label)

        # Token + inference timing from the ollama response. Any field may be
        # missing on older servers; treat each as Optional and skip derived
        # math when an input is None.
        try:
            prompt_tokens = getattr(result, "prompt_eval_count", None)
            response_tokens = getattr(result, "eval_count", None)
            eval_duration_ns = getattr(result, "eval_duration", None)
            prompt_eval_duration_ns = getattr(result, "prompt_eval_duration", None)
            if prompt_tokens is not None and response_tokens is not None:
                total_tokens = int(prompt_tokens) + int(response_tokens)
            elif response_tokens is not None:
                total_tokens = int(response_tokens)
            if response_tokens and eval_duration_ns:
                tokens_per_second = round(
                    float(response_tokens) / (float(eval_duration_ns) / 1e9), 2
                )
            if eval_duration_ns is not None or prompt_eval_duration_ns is not None:
                inference_duration_ms = int(
                    ((eval_duration_ns or 0) + (prompt_eval_duration_ns or 0)) / 1e6
                )
        except Exception as e:
            print(f"[metrics] token extraction failed: {e}", file=sys.stderr, flush=True)

        elapsed = time.perf_counter() - t0

        try:
            parsed = json.loads(result.response)
        except json.JSONDecodeError as e:
            error_class = "model_invalid_json"
            raise RuntimeError(
                f"Model returned invalid JSON: {e}. Raw: {result.response[:300]}"
            )

        # ── Phase: drafting (validating + filling sparse JSON, building response) ──
        _diagnose_jobs[diagnosis_id]["current_step"] = "drafting"

        parsed = merge_sparse_response(parsed, req, detected_model)
        # Deterministic grounding guard: remove any fabricated wiki page citations
        # the model invented (only real retrieved pages survive).
        parsed = strip_fabricated_sources(parsed, pages, settings.wiki_path)

        try:
            confidence = float(parsed.get("diagnosis", {}).get("confidence") or 0.0)
        except Exception:
            confidence = None

        # Ground the model's self-reported confidence in how much wiki actually
        # backed the answer. The small model tends to be overconfident on thin
        # coverage, so cap confidence at a ceiling set by the assessed coverage
        # tier. This is a ceiling only (never raises a low confidence).
        COVERAGE_CONF_CEILING = {"good": 0.95, "partial": 0.7, "poor": 0.45}
        if confidence is not None:
            ceiling = COVERAGE_CONF_CEILING.get(coverage, 0.7)
            if confidence > ceiling:
                confidence = ceiling
                diag = parsed.setdefault("diagnosis", {})
                diag["confidence"] = ceiling
                # Only explain the cap when coverage is genuinely thin.
                if coverage != "good":
                    note = (" Confidence is capped here because coverage for this specific "
                            "problem is limited. Provide the exact model and more detail, or "
                            "attach the IPS Tool log, for a more certain diagnosis.")
                    reasoning = diag.get("reasoning")
                    if isinstance(reasoning, str) and note.strip() not in reasoning:
                        diag["reasoning"] = reasoning.rstrip() + note

        parsed.setdefault("metadata", {})
        parsed["metadata"]["diagnosis_id"] = diagnosis_id
        parsed["metadata"]["wiki_pages_used"] = page_paths_for_metadata(pages)
        # Opaque on purpose: the real engine/backend is never exposed to the
        # browser or any rendered view. Forensics live in the audit DB only.
        parsed["metadata"]["model_used"] = "akari"
        parsed["metadata"]["elapsed_seconds"] = round(elapsed, 2)
        parsed["metadata"]["wiki_coverage"] = coverage
        parsed["metadata"]["output_format"] = "json"

        # IPS analysis: show the section only when the log decoded something
        # notable. Keep the model's prose summary when it gave one, but always
        # use the deterministic findings + severity for structure (so the model
        # can never fabricate a code or break the schema).
        if ips_findings and ips_findings.get("notable"):
            model_ips = parsed.get("ips_analysis")
            summary = ""
            if isinstance(model_ips, dict) and isinstance(model_ips.get("summary"), str):
                summary = model_ips["summary"].strip()
            parsed["ips_analysis"] = {
                "summary": summary or ips_findings["summary"],
                "findings": ips_findings["findings"],
                "severity": ips_findings["severity"],
            }
        else:
            parsed.pop("ips_analysis", None)

        # Ask-for-log: structured request when the symptom is thin and no log
        # was attached. Deterministic message guarantees a valid, on-brand ask.
        if ask_for_cd and detected_model:
            parsed["info_request"] = {
                "want": "condition_diagnosis",
                "message": cd_gate.build_message(
                    detected_model, cd_classes,
                    warmup_minutes=settings.cd_warmup_minutes,
                    help_url=settings.cd_help_url,
                ),
                "help_url": settings.cd_help_url,
            }
        elif ask_for_log:
            model_ir = parsed.get("info_request")
            msg = ""
            if isinstance(model_ir, dict) and isinstance(model_ir.get("message"), str):
                msg = model_ir["message"].strip()
            parsed["info_request"] = {"want": "ips_log", "message": msg or DEFAULT_ASK_LOG_MSG}
        else:
            parsed.pop("info_request", None)

        # Escalation: deterministically complete the draft. Engineer-only fields
        # become ⟨...⟩ gaps (the small model otherwise fabricates them or leaks
        # internal paths into references_checked); model/serial/firmware/error
        # evidence are sourced from the decoded log. The model keeps only the
        # grounded prose fields.
        _finalize_escalation(
            parsed.get("escalation_draft"),
            log_summary=log_summary,
            ips_findings=ips_findings,
            detected_model=detected_model,
            has_log=bool(req.ips_log),
        )
        if cd_result:
            parsed["cd_analysis"] = dict(cd_result, help_url=settings.cd_help_url)
            # Reference-only measurement (short warm-up): never let the prose
            # sound more certain than the numbers allow.
            if cd_result.get("reference_only"):
                d = parsed.get("diagnosis")
                if isinstance(d, dict):
                    try:
                        d["confidence"] = min(float(d.get("confidence", 0.5)), 0.5)
                    except (TypeError, ValueError):
                        d["confidence"] = 0.5
            esc = parsed.get("escalation_draft")
            if isinstance(esc, dict):
                line = cd_knowledge.summary_line(cd_result)
                ev = esc.get("error_evidence") or ""
                esc["error_evidence"] = line if _is_blank_or_placeholder(ev) else f"{ev}; {line}"
                warm = (cd_result.get("values") or {}).get("warmup_minutes")
                warm_txt = f" after {warm:g} min warm-up" if isinstance(warm, (int, float)) else ""
                esc["tried_steps"] = (
                    f"Condition Diagnosis run in the IPS Tool{warm_txt}; values recorded above. "
                    "⟨other steps you took and their result; note any parts replaced⟩"
                )
        else:
            parsed.pop("cd_analysis", None)

        # Opsec net: ensure no internal-knowledge-base wording reaches the user.
        scrub_response_for_user(parsed)

        try:
            response = DiagnoseResponse(**parsed)
        except Exception as e:
            error_class = "response_schema_invalid"
            raise RuntimeError(
                f"Response schema validation failed: {e}. Raw: {json.dumps(parsed)[:500]}"
            )

        success = True
        result_dict = response.model_dump()
        try:
            full_response_text = json.dumps(result_dict, ensure_ascii=False)
        except Exception:
            full_response_text = None
        job = _diagnose_jobs.get(diagnosis_id)
        if job is not None:
            job["status"] = "done"
            job["current_step"] = "done"
            job["result"] = result_dict
            job["finished_wall"] = time.time()
    except HTTPException:
        # Should be rare in the background path (we converted most to RuntimeError),
        # but handle any stragglers cleanly.
        if not error_class:
            error_class = "http_exception"
        raise
    except Exception as e:
        if not error_class:
            error_class = type(e).__name__
        job = _diagnose_jobs.get(diagnosis_id)
        if job is not None:
            job["status"] = "failed"
            job["error"] = f"{error_class}: {e}"
            job["finished_wall"] = time.time()
        print(
            f"[DIAGNOSE-FAIL] diagnosis_id={diagnosis_id} error_class={error_class} err={e!r}",
            file=sys.stderr,
            flush=True,
        )
    finally:
        latency_ms = int((time.perf_counter() - t0) * 1000)
        try:
            await asyncio.to_thread(
                db.write_diagnose_event,
                diagnosis_id=diagnosis_id,
                ts=db.now_utc_iso(),
                hashed_user=hashed_user,
                depth_tier=(req.depth_tier or ("balanced" if req.use_thinking else "fast")),
                confidence=confidence,
                coverage=coverage,
                latency_ms=latency_ms,
                success=success,
                error_class=error_class,
                image_used=bool(img_b64),
                pages_count=len(pages),
                wiki_pages_used=page_snapshots,
                query_classification=query_classification,
                prompt_tokens=prompt_tokens,
                response_tokens=response_tokens,
                total_tokens=total_tokens,
                tokens_per_second=tokens_per_second,
                inference_duration_ms=inference_duration_ms,
                gpu_util_percent_avg=system_metrics.get("gpu_util_percent_avg"),
                vram_used_mb_peak=system_metrics.get("vram_used_mb_peak"),
                cpu_percent_avg=system_metrics.get("cpu_percent_avg"),
                ram_used_mb_peak=system_metrics.get("ram_used_mb_peak"),
                problem_text=req.problem,
                model_input=detected_model or "auto",
                ips_log_summary=log_summary_text_for_audit,
                full_response_text=full_response_text,
            )
        except Exception as e:
            print(
                f"[DIAGNOSE-AUDIT-FAIL] diagnosis_id={diagnosis_id} err={e!r}",
                file=sys.stderr,
                flush=True,
            )
