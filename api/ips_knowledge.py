"""IPS log decoding knowledge base + deterministic analyzer.

Turns the structured summary/parsed dicts from ``ips_log_parser`` into ranked,
human-meaningful findings using the error / warning code dictionary and the
laser (YE) factor -> cause -> solution table.

The built-in tables below are the base set. A deployment extends them by
dropping ``data/knowledge/ips_knowledge.json`` next to the runtime data (same
keys: ``error_codes``, ``warning_codes``, ``ye_factors``); that file is loaded
at import time and merged over the defaults.

This module is the deterministic ground truth. It never speculates beyond the
dictionary. The language model writes the human-facing prose on top of these
findings; if it omits the section, the caller falls back to ``result["text"]``.

Opsec: technical content only. No internal platform codenames, no case IDs, no
customer / country references in any string here.
"""

from __future__ import annotations

import re
from typing import Any, Optional


# -------------------- error / warning code dictionary --------------------
# (name, category, severity). Extended per deployment via data/knowledge/.

ERROR_CODES: dict[str, tuple[str, str, str]] = {
    "TH": ("Internal Temp Error", "thermal", "high"),
    "FN": ("Fan Error", "cooling", "high"),
    "SE": ("Temp Sensor Error", "sensor", "high"),
    "II": ("I2C Error", "communication", "high"),
}

WARNING_CODES: dict[str, str] = {
    "TH": "High Temp Warning",
    "YE": "Laser Warning",
}


SEVERITY_ORDER = {"critical": 3, "high": 2, "medium": 1, "low": 0, "info": 0}

# Firmware build below this "Vnnn" value predates the laser-thermal fixes called
# out in the YE Rev.D guide ("Update Main FW to the latest, V130 or later").
# Used only as a soft "update first" nudge, never as a hard fault.
FW_FIX_BASELINE = 130


def error_vs_warning(kind: str) -> str:
    """The one semantic that reframes urgency, per the service training."""
    if kind == "error":
        return "Error: image projection stops to protect the unit"
    return "Warning: projection continues with a limitation (e.g. brightness drops)"


# -------------------- YE (laser) factor matrix --------------------
# factor string (read from the Detailed Laser Log: DR ST / LD Err ST / Err ST /
# LightSource ST) -> ranked cause -> ranked solution. Transcribed from training
# slides 40-54 and the Rev.D guide. Ordered specific-first so substring matching
# resolves the most precise factor.

YE_FACTORS: list[dict[str, Any]] = [
    {
        "keys": ["source war", "lightoutput", "light output"],
        "factor": "Source War",
        "meaning": "light-source module warning (light strength / balance)",
        "causes": ["degraded optics in the light path", "light-source module ageing", "calibration incomplete"],
        "parts": ["light source module", "optical engine"],
        "fix": ["run light-source calibration", "inspect and clean the optical path", "replace the light source module if the warning persists"],
    },
    {
        "keys": ["ary err", "drv err", "ary war", "drv war"],
        "factor": "Ary / Drv Err",
        "meaning": "laser array or laser driver fault (read the sub-factor in the detailed laser log)",
        "causes": ["laser array or driver failure; the sub-factor pinpoints the path"],
        "parts": ["laser driver board", "power supply", "light source module"],
        "fix": ["read the detailed laser log sub-factor", "follow the matching service-manual sequence"],
    },
]


def _load_site_tables() -> None:
    """Merge deployment-specific tables from data/knowledge/ips_knowledge.json."""
    import json
    from pathlib import Path
    p = Path(__file__).resolve().parent.parent / "data" / "knowledge" / "ips_knowledge.json"
    if not p.exists():
        return
    try:
        site = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return
    for k, v in (site.get("error_codes") or {}).items():
        ERROR_CODES[k] = tuple(v)
    WARNING_CODES.update(site.get("warning_codes") or {})
    YE_FACTORS[:0] = list(site.get("ye_factors") or [])


_load_site_tables()



def match_ye_factor(text: str) -> Optional[dict[str, Any]]:
    """Return the YE factor entry whose keyword matches ``text`` (the combined
    errSub + factor + DR ST / Err ST / LightSource ST blob), or None."""
    low = (text or "").lower()
    if not low.strip():
        return None
    for entry in YE_FACTORS:
        for k in entry["keys"]:
            if k in low:
                return entry
    return None


# -------------------- TH temperature levels --------------------
# Per the FN/TH/SE slide: thermistor state T1..T5. T3 is the warning threshold,
# T5 the error threshold. "Level nn, over 3 means hotter than normal."

