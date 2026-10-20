"""IPS Tool TSV log parser.

Field names inside parsed events stay camelCase to match the browser-side
log viewer. Adds:

  - summarize_log(parsed)              compact factual digest as a dict
  - format_summary_for_prompt(summary) ~500-char readable block for the LLM
  - _recover_if_utf16_misread(text)    safety net for clients that read the
                                       UTF-16 LE BOM file without proper
                                       encoding detection

The /diagnose pipeline replaces the previous "dump 8K of raw TSV into the
prompt" with a structured summary so the deeper models (gemma4:e2b on the
Balanced/Deep tiers) stop getting attention-distracted away from the
wiki content section.
"""
from __future__ import annotations

import re
from typing import Any, Optional


# -------------------- encoding safety net --------------------

def _recover_if_utf16_misread(text: str) -> str:
    """If `text` appears to be UTF-16 LE bytes mis-decoded as Latin-1/UTF-8,
    round-trip through latin-1 bytes and re-decode as UTF-16 LE.

    Heuristic: >30% NUL chars implies every-other-byte zeros, which is the
    signature of UTF-16 LE read as a single-byte encoding.
    """
    if not text or len(text) < 10:
        return text
    nul_ratio = text.count("\x00") / len(text)
    if nul_ratio < 0.3:
        return text
    try:
        raw = text.encode("latin-1", errors="ignore")
        if raw.startswith(b"\xff\xfe"):
            decoded = raw[2:].decode("utf-16-le", errors="ignore")
        elif raw.startswith(b"\xfe\xff"):
            decoded = raw[2:].decode("utf-16-be", errors="ignore")
        else:
            decoded = raw.decode("utf-16-le", errors="ignore")
        if decoded.count("\x00") < max(5, len(decoded) * 0.05):
            return decoded
    except Exception:
        pass
    return text


def _strip_bom(text: str) -> str:
    if text and text[0] in ("﻿", "￾"):
        return text[1:]
    return text


# -------------------- hex-array decoders --------------------

def parse_temp_hex(s: str) -> Optional[list[dict[str, Any]]]:
    """Decode 2-char hex temperature pairs, possibly across multiple @-sep sections.

    Mirrors parseTempHex in the JS. "XX" and "FF" become None; values must be
    in (0, 200) to be kept, otherwise None.
    Returns list of {s: section_index, v: [int|None,...]} or None.
    """
    if not s or s == "-----":
        return None
    out: list[dict[str, Any]] = []
    sections = s.split("@")
    for idx, sec in enumerate(sections):
        if not sec:
            continue
        vals: list[Optional[int]] = []
        for j in range(0, len(sec), 2):
            p = sec[j:j + 2]
            if p in ("XX", "FF"):
                vals.append(None)
            else:
                try:
                    v = int(p, 16)
                except ValueError:
                    vals.append(None)
                    continue
                vals.append(v if 0 < v < 200 else None)
        if any(v is not None for v in vals):
            out.append({"s": idx, "v": vals})
    return out or None


def parse_fan_hex(s: str) -> Optional[list[int]]:
    """Decode 4-char hex fan RPM chunks. Returns list of ints or None."""
    if not s:
        return None
    rpms: list[int] = []
    for j in range(0, len(s), 4):
        chunk = s[j:j + 4]
        if len(chunk) == 4:
            try:
                rpms.append(int(chunk, 16))
            except ValueError:
                pass
    return rpms if any(v > 0 for v in rpms) else None


# -------------------- per-event parser --------------------

