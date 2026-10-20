---
type: glossary
---

# Projector Glossary

Terms and abbreviations specific to Epson service work. Filled in as sources are ingested.

## Epson internal codes

- **H982** — Internal Epson product/board code for EB-X49 family.
- **H838** — Internal Epson code for PS Ballast Unit Assy + Filter Board Unit family.
- **H971** — Internal Epson code referenced in and the `H971_EngineRepairManual_EN_Rev.E.pdf` in . Relationship to X49 not yet confirmed.

## Parts / lamp SKUs

- **ELPLP97** — Epson lamp SKU compatible with EB-X49. See elplp97 vs elplp96.
- **ELPLP96** — Different Epson lamp SKU; compatibility with X49 raised in (answer pending).
- **PN-1799666** — Service part number for ELPLP97 as seen in cases.
- **PN-1892734** — Service part number for the EB-X49 main board (MA Board ASSY, H982).
- **ELPAP10** — Epson wireless dongle SKU (mentioned in ).
- **MA Board** — Main Board Assembly. The main logic board.
- **OPT Engine ASSY-X** — Optical Engine Assembly for X-series projectors. Internal code H982.
- **PS Ballast Unit Assy** — Power supply + ballast that drives the lamp. H838 family.
- **Filter Board Unit** — Filter board on the PS side. H838 family.

## Laser / light-source subsystem 

Mostly applies to laser projectors, not X49 (a lamp model), but useful background when the wiki later expands to laser models. Some terms (PS, MAB, OE, LD, BSP) overlap.

- **AS** — After-sales Service (Epson service parts and process).
- **MAB** — Main board (the projector main logic board; for X49 this is PN-1892734, family code H982).
- **PS** — Power Supply unit.
- **LLC** — Power supply for the LDDR (laser models only).
- **OE** — Optical Engine.
- **LD** — Laser Diode (laser models only).
- **LDDR** — Laser Diode Driver; controls supply current for the laser diode (= image brightness).
- **LDTH** — Laser Diode Thermistor.
- **LMDR** — Laser Motor Driver; controls the Diffusion Wheel and Phosphor Wheel.
- **LSM** — Light Source Module (laser).
- **DWH** — Diffusion Wheel; diffuses laser blue light so it covers the panel uniformly.
- **PHW** — Phosphor Wheel; has yellow phosphor material; converts blue light to yellow.
- **BSP** — Beam Splitter Polarizer; splits laser blue light into "Yellow" and "Blue" channels.
- **Ary** — Array (in YE error context, "AryErr" = laser array error).
- **Drv** — Driver (in YE error context, "DrvErr" = laser driver error).
- **POP** — Panel-On-Prism; the prism assembly with the three LCD light valves bonded on. Recombines the R/G/B images into the full-color image and sets color balance. Present in both lamp and laser optical engines.
- **PBS** — Polarizing Beam Splitter (see also BSP). A low-cost part whose degradation blocks a large share of brightness; an early step in laser brightness restoration.
- **Condition Diagnosis** — One-button IPS Tool function (v2.3.8 and later) that isolates LSM-vs-OE faults from internal sensor values on supported laser models. See condition diagnosis.
- **LSM B/Y** — White-balance ratio computed from the R/B sensors, scale 0 to 200. 100 = neutral white; above 100 the blue component dominates (bluish image expected), below 100 the yellow component dominates. The 110 to 90 band counts as no or little cast (workbook Rev C).
- **OE value** — In Condition Diagnosis output: the deliberate light-output restraining level (%) applied by firmware to protect phosphor and light valves over the unit's life. Not a fault by itself. Three restraints exist (LD temperature, brightness mode, weighted usage time); the OE value reports only the usage-time one. Some models report a combined OE&LSM value instead.
- **Sensor value** — In Condition Diagnosis output: light actually lost between the light source and the R/B sensor (%), from dust, smoke, sand or ageing optics. Real physical loss, unlike the OE value. Bench observation: about a 2-point run-to-run spread is normal.
- **LD Calibration (OK / Not Yet)** — Condition Diagnosis gate check: does the unit hold its factory calibration base record. Not Yet invalidates every other value; fix via CRAFT first.
- **R/B sensor** — Red/blue light sensors at the end of the optical engine. Feed the Sensor and LSM B/Y values. Everything after them (projection lens included) is invisible to the IPS tool.
- **Light Guide** — Light-guiding part at the optical engine entrance; one of the three standard cleaning points (around-lens, POP, Light Guide).
- **Weighted LOT** — Weighted light-output (usage) time; the input of the usage-time restraint reported by the OE value.
- **Restraining reset** — OE value returns to 100 only when the relevant part is NEW and CRAFT is executed (phosphor-wheel systems: optical engine; fixed-phosphor systems: LSM). No software-only reset. Matters for refurbish sales.
- **LMDR failure (YE Comm Err branch)** — the service-manual YE table branch `LD/WH ST Check_Other -> Timeout_AbnlReplay -> LMDR failure`, remedy replace LSM Assy.

