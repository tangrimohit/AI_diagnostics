---
type: entity
entity_type: model
aliases: [EB-X49, X49, H982]
---

# EB-X49

Epson business/education projector (XGA class, 3LCD). Internal Epson model code **H982**. Compatible lamp **ELPLP97** (lamp PN 1799666). Main board PN 1892734.

## Summary

Common failure modes, ranked by frequency (see known failures for detail):
1. Lamp errors and lamp replacements
2. Main board failures (ports, no power)
3. Optical engine / display blur / yellow image
4. iProjection / IPS Tool / software compatibility
5. Auto Iris failures
6. HDMI port failures (overlap with main board)
7. Remote control issues
8. Internal error / I2C / Ballast
9. LAN/network port failures
10. Fan / temperature errors

## Key facts

- Internal model code: **H982**. The X49 chassis is inside the H971-H988 / HA02 / HA03 optical-engine family, so that family's troubleshooting and procedures apply to X49 directly. There is a minor attribution quirk (H982 listed as WXGA in the manual specs vs X49 being XGA) documented in h code attribution; treat that as a parts-catalog quirk, not a reason to discount the manual.
- Compatible lamp: **ELPLP97**, lamp PN **1799666**.
- ELPLP96 cross-compatibility question. See elplp97 vs elplp96.
- Main board PN **1892734**.
- Related product code **H838** appears in PS Ballast / Filter Board failures.
- Lamp life claim: 12,000 hours eco-mode.
- Color depth: **10 bit / 1.07 billion colors**.
- Service support: **6 years of repair service after EOL**. As of 2024-05, X49 is still in mass production; EOL not yet announced.
- Security update commitment: **7 years from purchase** per SoC label / PSTI regulation.
- Latest firmware as of late 2024: **V2.14** (**V2.16** for the regional variant).
- Reported fault pattern: optical engine + main board failures. See critical issues.

## Child pages

- [[wiki/projectors/eb-x49/specs]] — basic specs (sparse until service manual ingested)
- known failures — failure clusters ranked by frequency
- critical issues — reported fault pattern, recurring lamp warranty pattern
- [[wiki/projectors/eb-x49/parts-reference]] — parts list
- lamp failures
- main board failures
- optical engine failures
- auto iris
- hdmi port
- lan network
- internal i2c error
- fan temperature
- iprojection compat
- remote control