_EVT_DATE_RE = re.compile(
    r":D\s+(?:V(\S+)\s+(\S+)\s+)?(\S+)\s+(\S+)\s+T\s+(\S+)\s+L\s+(\S+)\s+P\s+(\S+)"
)
# NOTE: the JS source has `(\S*)` for the errSub group, which silently drops
# data on events whose errSub contains a space (e.g. `[LF]Lamp On (WarmUp)`,
# `[FN]Fan Stop (Off)`). Switched to `([^(]*?)` so multi-word errSub captures
# correctly. Still trims via \s* before the opening paren, so `Temp (Normal)`
# still gives errSub="Temp" — unchanged for events that DID parse in the JS.
_EVT_ERR_RE = re.compile(
    r"\[(ERR|WAR)\]\s*\[(\w+)\]([^(]*?)\s*\((\w+)\)\s*(.*?),?\s*PwrOnCont\s*=\s*(\d+)"
)
_EVT_FACTOR_RE = re.compile(r"Error factor\s*=\s*(.*)", re.IGNORECASE)
_EVT_LASERINFO_RE = re.compile(r"\[Laser Info\]\s*(.*)")
_EVT_SIGNAL_RE = re.compile(r"\[SIGNAL\]\s*(.*)")
_EVT_CMODE_RE = re.compile(r"\[CMODE\]\s*(.*)")
_EVT_TEMP_RE = re.compile(r"temp\?\s*(\S+)")
_EVT_FAN_RE = re.compile(r"fanrevo\?\s*(\S+)")
_EVT_ANGLE_RE = re.compile(r"angle\s+(.*)")
_LD_FIELDS: list[tuple[str, re.Pattern[str]]] = [
    ("lddrVer",   re.compile(r"LDDR Ver\s+(.*)")),
    ("drSt",      re.compile(r"DR ST\s+(.*)")),
    ("errSt",     re.compile(r"Err ST\s+(.*)")),
    ("errId",     re.compile(r"Err ID\s+(.*)")),
    ("drvType",   re.compile(r"Drv Type\s+(.*)")),
    ("lightSrc",  re.compile(r"LightSource ST\s+(.*)")),
    ("rSensor",   re.compile(r"R SnsrVal\s+(.*)")),
    ("bSensor",   re.compile(r"B SnsrVal\s+(.*)")),
    ("timing",    re.compile(r"Detected Timing\s+(.*)")),
]


def parse_evt(text: str) -> dict[str, Any]:
    """Per-event parser. Mirrors parseEvt in the JS."""
    e: dict[str, Any] = {
        "raw": text,
        "date": "", "time": "",
        "totalTime": "", "laserTime": "", "powerTime": "",
        "fwVersion": "", "errType": "", "errCode": "", "errSub": "",
        "state": "", "component": "", "pwrOnCont": "", "factor": "",
        "angle": "", "temp": "", "fan": "",
        "parsedTemp": None, "parsedFan": None,
        "laserInfo": "", "ld": {},
    }

    d = _EVT_DATE_RE.search(text)
    if d:
        e["fwVersion"] = d.group(1) or ""
        date_raw = d.group(3) or ""
        time_raw = d.group(4) or ""
        if date_raw and date_raw != "--------":
            e["date"] = re.sub(r"(\d{4})(\d{2})(\d{2})", r"\1-\2-\3", date_raw)
        if time_raw and time_raw != "--_--_--":
            e["time"] = time_raw.replace("_", ":")
        e["totalTime"] = d.group(5)
        e["laserTime"] = d.group(6)
        e["powerTime"] = d.group(7)

    em = _EVT_ERR_RE.search(text)
    if em:
        e["errType"] = em.group(1)
        e["errCode"] = em.group(2)
        e["errSub"] = em.group(3) or ""
        e["state"] = em.group(4)
        e["component"] = re.sub(r",\s*$", "", em.group(5)).strip()
        e["pwrOnCont"] = em.group(6)

    fm = _EVT_FACTOR_RE.search(text)
    if fm:
        e["factor"] = fm.group(1).strip()

    lm = _EVT_LASERINFO_RE.search(text)
    if lm:
        e["laserInfo"] = lm.group(1).strip()
        e["errCode"] = e["errCode"] or "YE"

    ld: dict[str, str] = {}
    for key, pat in _LD_FIELDS:
        m = pat.search(text)
        ld[key] = m.group(1).strip() if m else ""
    e["ld"] = ld

    sm = _EVT_SIGNAL_RE.search(text)
    if sm:
        e["component"] = sm.group(1).strip()
    cm = _EVT_CMODE_RE.search(text)
    if cm:
        e["component"] = "CMode: " + cm.group(1).strip()

    am = _EVT_ANGLE_RE.search(text)
    if am:
        e["angle"] = am.group(1).strip()

    tm = _EVT_TEMP_RE.search(text)
    if tm:
        e["temp"] = tm.group(1)
        e["parsedTemp"] = parse_temp_hex(tm.group(1))
    fnm = _EVT_FAN_RE.search(text)
    if fnm:
        e["fan"] = fnm.group(1)
        e["parsedFan"] = parse_fan_hex(fnm.group(1))

    return e


