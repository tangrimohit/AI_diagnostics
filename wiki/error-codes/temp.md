---
type: error_code
code: TH
aliases: [TH, Temp]
category: thermal
severity: high
---

# TH (Temp) — Internal overheat (with Warning state)

> **Scope, read first.** This code also appears on laser projectors, where its causes and replacement parts differ (liquid-cooling coupler, C SYSTEM ASSY, LD thermal chain, and different boards). The causes, sequences, and part numbers below are for the lamp 3LCD chassis family (for example EB-X49). For a laser model (large-venue, ultra-short-throw, installation, or portable laser), follow that model's platform family page error reference instead, and do not order the lamp part numbers listed here.

Per the intermediate IPS Tool training, **TH has both Error and Warning levels.** The thermistor temperature state is recorded as a level T1 to T5 ("Level nn; over 3 means the temperature is higher than normal"):

- T1-T2: Normal
- T3: Warning threshold (high temperature warning)
- T4: High (pre-error)
- T5: Error threshold (internal overheat, shutdown)

AKARI's decoder reads the highest TH level present in the log and weighs T3+ as notable. Thresholds vary per model and per thermistor location (PS thermistor, MAB thermistor, board thermistor, FAN, etc.).

Reported by the projector when an internal temperature reading exceeds the threshold. According to the H971-series Optical Engine Repair Manual (chapter 2.2.1), when the error occurs **with no observable abnormality of the product**, the cause is a **MA Board circuit error**, not actual overheating.

## What it means

Either the projector really is too hot (real thermal event), or the MA Board's temperature-sensing circuit is misreading. Distinguish by feel and by recent operating history before pulling parts.

## Common causes

1. **Operating environment** — ambient temperature out of spec, projector near a heat source, blocked by furniture.
2. **Clogged air intake** — remove obstructions near the intake/exhaust ports.
3. **Dirty air filter** — clean or replace the air filter.
4. **MA Board failure** — when none of the above explain the heat reading. Source: H971 manual p33: "MA Board circuit error."

Use the **Temperature log conversion tool** (see temperature log conversion tool) to convert raw `temp?` log values into thermistor names + actual degrees, so you can see whether the heat is localized to one thermistor or system-wide.

## Standard resolution sequence

1. Confirm whether the unit is actually hot (touch the chassis after a power-off, check vents for blockage and dust).
2. Verify high-altitude mode setting matches the actual altitude.
3. Pull the IPS Tool TSV log and look for temperature counters / thermistor readings inconsistent with environmental conditions.
4. Clean filter and cooling path. Run a soak test.
5. If the error recurs without real overheating, **replace the MA Board** (PN-1892734 for the X49 family).

## Related pages

- fan temperature
- main board failures
- [[wiki/error-codes/fan]]
- [[wiki/error-codes/thermistor]]
