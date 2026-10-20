---
type: concept
keywords: [ips tool, ips log, tsv log, error log, read log, capture log, service tool, vcom mode, com port, get error log, error counter, test pattern, terminal, def viewer, cat tool, rescue, launcher, condition diagnosis, repair id, batch data, cs2, wireless lan log, vcom driver, memory integrity, core isolation, windows 11]
---

# IPS Tool (Integrated Projector Support Tool)

The Windows application Epson service engineers use to read operation and error logs from a projector. Almost every X49 MSD case references the IPS Tool log as the diagnostic anchor. This page summarizes how it's used so AKARI knows what data the engineer can produce.

## What it is

A Windows application from the manufacturer VPCS Quality Assurance Dept. that integrates multiple service functions:

| Function | Purpose |
|---|---|
| Error Information | Acquire / display / analyze projector operation and error logs |
| Terminal | Execute command macros |
| DLT | Firmware Download (transmission and reception) |
| Test Pattern | Display various test patterns |
| Laser Log Analysis | Detailed analysis for older laser models |
| LogInfo / ASInfo Viewer | View all service logs |
| Get LogInfo / ASInfo | Retrieve service logs |
| Private Network Functions | Network operation (alternative to Epson Projector Management) |
| Fast FW Backup | Backup for high-tier (Superior) models |
| Firmware File Downloader (Yatop) | Yatop transmission, for engineering |
| Zmodem | Flash ROM dump / load |
| Bin Extract | ROM XML reading, Flash ROM dump |
| Def Viewer | Model search (number ⇔ codename) |
| Condition Diagnosis | One-button LSM-vs-OE fault isolation for image-quality complaints on supported laser models (added v2.3.8). See condition diagnosis. |

