"""Condition Diagnosis gate (IPS Tool 2.4.2 feature).

Decides WHEN AKARI should ask the engineer to run the IPS Tool "Condition
Diagnosis" measurement. It must not fire on every fault: the feature only
answers "LSM vs optical engine (or no part)" on image-quality complaints on
supported laser models. Thermal, fan, I2C, power, network, HDMI and lamp
models never trigger it.

Deterministic, no model involvement. Supported-model data lives in
``cd_models.json`` next to this file (built by scripts/build_cd_models.py from
the official workbook).

Opsec: technical content only, no internal codenames, no case references.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional

_MODELS_PATH = Path(__file__).resolve().parent / "cd_models.json"

_models_cache: Optional[dict[str, dict[str, Any]]] = None


def _load_models() -> dict[str, dict[str, Any]]:
    global _models_cache
    if _models_cache is None:
        try:
            doc = json.loads(_MODELS_PATH.read_text(encoding="utf-8"))
            _models_cache = {m["model"].upper(): m for m in doc.get("models", [])}
        except Exception:
            _models_cache = {}
    return _models_cache


def reload_models() -> None:
    global _models_cache
    _models_cache = None


def model_info(model: Optional[str]) -> Optional[dict[str, Any]]:
    """Supported-model entry for a canonical model code (e.g. "EB-L735U"),
    or None if the model is not in the Condition Diagnosis list."""
    if not model:
        return None
    return _load_models().get(model.upper().replace(" ", ""))


def is_supported(model: Optional[str]) -> bool:
    return model_info(model) is not None


# Symptom classes the feature covers. Each class is a regex over the
# engineer's problem text (lowercased). Flicker is included because the
# workbook has a flicker flow next to the value rules, even though the values
# themselves do not judge flicker.
SYMPTOM_CLASSES: dict[str, re.Pattern] = {
    # "bright" root alone is enough (an engineer who types "brightness" on a
    # laser model is chasing output), plus the common misspellings seen in
    # real queries (brigtness, brigthness, brightnes).
    "brightness": re.compile(
        r"\b(dim(mer|ming)?|dark(er|ness)?|brigh?t\w*|brigtn\w*|brigthn\w*|lumens?|"
        r"light\s*output|output\s*(drop|low)|luminan\w*)\b"
    ),
    "color": re.compile(
        r"\b(yellow(ish)?|blu(e|ish)\s*(tint|cast|image|picture|hue)|bluish|colou?r\s*(shift|cast|tint|"
        r"problem|issue|wrong|off|balance)|tint|hue|white\s*balance|discolou?r(ed|ation)?)\b"
    ),
    "uniformity": re.compile(
        r"\b(uniformity|non-?uniform|uneven\s*(colou?r|brightness|image)|magenta|cyan|"
        r"corner[s]?\s*(dark|pink|green|yellow|blue)|patch(y|es))\b"
    ),
    "flicker": re.compile(r"\b(flicker(ing|s)?|flash(ing|es)?\s*(image|picture|brightness)|pulsat(e|ing))\b"),
}

# Symptom words that mean the complaint is NOT an image-quality one even if a
# colour word also appears (e.g. "fan noise, screen went dark then off").
_EXCLUDE_RE = re.compile(
    r"\b(no\s*power|won'?t\s*(turn\s*on|power|start)|dead|no\s*image|no\s*picture|"
    r"overheat|temperatur|thermal|fan\s*(error|noise|fail)|i2c|hdmi|signal|usb|network|"
    r"wifi|wireless|lens\s*shift|shutter|reboot|restart|shuts?\s*down)\b",
    re.IGNORECASE,
)

# IPS log hints (decoded finding lines) that point at the light-source path on
# their own, even when the typed symptom is vague.
_LOG_HINT_RE = re.compile(
    r"(FLB\b|Forced Low Brightness|Balance_LightOutput|Source\s*War|light\s*output\s*(low|unbalanced))",
    re.IGNORECASE,
)


def classify_symptom(problem: Optional[str]) -> list[str]:
    """Image-quality symptom classes found in the problem text (may be empty)."""
    text = (problem or "").lower()
    if not text:
        return []
    return [name for name, rx in SYMPTOM_CLASSES.items() if rx.search(text)]


def should_suggest(
    model: Optional[str],
    problem: Optional[str],
    ips_findings: Optional[dict[str, Any]] = None,
    cd_values: Optional[dict[str, Any]] = None,
) -> tuple[bool, str, list[str]]:
    """Return (suggest, reason, symptom_classes).

    suggest is True only when ALL hold:
      - the model is resolved and in the supported list,
      - the complaint is an image-quality one (typed symptom class) OR the
        decoded IPS log carries a light-source hint,
      - the exclusion vocabulary does not dominate the complaint,
      - no Condition Diagnosis values were supplied yet.
    """
    if cd_values:
        return False, "cd_values_present", []
    info = model_info(model)
    if not info:
        return False, "model_unsupported_or_unknown", []
    classes = classify_symptom(problem)
    excluded = bool(_EXCLUDE_RE.search(problem or ""))
    log_hint = False
    if ips_findings:
        blob = " ".join(ips_findings.get("findings") or []) + " " + (ips_findings.get("text") or "")
        log_hint = bool(_LOG_HINT_RE.search(blob))
    if classes and not excluded:
        return True, "symptom:" + "+".join(classes), classes
    if log_hint and not excluded:
        return True, "log_hint", classes
    return False, "not_image_quality", classes


def build_message(
    model: str,
    classes: list[str],
    *,
    warmup_minutes: int,
    help_url: str,
) -> str:
    info = model_info(model) or {}
    fix = info.get("light_source") == "FIX"
    oe_label = "OE&LSM" if fix else "OE"
    what = ", ".join(classes) if classes else "this image-quality symptom"
    parts = [
        f"For {what} on the {model}, run Condition Diagnosis in the IPS Tool (v2.4.2; check the "
        f"version in the title bar, an auto-updated older build can hide the button). "
        f"Warm the unit up for at least {warmup_minutes} minutes first, then press Execute and enter "
        f"the values here: LD calibration, LDDR, {oe_label} %, Sensor %, LSM B/Y, and the colour "
        f"cast you actually see on screen. It separates a light-source fault from an optical-engine "
        f"fault before any module is replaced."
    ]
    if "flicker" in classes:
        parts.append(
            "Flicker is not judged by these values; use the flicker steps (brightness mode Normal, "
            "then single-colour R/G/B patterns) alongside."
        )
    return " ".join(parts)