# -------------------- top-level TSV parser --------------------

_TSV_TRIPLE_RE = re.compile(r'^"([^"]*)"\t"([^"]*)"\t"?([\s\S]*)')
_TSV_TRIPLE_OPEN_RE = re.compile(r'^"[^"]*"\t"[^"]*"\t"')
_TSV_MODEL_LINE_RE = re.compile(r'^"\t"')
_TSV_MODEL_CAPTURE_RE = re.compile(r'"\t"([^"]+)"')
_TSV_VER_RE = re.compile(r'^"?VER=')
_TSV_DEFINE_FILE_RE = re.compile(r"^\*\* Define File")
_TSV_IPS_VERSION_RE = re.compile(r"^\*\* IPS Tool Version")
_TSV_HEADER_KV_RE = re.compile(r":\s*(.+)")
_TSV_MULTIMODEL_RE = re.compile(r'^"([A-Z0-9_]+)"\t"([^"]+)"\s*$')

_GROUP_LASER_REPL_RE = re.compile(r"Laser.*[Rr]eplacement")
_GROUP_AREA_RE = re.compile(r"^Area\d+$")
_ITEM_ERR_WAR_RE = re.compile(r"Error.*Warning", re.IGNORECASE)
_ITEM_DETAILED_LASER_RE = re.compile(r"Detailed.*Laser", re.IGNORECASE)
_ITEM_OPERATION_RE = re.compile(r"Operation", re.IGNORECASE)
_BRACKET_CODE_RE = re.compile(r"\[(\w+)\]")
_LEADING_DIGITS_RE = re.compile(r"^(\d+)")


def _assemble_multiline(lines: list[str]) -> list[str]:
    """Reconstruct multi-line quoted values back into single logical lines.

    A line starting with `"group"\\t"item"\\t"...` where the third field does
    not close its quote on the same line continues until a line that is just
    `"`. Same logic as the JS while-loop in parseTSV.
    """
    out: list[str] = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        if _TSV_TRIPLE_OPEN_RE.match(line):
            first_tab = line.find("\t")
            second_tab = line.find("\t", first_tab + 1)
            after_second = line[second_tab + 1:] if second_tab >= 0 else ""
            stripped = after_second[1:] if after_second.startswith('"') else after_second
            if not stripped.endswith('"') or stripped == "":
                full = line
                i += 1
                while i < n:
                    if lines[i].strip() == '"':
                        full += "\n" + lines[i]
                        i += 1
                        break
                    full += "\n" + lines[i]
                    i += 1
                out.append(full)
                continue
        out.append(line)
        i += 1
    return out


