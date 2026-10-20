---
type: entity
entity_type: platform
keywords: [pu22, large venue laser, burnt connector, burnt cable, burned connection, melted connector, short circuit, ld4 over volt, over voltage, laser driver, lddr, elplw08, lens calibration cannot finish, lens error, lens shift motor, hdmi not working, faulty hdmi, no hdmi, i2c hdmi rx, in789, dif board, ma-if board, f01d, model code isn't match, dr data, adjustment data, oe serial, craft, cat2, connector contact failure, sparks, colour non-uniformity, yellow green patch, cyan cast, side by side clearance, condition diagnosis, colour calibration, elpec01, factory outgoing data, pq2216b, rp error, md board, v2.73, tot reset, memory chip, edge blending reset, 2216821]
---
# Large-venue laser family (PU22 series)

## Summary

Shared diagnostic page for these projectors, which use the same engineering platform and share failure modes and service parts: EB-PU2213B, EB-PU2216B, EB-PU2220B.

## Specifications

Family-wide unless a model is called out. Where members differ, the range or specific model is noted.

| Item | Value |
|---|---|
| Resolution | WUXGA (1920 x 1200), 2,304,000 dots x 3 |
| Aspect ratio | 16:10 |
| LCD panel | 1.0-inch, VA type |
| Focus / zoom | Powered focus, optical zoom 1.0 to 1.6 |
| Light source | Laser diode, wavelength 449 to 461 nm, Class 4 |
| Light source output | EB-PU2220B/PU2120W: max 485 W (48.5 W x10); EB-PU2216B/PU2116W: max 388 W (48.5 W x8); EB-PU2213B/PU2113W: max 291 W (48.5 W x6) |
| Brightness (Normal) | EB-PU2220B: 20,000 lm; EB-PU2216B: 16,000 lm; EB-PU2213B: 13,000 lm |
| Brightness (Quiet/Extended) | EB-PU2220B: 14,000 lm; EB-PU2216B: 11,200 lm; EB-PU2213B: 9,100 lm |
| Brightness (Custom) | EB-PU2220B: 1,600 to 14,000 lm; EB-PU2216B: 1,280 to 11,200 lm; EB-PU2213B: 1,040 to 9,100 lm |
| Key I/O | D-sub 15-pin x1, HDMI Type-A x1 (HDCP 2.3), DVI-D x1 (HDCP 1.4), HDBaseT x1 (HDCP 2.3), BNC x1 (B models), Audio Out x1, RS-232C x1, Remote x1, USB Type-A x2, USB Type-B x1 |
| Network | RJ45 x1, USB Type-A x1 (for wireless LAN unit) |
| Power supply | EB-PU2220B: 100-120V AC ±10% 50/60Hz 12.0A, 200-240V AC ±10% 50/60Hz 6.6A; EB-PU2216B/PU2213B: 100-240V AC ±10% 50/60Hz (11.2-5.0A and 8.9-4.0A respectively) |
| Standby power | Communication On: 2.0 W; Communication Off: 0.4 W |
| Operating temperature | 0 to 50°C up to 2,286 m (7,500 ft); 0 to 45°C above 2,286 m |
| Operating humidity | 20 to 80% (no condensation) |
| Operating altitude | 0 to 3,048 m (10,000 ft) |
| Start-up period | Less than 8 seconds |
| Warm-up period | 20 seconds |
| Cool-down period | Instant off |
| Weight | Approx. 23.7 to 24.4 kg depending on model |

Source: Service Manual p.31-36.

## Error code reference

Display codes shown on the projector and the AS (after service) menu. Source: Service Manual p.78-79.

| Display code | Meaning |
|---|---|
| Temp (TH) | High-temperature error or warning, including laser error caused by temperature |
| Fan (FN) | Fan error |
| Thermistor (SE) | Temperature sensor error |
| Laser (YE) | Laser error or warning |
| Shutter (SH) | Shutter error or warning |
| Pump (FP) | Cooling system error (pump) |
| Voltage (PV) | Power voltage instability error |
| Lens Shift (LP) | Lens shift error |
| Lens Attach (LA) | No lens error |
| Laser CPD (AP) | Retardation plate error |
| Cover Open (LC) | Lamp cover open error |
| RAM (RA) | Internal error (RAM) |
| ROM (RO) | Internal error (ROM) |
| I2C (II) | Internal error (I2C) |
| DR (ID) | Internal error (DR status) |
| (IV) | Internal error (video sub-processor) |
| Sub_Pea3 (RP) | Sub system communication error: lens control device |
| Sub2_Oct (RT) | Sub system communication error: temperature control device |
| EasyMP (IM) | EasyMP internal error (warning) |

## Parts

Key replaceable assemblies and boards. Source: Service Manual Parts List p.442-449 and Repair Overview p.40-41.

- Sealed OPT Engine ASSY (sealed optical engine; covers light valves, shutter, lens shift)
- LSM ASSY (light source module)
- PS LDDR ASSY (power supply / laser driver assembly)
- MA-IF Board ASSY (main board / interface)
- DIF Board, AIF Board, ACN Board (signal/interface boards)
- LDDR Board, LDCN Board, LDCNCN Board, LDPS Board (laser drive chain)
- LMDR Board (motor driver)
- C SYSTEM ASSY and CCS Board (liquid cooling, pump)
- TH Board (thermistor board)
- Fans: Fan TB5010 (MA fan), Fan TB6035, Fan JK10525, plus EX/PS/PHW/C-system fans
- Projection lens (separate; not part of the sealed engine)
- Inner Radiator ASSY, control panel, cases, ducts, nets, and filters

Note on burnt-connector countermeasure (p.40-41): for repair products where a connector may be burnt, the manufacturer specifies replacing the LDDR Board, Cable LDDR-LDCN, LDCN Board, Cable LDCN, and LDCNCN Board with renewed parts, plus adding the radiate-heat cushion and sheets to the PS LDDR ASSY.

## Models in this family

-  - WUXGA, laser
- [[wiki/projectors/eb-pu2216b/index]] - WUXGA, laser
-  - WUXGA, laser