## Tools

- **IPS Tool** — Epson's projector service tool (Integrated Projector Support Tool). Reads error logs from a projector over USB and produces TSV log files.
- **CRAFT** — Manufacturer calibration software used at repair bases: LD calibration, writing adjustment data, detecting replaced parts and resetting restraining values.
- **DR data** — Per-unit image-adjustment data stored on the main board. Downloaded from the internal data portal (Intra-mart) and rewritten after board or optical-engine work; a DR-data mismatch shows as color problems or a failed write (F01D). After an OE swap the data must match the fitted engine and is requested by the **OE serial** (starts "E"), then written with CRAFT. See oe adjustment data request.
- **F01D "MODEL CODE ISN'T MATCH"** — error on a DR/adjustment-data write (a CAT2 symptom) meaning the data does not match the fitted engine/model. A data-match issue, not a board fault; use CRAFT and request DR data by the OE serial.
- **CAT / CAT2 / RESCUE / Launcher** — the legacy service-tool set (adjustment-data write, destination write) that CRAFT now integrates. See craft toolchain.
- **ELPAP12 / WH-5674B** — ELPAP12 is the Android TV media-player dongle bundled with home models (e.g. EH-TW6250); WH-5674B is its remote. The dongle pairs over RF (Bluetooth), not IR.
- **Test Pattern** — IPS function projecting inspection patterns from the PC over the video cable. Four adjustment purposes: Pixel Deviation / Focus, Burn-in, Colour Adjustment, Uniformity.
- **AGPATTERN** — Aging Pattern: the projector's own internal pattern generator, no PC signal needed. Test Pattern bad + AGPATTERN clean = signal path fault; bad on both = engine side. First isolation step on uniformity and colour complaints.
- **PJCONFDATA.BIN** — Log file written by the USB-stick dump (empty stick in the Type A port, hold [Return] on power-up). Loaded offline via Error Information.
- **VCOM** — Virtual COM port driver for USB service connection. Windows Core Isolation can block it.
- **ESC/VP21** — Epson projector command protocol used by the IPS Terminal function.
- **DLF** — Dead Lock Free: tool that unlocks a projector dead-locked by repeated wrong password entries (integrated into the confidential-data setting tool in 2026).
- **ACI** — Active Control Initialization: initializes projectors enabled for Active Control with EPMC (part of the confidential-data setting tool).
- **EGID** — Epson Global ID: partner authentication that replaces TechExchange for new service tools.
- **Request Code / Release Code** — password unlock pair: 5-digit code shown on the Password Protect Release screen, exchanged for a 4-digit release code via the Request Code Enquiry System.
- **iProjection** — Epson's customer-facing wireless display client (Windows, Mac, Android, iOS, Chromebook).
- **Epson Projector Management** — Admin tool for managing many projectors over a network.
- **TechExchange** — Epson's internal/partner knowledge portal.
- **PJLink** — IETF-style protocol for remote projector control over network.
- **AKARI** — This diagnostic assistant.

## Log / IPS terms

- **TSV log** — Tab-separated values log file produced by IPS Tool. UTF-16 encoded.
- **[FN]** — Fan Error Counter line in the IPS TSV log.
- **[TH]** — Temperature / Thermal Error line.
- **[YE]** — Yellow Error family in the Epson error taxonomy.
- **[II]** — I2C communication error line in the IPS log; the factor line names the two bus nodes (e.g. `Vic(MA board) - HDMI Rx(IN789 #1)(DIF board)`) and the slave/sub address.
- **DIF board / MA-IF board** — interface board carrying the HDMI Rx (IN789); a `[II]` I2C error to the HDMI Rx points here rather than at the panel or laser.
- **ErrCode / LogStatus** — The two log fields that feed Laser Log Analysis offline: the error code plus the hex status string recorded at the moment of a YE event. Standard content of every escalation.
- **ERR (field value)** — In Error Information: the tool could not read that item (usually the connection), NOT a projector error code. Many ERR entries across a log point at faulty error-log writing on the main board.
- **NG** — No Good. Generic fail state (e.g. LDDR = NG in Condition Diagnosis).
- **Yellow / blue rows** — Error Information colour code: yellow background = error (unit stopped), blue background = warning (unit kept running).
- **I2C** — Inter-Integrated Circuit bus. The bus that connects the main board to the ballast, filter board, optical engine, sensors, etc. "FATAL ERROR I2C" means the bus or one of its devices failed.
