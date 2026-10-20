"""User-label registry: resolve salted user hashes to human-readable names.

The audit DB (monitor.db) stores only salted hashes (opsec rule, see db.py).
This module is the *display-time* mapping from hash -> name, used only by the
admin panel. Names live in data/user_labels.json (gitignored, stays on the local PC);
they are never written into the audit DB.

Three ways a hash gets a name, in precedence order:

1. by_hash   — manual override keyed by the full hash (for hashes whose email
               we don't know, or to force a specific spelling).
2. by_email  — keyed by login email; the hash is computed deterministically at
               load via db.hash_user(email). This is how you pre-name a person:
               add one "email": "Name" line. It also pairs with the
               reverse-proxy allowlist (same emails).
3. learned   — auto-captured the first time a new authenticated user calls the
               API. The display name is derived from the email local-part
               (first.last@epson.ae -> "First Last"). No manual step needed.

Unknown hash  -> "user-<first7>"  (still distinct, just unnamed)
None / NULL    -> "Service / headless"  (service token or localhost, no login)
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_LABELS_PATH = Path(__file__).resolve().parent.parent / "data" / "user_labels.json"

# Seed registry. by_email is the canonical, future-proof way to name people;
# the hash is computed from the email at load time.
_SEED = {
    "by_email": {
    },
    "by_hash": {},
    "learned": {},
}

_NULL_LABEL = "Service / headless"

_lock = threading.Lock()
_store: Optional[dict] = None        # raw file contents
_hash_to_name: dict[str, str] = {}   # resolved lookup, rebuilt on load/learn
_known_hashes: set[str] = set()      # hashes we've already named (skip re-learn)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _pretty_from_email(email: str) -> str:
    """first.last@epson.ae -> 'First Last'. Best-effort, override-able."""
    local = email.strip().lower().split("@", 1)[0]
    parts = [p for p in local.replace("_", ".").replace("-", ".").split(".") if p]
    return " ".join(p.capitalize() for p in parts) or local


def _load() -> dict:
    global _store
    if _LABELS_PATH.exists():
        try:
            data = json.loads(_LABELS_PATH.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    else:
        data = {}
    # Merge seed into any missing keys (so first run writes the seed, and later
    # runs keep the admin's manual edits while still guaranteeing the sections exist).
    data.setdefault("by_email", {})
    data.setdefault("by_hash", {})
    data.setdefault("learned", {})
    for em, name in _SEED["by_email"].items():
        data["by_email"].setdefault(em, name)
    _store = data
    return data


def _save() -> None:
    if _store is None:
        return
    try:
        _LABELS_PATH.parent.mkdir(parents=True, exist_ok=True)
        _LABELS_PATH.write_text(
            json.dumps(_store, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    except Exception:
        # Labeling must never break a request; a failed write just means the
        # name resolves from in-memory state this run and re-learns next time.
        pass


def _rebuild_index() -> None:
    """Recompute hash -> name from the loaded store. by_hash > by_email > learned."""
    global _hash_to_name, _known_hashes
    from api.db import hash_user  # lazy: db imports this module at top

    idx: dict[str, str] = {}
    # Lowest precedence first so higher-precedence keys overwrite.
    for h, entry in (_store or {}).get("learned", {}).items():
        name = entry.get("name") if isinstance(entry, dict) else entry
        if h and name:
            idx[h] = name
    for em, name in (_store or {}).get("by_email", {}).items():
        h = hash_user(em)
        if h and name:
            idx[h] = name
    for h, name in (_store or {}).get("by_hash", {}).items():
        if h and name:
            idx[h] = name
    _hash_to_name = idx
    # "Known" = anyone explicitly named (by_email/by_hash) or already learned;
    # used to skip the re-learn write path.
    _known_hashes = set(idx.keys())


def _ensure_loaded() -> None:
    if _store is None:
        _load()
        _rebuild_index()
        # Persist the seed on first ever run.
        if not _LABELS_PATH.exists():
            _save()


def resolve(hashed_user: Optional[str]) -> str:
    """Hash -> display name. NULL -> service label; unknown -> 'user-<first7>'."""
    _ensure_loaded()
    if not hashed_user:
        return _NULL_LABEL
    name = _hash_to_name.get(hashed_user)
    if name:
        return name
    return "user-" + hashed_user[:7]


def note_user(email: Optional[str]) -> None:
    """Auto-learn a new authenticated user from their login email.

    Called on authenticated requests. Cheap and exception-safe: if the user is
    already named (seeded, manual, or previously learned) it's a no-op set
    membership check; only a genuinely new user triggers a file write.
    """
    if not email or not email.strip():
        return
    try:
        from api.db import hash_user
        h = hash_user(email)
        if not h:
            return
        _ensure_loaded()
        if h in _known_hashes:
            return
        with _lock:
            if h in _known_hashes:  # re-check under lock
                return
            (_store["learned"])[h] = {
                "name": _pretty_from_email(email),
                "email": email.strip().lower(),
                "first_seen": _now_iso(),
            }
            _rebuild_index()
            _save()
    except Exception:
        # Never let labeling interfere with serving a diagnosis.
        return


def email_for_hash(hashed_user: Optional[str]) -> Optional[str]:
    """Reverse-resolve a hash to a login email, if we know it.

    Used to actually send mail to a user. Sources: by_email seeds (compute hash
    per email) and auto-learned entries (which store the email). Returns None for
    unknown / service / NULL hashes, so the caller simply skips sending.
    """
    if not hashed_user:
        return None
    _ensure_loaded()
    from api.db import hash_user
    for em in (_store or {}).get("by_email", {}):
        if hash_user(em) == hashed_user:
            return em
    entry = (_store or {}).get("learned", {}).get(hashed_user)
    if isinstance(entry, dict) and entry.get("email"):
        return entry["email"]
    return None


def named_breakdown(pairs: list[tuple[Optional[str], int]]) -> list[dict]:
    """[(hash, count), ...] -> [{"name", "count"}, ...] sorted by count desc.

    Service/headless (NULL) rows are folded together under the service label.
    """
    _ensure_loaded()
    agg: dict[str, int] = {}
    for h, count in pairs:
        agg[resolve(h)] = agg.get(resolve(h), 0) + (count or 0)
    return [
        {"name": n, "count": c}
        for n, c in sorted(agg.items(), key=lambda kv: kv[1], reverse=True)
    ]
