"""Condition Diagnosis evaluator (IPS Tool 2.4.2 feature), Phase B.

Turns the six on-screen Condition Diagnosis values plus what the engineer
saw into a deterministic verdict: light source module (LSM), optical engine
(OE / POP), no part, calibrate first, or LDDR board. The language model only
writes prose around this; it must copy the verdict, never re-derive numbers.

Rules mirror the manufacturer's reference workbook:
- Warm-up under the policy minutes: results are reference only.
- LD calibration "Not Yet": no baseline, run LD calibration first.
- LDDR "NG": replace the LDDR board before judging anything else.
- OE - Sensor >= gap  -> loss inside the light-source path -> LSM.
- Sensor - actual >= gap (actual brightness from a 9-point measurement)
  -> loss after the sensor -> OE (POP where the model supports it).
- Neither gap -> no part failure (normal ageing).
- OE below the model's restraining floor is deliberate restraining, not a fault.
- LSM B/Y: 110..200 predicts bluish, 50..90 yellowish, 90..110 neutral.
  Prediction matches the seen image -> laser side (OSD light source
  calibration, then LSM). Mismatch, or neutral prediction with a coloured
  image -> OE side (rewrite DR data, then OE / POP).
- Flicker is never judged by the values.

Deterministic, no model involvement, no network. Opsec: technical text only.
"""
from __future__ import annotations

from typing import Any, Optional

from api import cd_gate

COLOR_CHOICES = ("", "neutral", "yellowish", "bluish", "other")

# Flicker flow (workbook flowchart). Not judged by the values; two guided
# questions instead of free text.
FLICKER_NORMAL = ("", "yes", "no")            # does brightness mode Normal clear it
FLICKER_RASTERS = ("", "one", "rg", "all", "none")  # which single-colour rasters flicker


def lumens_from_points(points: list, height_cm: Any, width_cm: Any) -> Optional[float]:
    """Workbook "Brightness calculation sheet": lumens = mean(9 lux) * area(m2).
    Set-up: 60 to 80 inch matt screen, colour mode Dynamic, 100% white, after
    warm-up. Returns None when inputs are incomplete."""
    vals = [_num(x) for x in (points or [])]
    vals = [v for v in vals if v is not None]
    h, w = _num(height_cm), _num(width_cm)
    if len(vals) < 9 or h is None or w is None or h <= 0 or w <= 0:
        return None
    return sum(vals[:9]) / 9.0 * (h / 100.0) * (w / 100.0)


def evaluate_flicker(normal_clears: str, rasters: str) -> Optional[dict[str, Any]]:
    """Deterministic flicker call from the two guided answers."""
    n = str(normal_clears or "").strip().lower()
    r = str(rasters or "").strip().lower()
    if n not in FLICKER_NORMAL or r not in FLICKER_RASTERS or (not n and not r):
        return None
    if n == "yes":
        return {"verdict": "lddr", "part": "laser driver board",
                "text": "Flicker disappears in brightness mode Normal: light-source drive control. Check the laser driver board.",
                "remedy": ["Inspect the laser driver board per the service manual."]}
    if r in ("one", "rg", "all"):
        return {"verdict": "oe", "part": "optical path",
                "text": "One or more colour rasters flicker: fault is inside the optical path.",
                "remedy": ["Isolate with the built-in test pattern, then follow the service-manual optical-path sequence."]}
    if r == "none" and n == "no":
        return {"verdict": "inconclusive", "part": "",
                "text": "No raster flickers and brightness mode Normal does not change it: the flicker is not from the light source or the light valves.",
                "remedy": ["Reproduce with the built-in test pattern and another source; a source or cable flicker is not a projector part."]}
    return None



