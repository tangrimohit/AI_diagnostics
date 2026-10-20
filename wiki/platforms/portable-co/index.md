---
type: entity
entity_type: platform
keywords: [co series, portable, co-w01, co-fh02, co-fh01, main board failure, main board pn 1893627, main board pn 1893626, ballast ok, hdmi port dead, usb dead, no power, lines on display, optical engine pn 1893619]
---
# Portable projector family (CO series)

## Summary

Shared diagnostic page for these projectors, which use the same engineering platform and share failure modes and service parts: CO-FH01, CO-FH02, CO-W01.

## Models in this family

-  - 1080p, lamp/LED
- [[wiki/projectors/co-fh02/index]] - 1080p, lamp/LED
-  - WXGA, lamp/LED

## Specifications

From the service manual. The manual covers several CO models, so per-model differences are noted where they exist.

| Item | CO-FH01 | CO-FH02 | CO-W01 |
|---|---|---|---|
| LCD size | 0.62-inch (C2fine) | 0.62-inch (C2fine) | 0.59-inch (C2fine) |
| Pixel number | 2,073,600 dots (1920 x 1080) x 3 | 2,073,600 dots (1920 x 1080) x 3 | 1,024,000 dots (1280 x 800) x 3 |
| Native resolution | Full HD | Full HD | WXGA |
| Aspect ratio | 16:9 | 16:9 | 16:10 |
| LCD type | VA | VA | VA |

Shared across the family unless noted:

| Item | Value |
|---|---|
| Focus adjustment | Manual |
| Zoom adjustment | 1.0 - 1.35 (digital) |
| Light source | UHE lamp, 188 W |
| Lamp life | High 6,000 hours / Low (Eco) 12,000 hours |
| Brightness | High 3,000 lm / Low (Eco) 2,000 lm |
| HDMI | HDMI Type-A x1 (HDCP 1.4) |
| USB | USB Type-A x1, USB Type-B x1 |
| Network | Wireless LAN unit (CO-FH01/CO-W01 optional; CO-FH02 included in package, plus SMP terminal) |
| Power | 100-240 V AC plus/minus 10%, 50/60 Hz |
| Rated power (High / Eco), 100-120 V area | 284 W / 223 W |
| Rated power (High / Eco), 220-240 V area | 270 W / 214 W |
| Standby power consumption | 0.5 W |
| Operating temperature | 5 to 40 C (0 to 2,286 m); 5 to 35 C (2,286 m or more) |
| Operating altitude | 0 to 3,048 m |
| Start-up period | Less than 6 seconds |
| Warm-up period | 30 seconds |
| Cool-down period | Instant off |
| Fan noise | High 37 dB / Low (Eco) 28 dB |

Physical differences:

| Item | CO-FH01 | CO-FH02 | CO-W01 |
|---|---|---|---|
| Size (excl. protrusions) | W295 x H82 x D211 mm | W320 x H82 x D211 mm | W295 x H82 x D211 mm |
| Size (maximum) | W295 x H87 x D211 mm | W320 x H87 x D211 mm | W295 x H87 x D211 mm |
| Weight | Approx. 2.2 kg | Approx. 2.5 kg | Approx. 2.2 kg |

Repair notes from the manual:
- The lamp is not user-replaceable by design. Removal requires disassembly (Cover SMP on CO-FH02, Case Upper, wiring, Cover Lamp Upper, Lamp Housing Assy).
- The air filter is not user-replaceable by design. Clean by vacuuming dust from outside the lower case; replacement requires replacing the double-sided tape on the lower case.
- An N polarizer is integrated into the PRJ LENS ASSY. Repairs for N polarizer deterioration require replacing the optical engine or PRJ LENS ASSY.
- If the lamp does not light, it may have burst with glass scattered inside. If there is a crunching sound when the body is slightly tilted with power off, follow the burst-lamp cleaning/replacement procedure before disassembling.

## Error code reference

LED / error indication codes from the manual error and warning name list. The display string is what appears on the projector.

| Error name | Error display |
|---|---|
| Overheat | Temp (TH) |
| Fan error | Fan (FN) |
| Temperature sensor error | Thermistor (SE) |
| Lamp error | Lamp (LE) |
| Lighting failure (lamp on error) | Lamp On (LF) |
| Lighting failure (lamp off error) | Lamp Off (LF) |
| Internal error (RAM) | RAM (RA) |
| Internal error (ROM) | ROM (RO) |
| Internal error (I2C) | I2C (II) |
| Internal error (DR status) | DR (ID) |
| Wind lowered error | Air (WL) |
| Power error (ballast) | Ballast (PB) |

Warnings:

| Warning name | Error display |
|---|---|
| Lamp life warning | Lamp Life (LL) |
| High Temp warning | Temp (TH) |
| EasyMP internal error | EasyMP (IM) |
| Wind lowered warning | Air (WL) |

## Parts

Key replaceable assemblies and boards from the manual parts list.

| Part | Notes |
|---|---|
| MA Board Assy | Main board; FH variants for CO-FH01/CO-FH02, WX variant for CO-W01. |
| Opt Engine Assy | Optical engine; FH and WX variants. Carries the integrated N polarizer in the lens path. |
| Ps Ballast Unit Assy | Power / ballast unit. |
| Lamp Housing Assy | Lamp assembly (not user-replaceable). |
| TH Board / TH Board A | Thermistor boards. |
| IR Board | Remote receiver board. |
| Filter Board | Filter / inlet board. |
| INT Fan | Intake fan. |
| EX Fan | Exhaust fan. |
| Ring Focus | Focus ring. |
| Speaker Unit / Speaker 5W | Audio output. |
| Air Filter | Air filter (HA84 variant and a separate variant). |
| Case Upper / Case Lower / Case Rear / Case Right | Enclosure parts (HA84/HA85 variants). |
| Cover SMP | SMP cover (CO-FH02). |
| PRJ LENS ASSY | Projection lens with integrated N polarizer. |

Part numbers are recorded in the manual as internal SPI naming and are not reproduced here.
