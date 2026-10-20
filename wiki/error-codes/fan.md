---
type: error_code
code: FN
aliases: [FN, Fan]
category: cooling
severity: high
---

# FN (Fan) — Fan error

> **Scope, read first.** This code also appears on laser projectors, where its causes and replacement parts differ (different fan set and control boards, plus pump fans on liquid-cooled models). The causes, sequences, and part numbers below are for the lamp 3LCD chassis family (for example EB-X49). For a laser model (large-venue, ultra-short-throw, installation, or portable laser), follow that model's platform family page error reference instead, and do not order the lamp part numbers listed here.

Reported when the projector's fan tachometer disagrees with the expected fan state. a reported fault is a real X49 example, IPS Tool log showed `[FN] Fan Error Counter 14 (0x0E)`.

## What it means

Either a real fan failure (bearing seizure, blade damage, connector unseated) OR a MA Board failure where the temperature/fan-control circuit gives bad data.

## Common causes

1. **Too much dust on the fan** — clean it.
2. **Cable connection problem** — re-seat the fan harness at the MA Board.
3. **Fan failure** — replace the fan.
4. **MA Board failure** — per H971 manual p33: "Elements for temperature control on MA Board are broken." Detected by: **error persists after replacing the fan**, replace the MA Board.

The device code next to the FN error in the IPS log identifies which fan is reporting (look it up in the service manual per page 60 of the training).

## Standard resolution sequence

1. Pull IPS Tool TSV log, capture the `[FN]` Fan Error Counter and any sub-codes.
2. Open chassis; inspect each fan for dust, broken blades, free rotation.
3. Re-seat all fan connectors at the MA Board.
4. If a fan is visibly damaged or won't spin freely, replace that fan assembly. Test.
5. If the error persists with healthy/replaced fans, replace the **MA Board** (PN-1892734 for X49 family).

## Related pages

- fan temperature
- main board failures
- [[wiki/error-codes/temp]]
- [[wiki/error-codes/thermistor]]