TH_LEVELS: dict[int, str] = {
    1: "normal",
    2: "normal (rising)",
    3: "warning threshold",
    4: "high (pre-error)",
    5: "error threshold (shutdown)",
}


def th_level_note(level: Optional[int]) -> str:
    if level is None:
        return ""
    state = TH_LEVELS.get(level, "abnormal")
    return f"temperature level T{level} ({state})"


# -------------------- I2C decode --------------------
# The II factor string carries the device pair and slave address, e.g.
# "Vic(MA board)-NTAG(NFC board) Communication Error. ... slave addr=00AAh ...".

_I2C_PAIR_RE = re.compile(r"([A-Za-z0-9 ]+\([^)]+\))\s*-\s*([A-Za-z0-9 ]+\([^)]+\))")
_I2C_ADDR_RE = re.compile(r"slave\s*addr\s*=\s*([0-9A-Fa-f]+h?)")


def decode_i2c(factor: str) -> Optional[str]:
    """Short human note from an I2C (II) factor string: which two devices
    failed to talk, and the generic reseat-then-swap sequence."""
    if not factor:
        return None
    pair = _I2C_PAIR_RE.search(factor)
    addr = _I2C_ADDR_RE.search(factor)
    bits: list[str] = []
    if pair:
        a, b = pair.group(1).strip(), pair.group(2).strip()
        bits.append(f"{a} <-> {b}")
        bits.append("reseat the cable between the boards, then swap the addressed board")
    if addr:
        bits.append(f"slave addr {addr.group(1)}")
    if not bits:
        return None
    return "; ".join(bits) + " (confirm the device via the service-manual slave-address list)"



# -------------------- firmware staleness (soft) --------------------

_FW_VNNN_RE = re.compile(r"V(\d{2,4})\b")


def fw_value(fw: str) -> Optional[int]:
    m = _FW_VNNN_RE.search(fw or "")
    return int(m.group(1)) if m else None


# -------------------- the analyzer --------------------

def _iter_events(parsed: dict[str, Any]):
    yield from parsed.get("events", [])
    yield from parsed.get("detailedLaser", [])


def _max_th_level(parsed: dict[str, Any]) -> Optional[int]:
    """Highest TH event level seen, read from the event 'factor'/'component'
    text (e.g. 'Level 4'). Returns None when no level is present."""
    best: Optional[int] = None
    for ev in _iter_events(parsed):
        blob = " ".join(str(ev.get(k, "")) for k in ("errSub", "factor", "component", "raw"))
        m = re.search(r"\bLevel\s*(\d)\b", blob)
        if m:
            lvl = int(m.group(1))
            if best is None or lvl > best:
                best = lvl
    return best