def parse_tsv(text: str) -> dict[str, Any]:
    """Top-level TSV parser. Mirrors parseTSV in the JS.

    Returned shape (camelCase preserved from JS for parity):
        header: {defineFile, ipsVersion, fwVersions, fwMain, fwMainShort}
        model:  str
        projector: dict[str, str]
        laser:     dict[str, str]
        panel:     dict[str, str]
        laserReplacement: list[{item, value}]
        errorCounters:    list[{code, name, count}]
        warningCounters:  list[{code, name, count}]
        events:           list[parsed event dicts]
        detailedLaser:    list[parsed event dicts]
        operationInfo:    list[parsed event dicts]
        settings:         dict[str, str]
    """
    text = _strip_bom(_recover_if_utf16_misread(text or ""))
    data: dict[str, Any] = {
        "header": {"defineFile": "", "ipsVersion": "", "fwVersions": [], "fwMain": "", "fwMainShort": ""},
        "model": "",
        "projector": {},
        "laser": {},
        "panel": {},
        "laserReplacement": [],
        "errorCounters": [],
        "warningCounters": [],
        "events": [],
        "detailedLaser": [],
        "operationInfo": [],
        "settings": {},
    }
    raw = text.replace("\r\n", "\n").replace("\r", "\n")
    raw_lines = raw.split("\n")
    assembled = _assemble_multiline(raw_lines)

    for line in assembled:
        t = line.strip()
        if not t:
            continue

        if _TSV_DEFINE_FILE_RE.match(t):
            m = _TSV_HEADER_KV_RE.search(t)
            if m:
                data["header"]["defineFile"] = m.group(1).strip()
            continue
        if _TSV_IPS_VERSION_RE.match(t):
            m = _TSV_HEADER_KV_RE.search(t)
            if m:
                data["header"]["ipsVersion"] = m.group(1).strip()
            continue
        if _TSV_VER_RE.match(t):
            data["header"]["fwVersions"].append(t.lstrip('"').rstrip('"').strip())
            continue
        if _TSV_MODEL_LINE_RE.match(t):
            m = _TSV_MODEL_CAPTURE_RE.search(t)
            if m:
                data["model"] = m.group(1)
            continue

        m_triple = _TSV_TRIPLE_RE.match(t)
        if not m_triple:
            # Multi-model header line like `"0106GPV213WW00"\t"EB-E01/.../VS260"`
            # — only two quoted fields, no third. Use it for `model` if we
            # haven't found one yet. (Extension to the JS, needed because the
            # JS model-line regex only matches the empty-first-field variant.)
            if not data["model"]:
                mm = _TSV_MULTIMODEL_RE.match(t)
                if mm:
                    data["model"] = mm.group(2)
            continue

        group = m_triple.group(1)
        item = m_triple.group(2)
        value = re.sub(r'"\s*$', "", m_triple.group(3)).strip()

        # Real exports use both with-period and without-period group names:
        # "Lamp Information."  vs  "Laser Information"
        group_canon = group.rstrip(".")
        if group_canon == "Projector Information":
            data["projector"][item] = value
        elif group_canon in ("Laser Information", "Lamp Information"):
            data["laser"][item] = value
        elif group_canon == "Panel Information":
            data["panel"][item] = value
        elif _GROUP_LASER_REPL_RE.search(group):
            data["laserReplacement"].append({"item": item, "value": value})
        elif group == "Error Counter":
            cm = _BRACKET_CODE_RE.search(item)
            code = cm.group(1) if cm else item[:4]
            nm = _LEADING_DIGITS_RE.match(value)
            data["errorCounters"].append({
                "code": code,
                "name": item,
                "count": int(nm.group(1)) if nm else 0,
            })
        elif group == "Warning Counter":
            cm = _BRACKET_CODE_RE.search(item)
            if cm:
                code = cm.group(1)
            elif "forced" in item.lower():
                code = "FLB"
            else:
                code = item[:3]
            nm = _LEADING_DIGITS_RE.match(value)
            data["warningCounters"].append({
                "code": code,
                "name": item,
                "count": int(nm.group(1)) if nm else 0,
            })
        elif _GROUP_AREA_RE.match(group) and _ITEM_ERR_WAR_RE.search(item):
            data["events"].append(parse_evt(value))
        elif _GROUP_AREA_RE.match(group) and _ITEM_DETAILED_LASER_RE.search(item):
            data["detailedLaser"].append(parse_evt(value))
        elif _GROUP_AREA_RE.match(group) and _ITEM_OPERATION_RE.search(item):
            data["operationInfo"].append(parse_evt(value))
        elif group == "Projector Setting Data":
            data["settings"][item] = value

    non_empty = [v for v in data["header"]["fwVersions"] if "----" not in v]
    if non_empty:
        data["header"]["fwMain"] = non_empty[0].replace("VER=", "")
        vm = re.search(r"V(\d+)$", data["header"]["fwMain"])
        if vm:
            data["header"]["fwMainShort"] = "V" + vm.group(1)
    return data


# -------------------- small helpers (parity with JS) --------------------

