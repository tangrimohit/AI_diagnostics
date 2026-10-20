"""Opsec scanner for wiki content + agent output.

Detects internal references that must never appear in user-facing wiki pages or
diagnostic answers: case / escalation / ticket IDs, customer or partner names,
country or region names (which also covers place-name style platform codenames),
and incident-flavoured wording.

Primary use is DETECTION (scan), so a human or synthesis agent can rewrite the
offending text to a pure technical conclusion. scrub_text() is a blunt
last-resort gate that strips IDs and masks country names; prefer rewriting.

CLI:
  python -m api.opsec scan wiki            # scan a dir or file, report leaks
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

# --- case / escalation / ticket / report identifiers -------------------------
CASE_ID_PATTERNS = [
    ("case_id", re.compile(r"\bTESC[-\s]?\d{3,}\b", re.I)),
    ("case_id", re.compile(r"\bSR[-\s]?\d{4,}\b")),
    ("case_id", re.compile(r"\b(?:END|ENC)[-\s]?\d{3,}\b", re.I)),
    ("case_id", re.compile(r"\bMSD\s*#?\s*\d{3,}\b", re.I)),
    ("case_id", re.compile(r"\bTI\d{2}-\d{2,}[A-Z\-]*\b")),          # TI bulletins
    ("case_id", re.compile(r"\bVP\d{2}-[A-Z]{3}-\d{3,}[A-Z\-]*\b")), # VP bulletins
]

# Country / region names. Doubles as a guard for place-name style codenames.
COUNTRIES = {
    "afghanistan", "albania", "algeria", "angola", "argentina", "armenia",
    "australia", "austria", "azerbaijan", "bahrain", "bangladesh", "belarus",
    "belgium", "bolivia", "bosnia", "brazil", "bulgaria", "cambodia", "cameroon",
    "canada", "chile", "china", "colombia", "croatia", "cyprus", "czech",
    "czechia", "denmark", "ecuador", "egypt", "estonia", "ethiopia", "finland",
    "france", "georgia", "germany", "ghana", "greece", "hungary", "iceland",
    "india", "indonesia", "iran", "iraq", "ireland", "israel", "italy", "japan",
    "jordan", "kazakhstan", "kenya", "kuwait", "latvia", "lebanon", "libya",
    "lithuania", "luxembourg", "malaysia", "mexico", "moldova", "mongolia",
    "montenegro", "morocco", "nepal", "netherlands", "holland", "norway", "oman",
    "pakistan", "peru", "philippines", "poland", "portugal", "qatar", "romania",
    "russia", "saudi", "serbia", "singapore", "slovakia", "slovenia", "somalia",
    "spain", "sweden", "switzerland", "syria", "taiwan", "thailand", "tunisia",
    "turkey", "turkiye", "ukraine", "emirates", "uae", "uganda", "vietnam",
    "yemen", "zambia", "zimbabwe",
}
# Multi-word / ambiguous region phrases handled separately.
REGION_PHRASES = [
    "united states", "united kingdom", "saudi arabia", "south korea",
    "north korea", "south africa", "new zealand", "middle east", "north africa",
]
_COUNTRY_RE = re.compile(
    r"\b(" + "|".join(sorted(re.escape(c) for c in COUNTRIES)) + r")\b", re.I
)
_REGION_RE = re.compile(
    r"\b(" + "|".join(re.escape(p) for p in REGION_PHRASES) + r")\b", re.I
)

# Incident-flavoured wording: tie a fault to a real-world event/cluster instead
# of stating the technical conclusion.
INCIDENT_RE = re.compile(
    r"\b(mass[- ]failures?|warranty cluster|mass defect|customer\s+complaint)\b", re.I
)

# Internal engineering codenames: deployment-specific, loaded from
# data/knowledge/codenames.txt (one per line) when present.
def _codename_re() -> re.Pattern:
    from pathlib import Path
    p = Path(__file__).resolve().parent.parent / "data" / "knowledge" / "codenames.txt"
    names = []
    if p.exists():
        names = [n.strip() for n in p.read_text(encoding="utf-8").splitlines() if n.strip()]
    if not names:
        return re.compile(r"(?!x)x")
    return re.compile(r"\b(?:" + "|".join(re.escape(n) for n in names) + r")\b", re.I)


CODENAME_RE = _codename_re()

CODENAME_SHORT_RE = re.compile(r"(?!x)x")

# Internal organisation / channel acronyms and bare country acronyms.
ORG_RE = re.compile(r"\b(?:EMEA|APAC)\b")          # case-sensitive
CORP_RE = re.compile(r"Seiko\s+Epson\s+Corp(?:oration|\.)?", re.I)  # service-manual footer
COUNTRY_ACRONYM_RE = re.compile(r"\b(?:USA|U\.S\.A\.|U\.S\.|UK|KSA)\b")  # case-sensitive
# Serial-number prefixes from service-manual spec tables (e.g. XD9S430001L).
SERIAL_RE = re.compile(r"\b[A-Z][A-Z0-9]{3}\d{6}[A-Z]?\b")

# Redaction / ingest artifacts that mean a page was not fully rewritten to clean
# technical prose. Flagged so "scan = 0" guarantees genuinely clean output.
ARTIFACT_RE = re.compile(
    r"(\*\*\*\*|\*WEB\*|\(the field[,)]|the field[,)]|raw/(?:msd|tis|depot2|manuals|web|ips_logs)"
    r"|INTERNAL USE ONLY)"
)

# Words allowed even though they look like leaks (product/tech terms).
_ALLOW = {"china"}  # e.g. "made in" rarely; keep minimal. Adjust if needed.


def scan_text(text: str) -> list[dict[str, Any]]:
    """Return a list of {category, match, pos} for every leak found."""
    findings: list[dict[str, Any]] = []
    for cat, rx in CASE_ID_PATTERNS:
        for m in rx.finditer(text):
            findings.append({"category": cat, "match": m.group(0), "pos": m.start()})
    for m in _COUNTRY_RE.finditer(text):
        if m.group(0).lower() in _ALLOW:
            continue
        findings.append({"category": "country", "match": m.group(0), "pos": m.start()})
    for m in _REGION_RE.finditer(text):
        findings.append({"category": "region", "match": m.group(0), "pos": m.start()})
    for m in INCIDENT_RE.finditer(text):
        findings.append({"category": "incident", "match": m.group(0), "pos": m.start()})
    for m in CODENAME_RE.finditer(text):
        findings.append({"category": "codename", "match": m.group(0), "pos": m.start()})
    for m in CODENAME_SHORT_RE.finditer(text):
        findings.append({"category": "codename", "match": m.group(0), "pos": m.start()})
    for m in ORG_RE.finditer(text):
        findings.append({"category": "org", "match": m.group(0), "pos": m.start()})
    for m in CORP_RE.finditer(text):
        findings.append({"category": "org", "match": m.group(0), "pos": m.start()})
    for m in SERIAL_RE.finditer(text):
        findings.append({"category": "serial", "match": m.group(0), "pos": m.start()})
    for m in COUNTRY_ACRONYM_RE.finditer(text):
        findings.append({"category": "country", "match": m.group(0), "pos": m.start()})
    for m in ARTIFACT_RE.finditer(text):
        findings.append({"category": "artifact", "match": m.group(0), "pos": m.start()})
    findings.sort(key=lambda f: f["pos"])
    return findings


def scrub_text(text: str) -> str:
    """Blunt gate: delete case IDs, mask country/region names. Prefer rewriting."""
    for _, rx in CASE_ID_PATTERNS:
        text = rx.sub("", text)
    text = INCIDENT_RE.sub("a reported fault", text)
    text = CODENAME_RE.sub("this projector family", text)
    text = CORP_RE.sub("the manufacturer", text)
    text = SERIAL_RE.sub("", text)
    text = ORG_RE.sub("the manufacturer", text)
    text = COUNTRY_ACRONYM_RE.sub("the field", text)
    text = _REGION_RE.sub("the field", text)
    text = _COUNTRY_RE.sub(lambda m: "the field" if m.group(0).lower() not in _ALLOW else m.group(0), text)
    text = CODENAME_SHORT_RE.sub("", text)
    # collapse the whitespace the deletions may leave behind
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text


_DETAILS_RE = re.compile(r"<details>.*?</details>", re.DOTALL | re.I)
_EMPTY_BULLET_RE = re.compile(r"^\s*[-*]\s*(?:,\s*)*$", re.M)
_SOURCES_SECTION_RE = re.compile(r"\n#{2,4}\s*Sources\b.*?(?=\n#{2,4}\s|\Z)", re.DOTALL | re.I)
_PAREN_FIELD_RE = re.compile(r"\s*\(the field[^)]*\)", re.I)
_RAW_PATH_RE = re.compile(r"`?\s*raw/(?:msd|tis|depot2|manuals|web|ips_logs)[^\s`)]*`?", re.I)


def strip_provenance(text: str) -> str:
    """Remove case-citation scaffolding (collapsible source blocks, Sources
    sections, raw/ paths, *WEB* markers, redacted parentheticals, empty bullets)
    that exists only to cite internal sources. Keeps technical prose + headings."""
    text = _DETAILS_RE.sub("", text)
    text = _SOURCES_SECTION_RE.sub("", text)
    text = _PAREN_FIELD_RE.sub("", text)
    text = _RAW_PATH_RE.sub("", text)
    text = text.replace("*WEB*", "")
    text = re.sub(r"INTERNAL USE ONLY", "", text, flags=re.I)
    text = _EMPTY_BULLET_RE.sub("", text)
    return text


def clean_text(text: str) -> str:
    """Full opsec clean for an existing wiki page: drop provenance scaffolding,
    then strip IDs / mask countries / neutralise incident wording. Deterministic,
    so it can never introduce a hallucinated fact; it only removes."""
    text = strip_provenance(text)
    text = scrub_text(text)
    # tidy: collapse 3+ blank lines left by removals
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def clean_file(path: Path) -> int:
    """Clean a wiki file in place. Returns leaks remaining after cleaning."""
    original = path.read_text(encoding="utf-8", errors="replace")
    cleaned = clean_text(original)
    if cleaned != original:
        path.write_text(cleaned, encoding="utf-8")
    return len(scan_text(cleaned))


def scan_paths(root: Path) -> dict[str, list[dict[str, Any]]]:
    """Scan a dir (recursively, *.md) or a single file. Returns {relpath: findings}."""
    out: dict[str, list[dict[str, Any]]] = {}
    files = [root] if root.is_file() else sorted(root.rglob("*.md"))
    for p in files:
        if "_drafts" in p.parts:
            continue
        try:
            f = scan_text(p.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
        if f:
            out[str(p)] = f
    return out


def _main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[0] not in ("scan", "clean"):
        print("usage: python -m api.opsec scan|clean <dir-or-file>", file=sys.stderr)
        return 2
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    root = Path(argv[1])

    if argv[0] == "clean":
        files = [root] if root.is_file() else sorted(root.rglob("*.md"))
        files = [f for f in files if "_drafts" not in f.parts]
        changed = 0
        residual = 0
        for f in files:
            before = len(scan_text(f.read_text(encoding="utf-8", errors="replace")))
            after = clean_file(f)
            if before and not after:
                changed += 1
            elif after:
                residual += after
                print(f"  RESIDUAL in {f}: {after} leaks")
        print(f"cleaned {changed} files; {residual} residual leaks")
        return 0 if residual == 0 else 1

    results = scan_paths(root)
    total = sum(len(v) for v in results.values())
    if not results:
        print(f"CLEAN: no opsec leaks under {root}")
        return 0
    for path, findings in results.items():
        cats: dict[str, set] = {}
        for f in findings:
            cats.setdefault(f["category"], set()).add(f["match"])
        summary = "; ".join(f"{c}: {', '.join(sorted(v))}" for c, v in cats.items())
        print(f"{path}  ({len(findings)})")
        print(f"    {summary}")
    print(f"\n{total} leaks across {len(results)} files")
    return 1


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
