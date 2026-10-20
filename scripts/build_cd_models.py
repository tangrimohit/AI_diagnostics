"""Build api/cd_models.json (Condition Diagnosis supported-model list).

Source: the official IPS image troubleshooting workbook, "Applicable model"
sheet (series / model name / H code / light source). Run once per workbook
revision:

    python scripts/build_cd_models.py "<path to IPS_Image_trouble_shooting_X.xlsx>"

Opsec: internal series codenames are NOT written to the output. Only model
names, H-codes and the light-source structure (FIX vs PHW) are kept.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import openpyxl

OUT = Path(__file__).resolve().parent.parent / "api" / "cd_models.json"


def expand_names(raw: str) -> list[str]:
    """'EB/CB-L730U/L735U' -> ['EB-L730U','CB-L730U','EB-L735U','CB-L735U'].
    'Pro L1070U (NL)' -> ['EB-L1070U'] (NA naming mapped to the EU code)."""
    s = raw.replace("／", "/").replace("　", " ").strip()
    s = re.sub(r"\s*\(NL\)\s*", "", s)
    m = re.match(r"^Pro\s+L(\w+)$", s, re.I)
    if m:
        return [f"EB-L{m.group(1).upper()}"]
    m = re.match(r"^([A-Z]{2}(?:/[A-Z]{2})*)-(.+)$", s)
    if not m:
        return [s.upper()]
    prefixes = m.group(1).split("/")
    tails = [t for t in m.group(2).split("/") if t]
    out = []
    for p in prefixes:
        for t in tails:
            out.append(f"{p}-{t}".upper())
    return out


def main(xlsx: str) -> None:
    ws = openpyxl.load_workbook(xlsx, data_only=True)["Applicable model"]
    models: list[dict] = []
    light = ""
    for r in ws.iter_rows(min_row=12, values_only=True):
        name, hcode, ls = r[2], r[3], r[4]
        if ls and str(ls).strip() and str(ls).strip() != "　":
            light = "FIX" if "fix" in str(ls).lower() else "PHW"
        if not name or not hcode:
            continue
        for code in expand_names(str(name)):
            models.append({"model": code, "h_code": str(hcode).strip(), "light_source": light})
    # de-dup keeping first
    seen, uniq = set(), []
    for m in models:
        k = (m["model"], m["h_code"])
        if k in seen:
            continue
        seen.add(k)
        uniq.append(m)
    doc = {
        "_readme": "Condition Diagnosis applicable models (IPS Tool). FIX = fixed phosphor "
                   "(reports OE&LSM; brightness restore = LSM). PHW = phosphor wheel "
                   "(reports OE; brightness restore = optical engine). Rebuild with "
                   "scripts/build_cd_models.py from the official workbook.",
        "workbook_revision": Path(xlsx).stem,
        "restraining_floor_default": 90,
        "models": uniq,
    }
    OUT.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {OUT} ({len(uniq)} models)")


if __name__ == "__main__":
    main(sys.argv[1])