def parse_hrs(s: str) -> float:
    """e.g. '953h 25m 24s' -> 953.4166. Mirrors parseHrs in the JS."""
    if not s:
        return 0.0
    h = re.search(r"(\d+)h", s)
    m = re.search(r"(\d+)m", s)
    return (int(h.group(1)) if h else 0) + (int(m.group(1)) / 60 if m else 0)


def parse_cnt(s: Optional[str]) -> Optional[int]:
    if not s:
        return None
    m = _LEADING_DIGITS_RE.match(s)
    return int(m.group(1)) if m else None


def get_power(d: dict[str, Any]) -> dict[str, Any]:
    """Laser/Lamp ON-OFF counter analysis. Mirrors getPower in the JS but
    also reads Lamp* keys (lamp projectors use those instead of Laser*)."""
    laser = d["laser"]
    on = parse_cnt(
        laser.get("Laser ON Counter") or laser.get("Laser ON Times Counter")
        or laser.get("Lamp ON Counter") or laser.get("Lamp ON Times Counter")
    )
    off = parse_cnt(
        laser.get("Laser OFF Counter") or laser.get("Laser OFF Times Counter")
        or laser.get("Lamp OFF Counter") or laser.get("Lamp OFF Times Counter")
    )
    p_on = parse_cnt(d["projector"].get("Power ON Counter"))
    abn = (on - off) if (on is not None and off is not None) else None
    pct: Optional[float] = None
    if abn is not None and on and on > 0:
        pct = round((abn / on) * 100, 1)
    return {"on": on, "off": off, "pOn": p_on, "abn": abn, "pct": pct}


# -------------------- summary for LLM prompt --------------------

def summarize_log(parsed: dict[str, Any]) -> dict[str, Any]:
    """Compact factual digest of a parsed TSV. The result is the dict we send
    into the LLM prompt (after format_summary_for_prompt). No speculation."""
    pwr = get_power(parsed)
    proj = parsed["projector"]
    laser = parsed["laser"]
    total_op_str = (
        proj.get("Total Op.Time")
        or proj.get("Total Op.Time()")
        or proj.get("Accum. Total Op Time()")
        or proj.get("Accum. Total Op Time")
        or ""
    )
    light_src_str = (
        laser.get("Laser Op.Time(Conversion)")
        or laser.get("Lamp Op. Time(C)")
        or laser.get("Lamp Op.Time()")
        or laser.get("Lamp Op.Time")
        or laser.get("Total Op.Time()")
        or laser.get("Total Op.Time")
        or ""
    )

    active_errors = {e["code"]: e["count"] for e in parsed["errorCounters"] if e["count"] > 0}
    active_warnings = {w["code"]: w["count"] for w in parsed["warningCounters"] if w["count"] > 0}

    # Last few events. parse_evt fills date when the device has an RTC; lamp
    # projectors without an RTC leave date empty and the only ordering signal
    # is totalTime. Use file order for undated events and date+time for dated.
    events = list(parsed["events"])
    dated = [e for e in events if e.get("date")]
    undated = [e for e in events if not e.get("date")]
    dated.sort(key=lambda e: (e.get("date", ""), e.get("time", "")))
    recent = (dated + undated)[-5:]
    recent_brief = []
    for ev in recent:
        recent_brief.append({
            "date": ev.get("date") or "",
            "time": ev.get("time") or "",
            "totalTime": ev.get("totalTime") or "",
            "pwrOnCont": ev.get("pwrOnCont") or "",
            "errType": ev.get("errType") or "",
            "errCode": ev.get("errCode") or "",
            "errSub": (ev.get("errSub") or "")[:40],
            "state": ev.get("state") or "",
            "factor": (ev.get("factor") or "")[:120],
            "component": (ev.get("component") or "")[:80],
        })

    temp_anomalies = any(
        (ev.get("parsedTemp") and any(s["v"] and any(v and v > 80 for v in s["v"]) for s in ev["parsedTemp"]))
        for ev in (parsed["events"] + parsed["detailedLaser"])
    )

    return {
        "model": parsed.get("model") or "",
        "serial_number": parsed["projector"].get("SerialNo", ""),
        "fw_version": parsed["header"].get("fwMain") or parsed["header"].get("fwMainShort") or "",
        "ips_tool_version": parsed["header"].get("ipsVersion", ""),
        "total_operation_str": total_op_str,
        "light_source_hours_str": light_src_str,
        "power_on_counter": pwr.get("pOn"),
        "laser_on_counter": pwr.get("on"),
        "laser_off_counter": pwr.get("off"),
        "abnormal_shutdowns": pwr.get("abn"),
        "abnormal_shutdown_percentage": pwr.get("pct"),
        "active_error_counts": active_errors,
        "active_warning_counts": active_warnings,
        "recent_events": recent_brief,
        "temp_anomalies": bool(temp_anomalies),
        "event_count": len(parsed["events"]),
        "detailed_laser_count": len(parsed["detailedLaser"]),
        "operation_info_count": len(parsed["operationInfo"]),
    }