def _num(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f


def _norm_choice(v: Any, ok_words: tuple[str, ...], bad_words: tuple[str, ...]) -> str:
    """Map free-ish input to 'ok' | 'bad' | ''."""
    s = str(v or "").strip().lower().replace("_", " ")
    if not s:
        return ""
    if s in ok_words:
        return "ok"
    if s in bad_words:
        return "bad"
    return ""


def has_values(values: Optional[dict[str, Any]]) -> bool:
    """True when the engineer actually entered something usable."""
    if not isinstance(values, dict):
        return False
    for k in ("oe_pct", "sensor_pct", "lsm_by", "actual_brightness_pct"):
        if _num(values.get(k)) is not None:
            return True
    for k in ("ld_calibration", "lddr", "flicker_normal_clears", "flicker_rasters"):
        if str(values.get(k) or "").strip():
            return True
    if _num(values.get("measured_lumens")) is not None and _num(values.get("spec_lumens")):
        return True
    return False


def by_prediction(by: Optional[float]) -> str:
    if by is None:
        return ""
    if by >= 110:
        return "bluish"
    if by < 90:
        return "yellowish"
    return "neutral"


def evaluate(
    values: dict[str, Any],
    *,
    model: Optional[str] = None,
    gap_threshold: int = 20,
    warmup_minutes: int = 20,
) -> dict[str, Any]:
    """Return a verdict dict:

    verdict: "lddr" | "calibrate_first" | "lsm" | "oe" | "lsm_and_oe" |
             "no_part" | "inconclusive"
    headline: one sentence
    findings: [str]     what the numbers say, in order
    remedy:   [str]     ordered cheapest first
    caveats:  [str]
    values:   echo of the normalised inputs (for the escalation draft / audit)
    reference_only: bool (warm-up under policy)
    """
    info = cd_gate.model_info(model) or {}
    light = (info.get("light_source") or "").upper()
    oe_label = "OE&LSM" if light == "FIX" else "OE"

    oe = _num(values.get("oe_pct"))
    sensor = _num(values.get("sensor_pct"))
    by = _num(values.get("lsm_by"))
    actual = _num(values.get("actual_brightness_pct"))
    measured_lm = _num(values.get("measured_lumens"))
    spec_lm = _num(values.get("spec_lumens"))
    if actual is None and measured_lm is not None and spec_lm:
        actual = round(measured_lm / spec_lm * 100.0, 1)
    warm = _num(values.get("warmup_minutes"))
    flicker = evaluate_flicker(values.get("flicker_normal_clears"), values.get("flicker_rasters"))
    ld_cal = _norm_choice(values.get("ld_calibration"), ("ok", "yes", "done"), ("not yet", "notyet", "no", "none"))
    lddr = _norm_choice(values.get("lddr"), ("ok",), ("ng", "fail", "bad"))
    seen = str(values.get("observed_color") or "").strip().lower()
    if seen not in COLOR_CHOICES:
        seen = "other"

    findings: list[str] = []
    remedy: list[str] = []
    caveats: list[str] = []
    reference_only = False

    if warm is not None and warm < warmup_minutes:
        reference_only = True
        caveats.append(
            f"Measured after {int(warm)} min warm-up; the rule is {warmup_minutes} min. "
            "Treat this as reference only and re-run after full warm-up."
        )

    echo = {
        "ld_calibration": {"ok": "OK", "bad": "Not Yet"}.get(ld_cal, ""),
        "lddr": {"ok": "OK", "bad": "NG"}.get(lddr, ""),
        "oe_pct": oe, "sensor_pct": sensor, "lsm_by": by,
        "actual_brightness_pct": actual, "observed_color": seen,
        "warmup_minutes": warm, "oe_label": oe_label, "light_source": light or None,
        "measured_lumens": measured_lm, "spec_lumens": spec_lm,
    }
    if measured_lm is not None and spec_lm:
        findings.append(f"Measured {measured_lm:g} lm against a spec of {spec_lm:g} lm: actual brightness {actual:g}%.")

    if lddr == "bad":
        findings.append("LDDR reads NG.")
        remedy.append("Check the laser driver board first; re-run Condition Diagnosis afterwards.")
        return _pack("lddr", "Laser driver board reports a fault: resolve it before judging the light source or optical engine.",
                     findings, remedy, caveats, echo, reference_only)

    if ld_cal == "bad":
        findings.append("LD calibration is Not Yet: there is no baseline to compare against.")
        remedy.append("Run LD calibration first, warm up, then re-run Condition Diagnosis.")
        return _pack("calibrate_first", "No LD calibration baseline: calibrate first, then measure again.",
                     findings, remedy, caveats, echo, reference_only)

    has_numbers = any(v is not None for v in (oe, sensor, by, actual))
    if flicker and not has_numbers:
        findings.append(flicker["text"])
        return _pack(flicker["verdict"], "Flicker flow: " + flicker["text"].split(":")[0] + ".",
                     findings, list(flicker["remedy"]), caveats, dict(echo, flicker=flicker["verdict"]), reference_only)

    lsm_hit = oe is not None and sensor is not None and (oe - sensor) >= gap_threshold
    oe_hit = sensor is not None and actual is not None and (sensor - actual) >= gap_threshold
    if oe is not None and sensor is not None:
        findings.append(f"{oe_label} {oe:g}% vs Sensor {sensor:g}%: drop of {oe - sensor:g} points inside the light-source path (threshold {gap_threshold}).")
    if sensor is not None and actual is not None:
        findings.append(f"Sensor {sensor:g}% vs actual brightness {actual:g}%: drop of {sensor - actual:g} points after the sensor (threshold {gap_threshold}).")
    if by is not None:
        findings.append(f"LSM B/Y {by:g}: the sensors predict a {by_prediction(by)} image.")

    if lsm_hit and oe_hit:
        verdict, head = "lsm_and_oe", "Both stages show loss: light-source path and optical-engine side each exceed the gap."
    elif lsm_hit:
        verdict, head = "lsm", "Loss is inside the light-source path."
    elif oe_hit:
        verdict, head = "oe", "Loss is after the sensor: optical-engine side."
    elif oe is not None and sensor is not None:
        verdict, head = "no_part", "No part failure from the numbers: values are within the allowed range."
    else:
        verdict, head = "inconclusive", "Not enough values to decide; enter OE, Sensor and actual brightness."
    if verdict in ("lsm", "oe", "lsm_and_oe"):
        remedy.append("Clean the optical path and re-run before replacing any module.")
        remedy.append("Follow the service-manual replacement sequence for the indicated stage.")

    if flicker:
        findings.append("Flicker flow: " + flicker["text"])
        echo["flicker"] = flicker["verdict"]
    if not remedy:
        remedy.append("Re-run Condition Diagnosis with the missing values after a full warm-up.")
    return _pack(verdict, head, findings, remedy, caveats, echo, reference_only)



def _pack(verdict, headline, findings, remedy, caveats, echo, reference_only):
    if reference_only:
        headline = "Reference only (short warm-up): " + headline
    return {
        "verdict": verdict,
        "headline": headline,
        "findings": findings,
        "remedy": remedy,
        "caveats": caveats,
        "values": echo,
        "reference_only": reference_only,
    }


def summary_line(result: dict[str, Any]) -> str:
    """Compact one-liner for the escalation draft's error_evidence."""
    v = result.get("values") or {}
    parts = []
    if v.get("ld_calibration"):
        parts.append(f"LD cal {v['ld_calibration']}")
    if v.get("lddr"):
        parts.append(f"LDDR {v['lddr']}")
    if v.get("oe_pct") is not None:
        parts.append(f"{v.get('oe_label') or 'OE'} {v['oe_pct']:g}%")
    if v.get("sensor_pct") is not None:
        parts.append(f"Sensor {v['sensor_pct']:g}%")
    if v.get("lsm_by") is not None:
        parts.append(f"LSM B/Y {v['lsm_by']:g}")
    if v.get("actual_brightness_pct") is not None:
        parts.append(f"actual {v['actual_brightness_pct']:g}%")
    if v.get("observed_color") and v["observed_color"] != "other":
        parts.append(f"image looks {v['observed_color']}")
    if v.get("measured_lumens") is not None and v.get("spec_lumens"):
        parts.append(f"{v['measured_lumens']:g} lm measured vs {v['spec_lumens']:g} lm spec")
    if v.get("flicker"):
        parts.append(f"flicker flow -> {v['flicker']}")
    if v.get("warmup_minutes") is not None:
        parts.append(f"warm-up {v['warmup_minutes']:g} min")
    return "Condition Diagnosis: " + ", ".join(parts) + f". Verdict: {result.get('headline', '')}"