def analyze(summary: dict[str, Any], parsed: dict[str, Any]) -> dict[str, Any]:
    """Deterministic read of a parsed IPS log.

    Returns:
      {
        "notable": bool,          # is anything worth a dedicated section
        "summary": str,           # one-line headline
        "findings": [str],        # short bullet lines (for the response)
        "severity": str,          # overall: critical|high|medium|low|info
        "text": str,              # compact block for prompt injection + fallback
        "codes": [str],           # decoded codes (audit)
      }
    """
    active_errors = summary.get("active_error_counts") or {}
    active_warnings = summary.get("active_warning_counts") or {}

    findings: list[dict[str, Any]] = []  # {sev, kind, line}
    codes: list[str] = []
    notable = False

    # 1) Active ERROR counters (primary signal).
    for code, count in active_errors.items():
        info = ERROR_CODES.get(code)
        sev = info[2] if info else "high"
        codes.append(code)
        # YE and II get decoded below; here keep a base line for everything else.
        if code in ("YE", "II"):
            continue
        if info:
            line = f"[ERROR] {code} {info[0]} x{count} ({sev})."
        else:
            line = f"[ERROR] {code} x{count} (not in dictionary; see service manual)."
        if code in ("TH", "FN", "SE", "WL", "VE"):
            line += " Likely cooling/thermal path: clear vents, clean/replace filter, check ambient and fan."
        findings.append({"sev": sev, "kind": "error", "line": line})
        notable = True

    # 2) YE laser decode (error and/or warning side).
    ye_kind = "error" if "YE" in active_errors else ("warning" if "YE" in active_warnings else None)
    if ye_kind:
        codes.append("YE")
        factor = None
        for ev in _iter_events(parsed):
            if ev.get("errCode") != "YE":
                continue
            ld = ev.get("ld") or {}
            blob = " ".join([
                str(ev.get("errSub", "")), str(ev.get("factor", "")),
                str(ld.get("drSt", "")), str(ld.get("errSt", "")), str(ld.get("lightSrc", "")),
            ])
            factor = match_ye_factor(blob)
            if factor:
                break
        cnt = active_errors.get("YE") or active_warnings.get("YE")
        sev = "critical" if ye_kind == "error" else "medium"
        if factor:
            fix = "; ".join(factor["fix"][:4])
            line = (
                f"[{ye_kind.upper()}] YE laser {ye_kind} x{cnt}: \"{factor['factor']}\" "
                f"- {factor['meaning']}. Likely: {factor['causes'][0]}. "
                f"Steps: {fix}."
            )
        else:
            line = (
                f"[{ye_kind.upper()}] YE laser {ye_kind} x{cnt}. Sub-factor not in this export; "
                f"read the Detailed Laser Log (DR ST / LD Err ST) and match against the laser factor table."
            )
        findings.append({"sev": sev, "kind": ye_kind, "line": line})
        notable = notable or ye_kind == "error"

    # 3) I2C decode.
    if "II" in active_errors:
        codes.append("II")
        note = None
        for ev in _iter_events(parsed):
            if ev.get("errCode") == "II" and ev.get("factor"):
                note = decode_i2c(ev.get("factor"))
                if note:
                    break
        cnt = active_errors["II"]
        line = f"[ERROR] II I2C Error x{cnt} (communication)."
        if note:
            line += f" {note}"
        else:
            line += " Identify the device via the service-manual slave-address list."
        findings.append({"sev": "high", "kind": "error", "line": line})
        notable = True

    # 4) Thermal level (refines a TH finding when the log carries a level).
    th_level = _max_th_level(parsed)
    if th_level is not None and th_level >= 3:
        note = th_level_note(th_level)
        sev = "critical" if th_level >= 5 else "high" if th_level == 4 else "medium"
        findings.append({"sev": sev, "kind": "thermal", "line": f"[THERMAL] {note}."})
        notable = True
    elif summary.get("temp_anomalies") and "TH" not in active_errors:
        findings.append({"sev": "medium", "kind": "thermal",
                         "line": "[THERMAL] sensor readings above 80C in the event log; check cooling/airflow."})

    # 5) Warning counters worth surfacing (informational, not a fault on their own).
    for code, count in active_warnings.items():
        if code in ("YE",):  # already decoded above
            continue
        name = WARNING_CODES.get(code, f"{code} warning")
        codes.append(code)
        findings.append({"sev": "info", "kind": "warning",
                         "line": f"[WARNING] {code} {name} x{count} (projection continues, degraded)."})

    # 6) Abnormal shutdown rate.
    pct = summary.get("abnormal_shutdown_percentage")
    if pct is not None and pct >= 5:
        findings.append({"sev": "medium", "kind": "shutdown",
                         "line": f"[SHUTDOWN] abnormal shutdowns {pct}% of laser cycles (elevated)."})
        notable = True

    # 7) Firmware staleness (soft nudge only).
    fwv = fw_value(summary.get("fw_version") or "")
    if fwv is not None and fwv < FW_FIX_BASELINE:
        findings.append({"sev": "info", "kind": "firmware",
                         "line": f"[FW] firmware V{fwv} predates common laser/thermal fixes (V{FW_FIX_BASELINE}+); update before any hardware swap."})

    if not findings:
        return {"notable": False, "summary": "", "findings": [], "severity": "info", "text": "", "codes": []}

    # Overall severity = highest among findings.
    overall = max(findings, key=lambda f: SEVERITY_ORDER.get(f["sev"], 0))["sev"]
    # Headline = highest-severity error/laser/thermal line, else first.
    headline = max(findings, key=lambda f: SEVERITY_ORDER.get(f["sev"], 0))["line"]

    lines = [f["line"] for f in findings]
    text_parts = ["IPS LOG FINDINGS (decoded via the IPS error dictionary):"]
    text_parts += [f"  - {ln}" for ln in lines]
    text_parts.append(
        "  Note: Error = projection stops to protect the unit; "
        "Warning = projection continues with a limitation."
    )

    return {
        "notable": notable,
        "summary": headline,
        "findings": lines,
        "severity": overall,
        "text": "\n".join(text_parts),
        "codes": sorted(set(codes)),
    }