def format_summary_for_prompt(summary: dict[str, Any]) -> str:
    """Render summarize_log() output as a compact readable text block.

    Intentionally omits the serial number (kept for audit only, not sent to
    the LLM). Keeps the whole block to a few hundred chars at most.
    """
    lines: list[str] = ["IPS LOG SUMMARY:"]
    model = summary.get("model") or "(not determined from log)"
    lines.append(f"  Device family: {model}")
    fw = summary.get("fw_version") or "(unknown)"
    lines.append(f"  Firmware: {fw}")
    if summary.get("total_operation_str"):
        lines.append(f"  Total operation: {summary['total_operation_str']}")
    if summary.get("light_source_hours_str"):
        lines.append(f"  Light source: {summary['light_source_hours_str']}")
    if summary.get("power_on_counter") is not None:
        lines.append(f"  Power-on count: {summary['power_on_counter']}")
    abn = summary.get("abnormal_shutdowns")
    pct = summary.get("abnormal_shutdown_percentage")
    if abn is not None:
        if pct is not None:
            lines.append(f"  Abnormal shutdowns: {abn} ({pct}% of laser cycles)")
        else:
            lines.append(f"  Abnormal shutdowns: {abn}")

    aec = summary.get("active_error_counts") or {}
    if aec:
        lines.append("  Active error counters: " + ", ".join(f"{k} x{v}" for k, v in aec.items()))
    else:
        lines.append("  Active error counters: none")
    awc = summary.get("active_warning_counts") or {}
    if awc:
        lines.append("  Active warning counters: " + ", ".join(f"{k} x{v}" for k, v in awc.items()))

    if summary.get("temp_anomalies"):
        lines.append("  Temperature anomalies: yes (sensor readings above 80C in event log)")

    recent = summary.get("recent_events") or []
    if recent:
        lines.append("  Recent events:")
        for ev in recent:
            stamp = (ev.get("date") + " " + ev.get("time", "")).strip()
            if not stamp and ev.get("totalTime"):
                stamp = f"@T={ev['totalTime']}"
            stamp = stamp or "(undated)"
            code = ev.get("errCode") or "?"
            if ev.get("errSub"):
                code = f"{code}/{ev['errSub']}"
            etype = ev.get("errType") or "?"
            extra = []
            if ev.get("state"): extra.append(f"state={ev['state']}")
            if ev.get("factor"): extra.append(f"factor={ev['factor']}")
            if ev.get("pwrOnCont"): extra.append(f"PwrOnCont={ev['pwrOnCont']}")
            tail = (" " + "; ".join(extra)) if extra else ""
            lines.append(f"    - {stamp}  [{etype}][{code}]{tail}")
    else:
        lines.append("  Recent events: none in log")

    return "\n".join(lines)


# -------------------- error codes for retrieval --------------------

def error_codes_from_summary(summary: dict[str, Any]) -> list[str]:
    """Active error + warning codes from the summary, for use by the
    /diagnose retrieval pipeline's entity-extraction step."""
    codes = set()
    for k in (summary.get("active_error_counts") or {}).keys():
        if k:
            codes.add(k.upper())
    for k in (summary.get("active_warning_counts") or {}).keys():
        if k:
            codes.add(k.upper())
    return sorted(codes)
