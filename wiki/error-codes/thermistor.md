---
type: error_code
keywords: [se, thermistor, panel temperature sensor, lvinr, lvinb, lving, fpc, pop assy, dr-ic, kapton, orange led shutdown]
code: SE
aliases: [SE, Thermistor]
category: sensor
severity: high
---

# SE (Thermistor) — Temperature sensor error

> **Scope, read first.** This code also appears on laser projectors, where the failing thermistor may sit on a different board (TH Board, FAN Board, CIN Board, DIF Board) and require a different assembly. The causes, sequences, and part numbers below are for the lamp 3LCD chassis family (for example EB-X49). For a laser model (large-venue, ultra-short-throw, installation, or portable laser), follow that model's platform family page error reference instead, and do not order the lamp part numbers listed here.

Indicates the light valve thermistor (panel temperature sensor) signal is bad. Hardware: the thermistor is inside the POP Assy / Light Valves, and connects to the MA Board via an FPC (Flexible Printed Circuit) per light valve.

## What it means

Two physical possibilities per H971 manual p33: an FPC connecting a Light Valve to the MA Board is broken (cable failure), or the thermistor inside the Light Valves is broken (sensor element failure). Either way, replacement is at the **POP Assy** level (the sub-assembly containing the light valves) or the **PRJ Lens Assy** depending on which sub-component failed.

## Common causes

1. **Abnormal thermistor connection** — re-seat the thermistor cable.
2. **Thermistor failure** — replace the thermistor.
3. **Failure of the board on which the thermistor is mounted** — replace the board (typically MA Board for board-mounted thermistors, or POP Assy for light-valve thermistors per H971 manual).

For X49 family specifically (H971 manual p33): the issue is most often one of the Light Valve FPCs broken (R/G/B panel FPC, intermittent or fully open) or the thermistor element inside the Light Valves. Replacement is at the POP Assy or PRJ Lens Assy level.

The device code next to the SE error identifies which thermistor; look up in the service manual.

## Standard resolution sequence

1. Pull the IPS Tool TSV log and check whether the error is sporadic or constant (sporadic suggests FPC connection issue; constant suggests thermistor failure).
2. Inspect FPC connectors at the MA Board: re-seat, check for damaged conductors visible on the flex.
3. Replace the **POP Assy** (Projection Optical Pack containing the three light valves with their thermistors and FPCs). See H971 manual section 3.4.3.1.
4. If still failing, replace the **PRJ Lens Assy**.

## Laser home models: SE with an LVIN channel (panel temperature sensor open)

On a laser home-cinema class (EH-LS970), a service bulletin (rank B, 2026-07) describes the Status LED turning orange and a protective shutdown 5 to 10 minutes after power-on with `[ERR][SE] Thermistor (Normal) LVINB[6Dh]` in the log. The channel names the panel: LVINR = R, LVINB = B, LVING = G, never more than one at a time. Cause: insufficient Kapton tape over the DR-IC on the panel COF/FPC assembly at manufacture, so the panel temperature sensor terminal peels and goes open-circuit. Remedy: replace the optical engine (same part number; engines built from August 2026 carry three-layer tape). Do not confuse with the same model's SMF-board thermistor fault, which logs as a TEMP level 5 DMA entry and needs the SMF board, not the engine.

## Related pages

- optical engine failures
- [[wiki/error-codes/temp]]
- [[wiki/error-codes/fan]]
