---
type: entity
entity_type: part
keywords: [eb-x49 parts, ballast, ps ballast unit, pn 1941969, pn 1870132, pn 1775452, filter board, pn 2183918, h838, shared chassis parts, ma-if board, pn 1904782, optical engine pn 1831165, lamp elplp97, lower case, case unit lower, pn 1942018, pn 1941989, pn 1941983, plate fasten nut, ceiling mount fastening]
---

# EB-X49 — Parts reference

Parts associated with EB-X49 service work, with each part's function and the failure mode that calls for replacing it. Not authoritative for ordering (use the Epson parts catalog for current PNs and availability), but useful as a diagnostic shortcut.

## Lamp

- **ELPLP97** (Epson product code), lamp PN **1799666** (service PN).
- Function: projector light source.
- Cross-reference question: can ELPLP96 substitute for ELPLP97 on EB-X49? Not yet resolved. See elplp97 vs elplp96.
- Replace when: lamp error on power-on, fan spins but no display, dim or dark image, lamp reported dead.
- Lamp-life claim: 12,000 hours in eco mode.
- See lamp failures.

## Main board

- **Main board PN 1892734** (service PN).
- Function: primary control board (power, video, network, image adjustment).
- Replace when: no power on, HDMI port dead, LAN port dead, image adjustment unresponsive, intermittent shutdown, internal error.
- See main board failures.

## PS Ballast Unit Assy

- Associated product/board code: **H838** (also appears as `BALLAST UNIT;H838;EP;PH`).
- Function: drives the lamp (provides the ignition and lighting power for the lamp).
- Replace when: internal error, projection won't start, lamp won't ignite, high-pitched electronic noise.
- Ballast PN compatibility for the X49 family:
 - `1798060` — compatible, latest, has lamp reinforcement learning
 - `1870132` — compatible (superseded by `1941969`)
 - `1941969` — current PS BALLAST UNIT ASSY, supersedes 1870132. Shared across the H838 lamp chassis: X49, FH52, W51, 992F, FH06.
 - `1775452` — **INCOMPATIBLE**, causes Power Supply System Error (Ballast) [0x13]. See power supply ballast.
- See internal i2c error.
- **Noise note**: high-pitched electronic noise in eco mode is resonance of the ballast and lamp at the lighting frequency, with individual unit variation. No fix is available; swap lamp and ballast until a low-noise combination is found.

## Filter Board Unit

- Associated product/board code: **H838** (same as Ballast).
- Function: filter board, paired with the PS Ballast Unit.
- Replace when: internal error, alongside PS Ballast failures.
- Current part: **FILTER BOARD UNIT, PN 2183918**, shared across the H838 chassis (X49, FH06, 735Fi, 770Fi, LS300). Field repairs on the same units also list the MA-IF board PN 1904782 and PCB 2218817.
- The H838 shared-chassis service model is confirmed by two years of field data: the same ballast and filter-board part numbers recur across eleven models, so a known-good part from a sibling is a valid swap test.

## OPT Engine ASSY-X (optical engine)

- Associated product/board code: **H982** (matches the X49 model code).
- Function: optical engine (image-forming optics).
- Replace when: blurry display, color cast (yellow, red), shadow in projection, fine-text unreadability.
- See optical engine failures.

## MA Board ASSY

- Associated product/board code: **H982**.
- Function: main board for the X49 (see Main board section above).
- Note: in at least one instance MA Board replacement did not resolve the reported fault.

## Remote control

- Remote codes seen on physical remotes: `164880600`, `219863500`, `162636600`. PN `2181788` is the EB-X39 remote (reference data point only).
- An authoritative remote PN for EB-X49 is not yet recorded.

## Optical/imaging parts (referenced but not specified)

- Some "optical control" approvals reference an "optical part" without specifying the exact sub-component. This could be the OPT Engine ASSY or a sub-module within it.

## Lower case redesign (second ceiling-mount fastening point)

A service bulletin (rank B, revised 2025-02) changed the lower case of the EB-E01 family (X49 chassis) and its S05, EH-TW5400/TW5750 and S39 siblings to share parts with newer products. The redesign also raised the ceiling-mount metal fastening points from one to two, so a cracked case (oily environments, see adverse environment precautions) may tilt but will not fall.

- Changed parts, EB-E01 example: CASE UNIT,LOWER 1801623 -> **1942018**; DUCT,EXHAUST,LOWER 1706838 -> **1941989**; CASE,EX 1706879 -> **1941983**.
- Added parts: PLATE,FASTEN,NUT **1940908** (B-H971) or **1940909** (C-H978), and CUSHION,WAVE,PLATE **1764104**.
- Compatibility rule: a new CASE UNIT,LOWER needs the new duct, the new CASE,EX and the added parts. The old case unit works with old or new duct and CASE,EX; the new case unit does not work with the old duct or old CASE,EX. Keep ordering old parts until old stock is used up.

## Related pages

- [[wiki/projectors/eb-x49/index]]
- known failures
- critical issues