Training levels per the source document:
- **Basic** — How to use the IPS Tool app (this page's source).
- **Intermediate** — How to read the "Error information" log in the IPS Tool (this document has not been ingested yet; it would be valuable for a next ingest).
- **Practical** — Find solutions based on errors retrieved from IPS Tool, via repair-practice exercises (covered below under "Practical diagnosis workflow").

## Install prerequisites

- Windows 10 / 11. On Windows 10 and older VCOM drivers, **turn off Memory Integrity** under Core Isolation in Windows security settings before installing the VCOM driver (the OS otherwise blocks the driver install).
- **VCOM driver 3.0.0.0 (service bulletin rank B, 2026-08)** supports Windows 11 with Memory Integrity left on. With this driver the security-setting workaround is no longer needed on Windows 11; it still applies to Windows 10 and earlier. The VCOM driver is the USB bridge for IPS Tool, CRAFT, CAT2 and RESCUE alike.
- Install IPS Tool from TechExchange.
- Install the VCOM driver alongside (required for USB communication with the projector). The driver link is in the T/I.

## Basic operation (startup and main menu)

After installation, launch IPS Tool from the desktop icon. At startup it may show a notification that the definition file or the tool itself has an update. You can skip an update by pressing the X in the upper right, but the guidance is to apply updates when possible. A tool update runs 1 to 2 minutes; a definition file update takes only a few seconds.

The Main Menu is the screen that appears after startup. It has three groups:

- **Main Functions** — each service function is launched by a button click. The distributor and repair-base build of the app has limited functionality (a subset of the engineering functions).
- **Projector operation** — an alternative to the control panel and remote control. Requires the projector to be connected in VCOM mode.
- **Language settings** — switch the screen between Japanese and English.

## Capturing logs from a projector

Required: PC with IPS Tool installed, VCOM driver installed, USB cable (USB A to B for "Biz" projectors like the EB-X49, USB A to mini-B for "Home" projectors).

1. Install VCOM driver to your PC.
2. Unplug the projector power cord.
3. **Hold [Enter]** on the projector control panel while plugging the power cord back in. This is the trigger to enter VCOM mode.
4. When the "ON/Standby" status light flashes then lights up, release [Enter].
5. Connect the USB cable between the PC and the projector's service port (USB Type-B).
6. Turn on the projector.
 - If the projector is already in "Communication ON Standby" or "Error Standby", you can skip step 6.
7. In IPS Tool, press **COM Port**, select **EPSON Virtual COM Port (COMxx)**, then **Connect Test** (success dialog confirms).
8. Press **Get Error Log**.
9. Save as `.tsv` (text, human-readable, can share) or `.bin` (binary, encrypted, IPS-only).

If the projector won't boot into VCOM mode, the logs can alternatively be captured to USB memory via a documented key sequence in the user manual; the USB memory must be empty.

## Error information screen layout

The Error Information window has these areas:

- **Port connection button** — selects the COM port used to talk to the projector. Set it up after the projector is powered on.
- **Error log display area** — logs retrieved from the projector, or loaded from a saved file, are shown here. If text appears in this area after a Connect Test, the connection succeeded.
- **Analysis support button** — sorts the error log and shows a status view (see "How to analyze" below).
- **Error log retrieval button** ("Get Error Log") — pulls the log from the connected projector. It is grayed out until the projector is connected over the VCOM port and powered on.
- **Wireless LAN log retrieval button** — enabled only when the batch setting file of a wireless-LAN-logging model is open.
- **File Save / Load button** — saves the displayed log to a file, or reads a log back from a file.

## Types of information returned

Based on projectors released in 2017 and later. There is slight variation per model.

| Group | Content |
|---|---|
| Projector Information | Serial number, MAC address, destination region |
| Lamp/Laser Information | Light source operation history |
| Lamp/Laser Replacement Time | When the light source was last replaced (recorded at repair) |
| Error Counter | Cumulative count per error type |
| Warning Counter | Cumulative count per warning type |
| Error/Warning Info | Occurrence log (chronological) |
| Detailed Laser Log | Detailed log when a YE laser error occurs (laser models only; see ye errors laser only) |
| Temp Info | Detailed log when a temperature error occurs |
| Operation Info | Power on/off events, signal-input events |
| Signal Info | Signal information log (recently merged into Operation Info) |
| Content Playback Info | Content playback events |
| Projector Setting Data | OSD menu settings |

## File formats

| Format | Encoding | Capacity | How to capture | How to read | User-accessible |
|---|---|---|---|---|---|
| TSV (`*.tsv`) | Text (UTF-16, tab-separated) | small | VCOM mode via IPS Tool | IPS Tool or a text editor like Notepad | Yes, documented |
| BIN (`*.bin`) | Binary (encrypted) | larger | USB memory via special key on the projector | IPS Tool only (encrypted) | No |

TSV is the format L3 and the service partners share when discussing cases (almost all MSD cases reference `tsv` logs). BIN is used for backup-and-write of full PJ settings and for firmware update.

## How to analyze

1. Capture the log (TSV preferred for sharing).
2. Compare the per-model service manual against the error counter / Error Info entries. The Error Counter shows cumulative per-error totals; the Error Info gives the chronological occurrence log.
3. Use the **Error analysis support** button (still labeled "testing function" in this revision) to sort Operation Info and Error Info together in chronological order. Lets you see "error occurred during operation," "error immediately after power on," "power forcibly terminated," etc.
4. Map the error code to the corresponding entry in [[wiki/index]] under Error codes (Temp, Fan, Thermistor, RAM, Inner, DR, IV, Auto Iris for the H971-H988 family).

## Firmware update via IPS Tool

Firmware update is normally done by the engineer rather than by IPS Tool, but IPS Tool can do it when a special measure is required.

1. Load a DLT file (provided by the manufacturer for special cases; not generally public).
2. Set the projector into VCOM mode and connect via USB.
3. Press **DL Mode ON** in IPS Tool to enter PJ download mode.
4. Download (or back up) the firmware. Process takes 10 minutes to 1 hour; fan spins at high speed. **Do not disconnect power or USB during the process.**

YATAP file route is an alternative not requiring IPS Tool; described in TechExchange.

## Test Pattern function

The Test Pattern function is mainly used to check for image-quality defects and to run aging. There are two pattern sources:

- **Test pattern** — a pattern stored in IPS Tool is projected to the unit. Connect to the projector with an HDMI cable; no VCOM connection is required. During display, use the left and right keys to switch patterns and Esc to end.
- **Aging pattern (PJ built-in)** — calls up a pattern built into the projector. Connect a USB cable to a projector booted in VCOM mode. The built-in pattern can also be called up by pressing and holding Esc while VCOM is running. If a pattern is not supported by the model, its button does nothing.

When connected over VCOM, the PJ setting controls let you switch color mode and pixel shift ON/OFF.

Common image-quality defects and the patterns used to check them:

| Defect | Symptom | Patterns used |
|---|---|---|
| Color uniformity | Parts of the screen look magenta or cyan; white does not look uniform | All white (100%), all black, midtones (e.g. 127/255, 40/255) |
| Dust / scratch | Dust in the optical engine or scratches on the lens surface show up | All white, all black |
| Pixel defect | A dot is always bright (R/G/B), or always dark | Pixel R/G/B; bright spot checked on all-white, dark spot checked on all red/green/blue |
| Pixel misalignment | R/G/B lines visible on the outline of characters | H Pattern (pixel-shift pattern for accurate measurement) |
| Flare | Light appears to trail from pixels | H Pattern |
| Focus error | Out of focus even after focus adjustment | H Pattern |

Usage note: if the test pattern does not fill the projector screen, check the PC display resolution. Set the PC display resolution equal to the projector's native panel resolution.

## Terminal function

The Terminal function sends ESC/VP21 commands to the projector and shows the response value. It can also run macros (repeating the same command automatically). A TeraTerm macro can be reused by changing its extension from `.ttl` to `.ipsm`. This function is mainly for service partners who cannot install TeraTerm; engineers who already have terminal software they know (for example Hercules) can keep using it.

The VCOM-connection part of the Terminal screen is the same as the error-log screen. After connecting to VCOM, press Enter on the PC and a returned `:` confirms the link. The Log Field shows the command you entered and the response; a Log Save button writes the field to a text file, and a Log Clear button clears the display.

## VCOM entry method varies by model

The basic VCOM-entry method is to plug in the power cord (AC IN) while holding [Enter] on the control panel. Some model families use a remote-control button instead (for example A/V Mute, Blank, or Power held during AC IN), and a few need a two-step sequence (AC IN, then power on, then hold a remote button). Always confirm the exact key sequence for the specific model in its service manual before assuming the [Enter] method works.

## Practical diagnosis workflow (from repair-practice training)

The practical-level training reduces field diagnosis to a short loop. When you notice an error:

1. **Get the IPS log.**
2. **Check the troubleshooting section of the service manual** for that error code.
3. **Check the wiring / connection diagram** if the manual remedy alone does not resolve it.
4. **Ask a depot or central-support member** if it is still unresolved.

Reading the log inside IPS Tool, the practical steps are: open Error Information and connect, press **Get Error Log** while the error is occurring, then read it in two places. In **Error Counter**, the error types that have occurred are highlighted in orange. In **Error / Warning Info** you can read the dated occurrence log (date and time per entry) to see today's events.

### Recurring lessons from the worked examples

The training Q&A set shows the same failure pattern repeatedly: an engineer replaces the boards the error name points at, the symptom persists, and the real cause is an adjacent cable, connector, or in-between assembly. Concrete takeaways:

- **Follow the manual remedy top to bottom.** Several cases were only solved by continuing down the manual's ordered remedy list after the first replacement failed. Skipping straight to the obvious board is a common miss.
- **Suspect the parts between the named boards.** A repeated TH (temperature) error that survived replacing the light-source-control board and main board was fixed by replacing the LDDR assembly, which sits between the main board and the LLC board. A laser (YE) Drv error that survived several board swaps was fixed by replacing the LLC assembly. Another laser case was fixed only by replacing the optical engine after the manual's later remedy steps.
- **Check cables and connectors, not just boards.** An I2C error pointing at a slave address was traced to a relay board and a defective FFC between the connector board and the main board, not the boards already swapped. An intermittent power-off-with-error case turned out to be a burnt DC-connector pin root with melted cable housing.
- **Laser warning text carries meaning.** A `Balance_LightOutput` warning means the light strength is unbalanced between the R and B channels and is too low. The manual's remedy list for that condition walks through LSM, then wave plate in the LSM, then LDDR, then optical-engine assembly.
- **Some failures are firmware or environment, not the named part.** A recurring fan (FN) error across many units of one model was root-caused to a setting parameter ("fan duty %") that was not always written to memory correctly, and was fixed by a new firmware build rather than by cleaning or replacing the fan. A separate "LV0" fan reading is not actually a fan fault; it indicates the main board and power-supply assembly cannot communicate, so the fix is to replace those boards and the cables between them.

The standing wrap-up from the training: most errors can be solved by reading the IPS log against the service manual, a minority need the connection diagram, and the hardest ones need a root-cause analysis from the manufacturer.

## Version capabilities worth knowing (v2.2 to v2.4)

The tool's official manual (Rev A, April 2026) and release history add
capabilities an engineer may not know their build has. Current version is
v2.4.1 (June 2026); v2.1.5 and later self-detect new versions over the
internet and offer the update.

- **Repair ID in TSV filenames** (v2.3.4): a form appends the repair ID to
  saved TSV log filenames, which keeps logs traceable to cases without manual
  renaming.
- **Wireless LAN log** (v2.2.0): access-point and iProjection connection logs
  can be loaded from batch data and exported (csv/txt) on wireless-logging
  models. Useful for "keeps disconnecting" complaints (see
  control system integration faults).
- **Batch data loading**: the error screen can load a `PJCONFDATA.BIN` batch
  file captured to USB memory on-site, so a full log review does not need the
  unit connected. Constant info (serial, MAC) displays with it.
- **Extra test patterns**: Pixel R/G/B (v2.2.2), Pixel Deviation and White
  1.7% (v2.3.1), used with test patterns.
- **Condition Diagnosis** (v2.3.8; button-visibility fix in v2.4.1): see
  condition diagnosis.
- **CS2 restricted installer**: a function-masked build for distribution to
  service partners; the enabled function set is controlled by a settings file
  generated with the official localization/setting helper workbook. If a
  partner's IPS Tool is missing buttons, it is a CS2 build with functions
  masked, not a broken install.
- **Laser Log Analysis workflow**: for YE errors/warnings on older laser
  models, the tool decodes an `ErrCode` plus `LogStatus` hex string from the
  log into a human-readable LSM status. The decode logic is inside the tool;
  the log supplies the code and hex.

## Recent Projector Service Tool family

IPS Tool is one tool inside a broader Projector Service Tool set used for repair support. The other members handle data that lives on the main board and must be restored when the main board is replaced:

| Tool | Purpose |
|---|---|
| IPS Tool | Get error and projector-usage logs, firmware update, user-logo backup, display test pattern (the main repair-analysis tool) |
| CAT Tool | Calibration-data downloader. Projectors hold calibration data (for example DR data, laser calibration data) on the main board. After a main board swap the technician downloads the unit's calibration data and writes it to the projector. |
| RESCUE | Destination-configuration downloader. The default OSD-menu values differ by destination, and that destination data is stored on the main board, so it must be re-downloaded after a main board swap. RESCUE is released per model. |
| Launcher | Launches each of the above tools. It exists because RESCUE is released per model (a large number of versions), so a single launcher fronts them all. |

Practical implication for diagnosis: if a case mentions replacing the main board, calibration and destination data have to be re-written with CAT Tool and RESCUE, otherwise the unit can misbehave after the swap even though the board itself is good.

## What AKARI should do with this

When a query says "IPS log shows X" or "from the TSV," interpret X using the Error code pages and the known failures cluster mapping. The TSV log is the authoritative source for engineer-facing diagnosis; if a case has no TSV attached, recommend pulling one before further work.

## Related pages

- fan temperature (FN counter example)
- internal i2c error (TSV-anchored cases)
- [[wiki/error-codes/temp]]
- [[wiki/error-codes/fan]]
- auto iris
- ye errors laser only
- condition diagnosis
- ld driver ic failure
