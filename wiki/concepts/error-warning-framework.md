---
type: concept
keywords: [indicator light, led indicator, status light, blinking led, flashing, warning code]
---

# Error vs Warning diagnostic framework (intermediate level)

How AKARI and a service engineer should read the "Error information" log in the IPS Tool, tell an Error apart from a Warning, decode the code and indicator fields, and decide what to do. This is the foundational concept that the per-code pages build on. The detailed IPS Tool workflow lives in [[wiki/concepts/ips-tool]]; the code lookup tables live in ips error code dictionary.

## Definition

The single most important distinction in the log is severity, and it is binary.

- **Error**: image projection stops. The projector halts the picture on purpose to protect itself from damage.
- **Warning**: image projection continues, but with a functional limitation (for example brightness drops).

Every code in the log carries a severity prefix that states which of the two it is: `ERR` for an error, `WAR` for a warning. The full code field is read as `[WAR/ERR][error code]`.

Because the same two-letter code can be logged as either an error or a warning (the temperature code TH and the laser code YE both appear in both forms), the prefix and the counter section, not the two letters alone, tell the engineer whether the unit shut down or merely flagged a condition.

## Context

The log lives inside the IPS Tool under the AS menu and the error/warning info view. The sub-items under "Log Data" vary by projector model, so the engineer first checks what error has occurred in the error/warning info, then opens the matching sub-item:

- Laser-related codes (YE) are detailed under the sub-item labelled "Laser" (for example LaserInfo, LaserErrorLog).
- Temperature codes (TH) are detailed under the sub-item "Temp info".

The codes seen across the log include SE, FN, TH, YE, RAM, ROM, I2C, DR, Air, OD, AP, FP, WL, RA, RO, ID, IV, CF, PV, LP, LA, SH and others. They sort into broad families: thermal and cooling (TH, FN, SE, fan and thermistor faults), laser and light source (YE and its sub-types), communication (I2C), and a long tail of other codes that the per-model service manual covers.

## How to read a log entry

Each error/warning record exposes a fixed set of fields. The ones that drive a diagnosis:

| Field | What it tells you |
|---|---|
| FW version | `V` plus 3 of the 4 digits of the software version. |
| Sequence No. | Event counter, 0 to 4294967295 (decimal). |
| Date of occurrence | `yyyy_mm_dd`. |
| Time of occurrence | `hh_mm_ss`. |
| Operation time | Total time / laser operation time / power-on time. |
| Error Code | `[WAR/ERR][error code]` (the severity prefix plus the two-letter code). |
| Warning/Error Name | Plain meaning of the code. |
| Projector Status | State at the moment of the event. |

Projector Status values: Standby, NW standby, AV standby, Normal (normal condition), Cooling (cooling down in progress), Error standby.

Further fields, present only on some entries: Device ID (device name is defined in the service manual), Projector ON count (max 65,535), Installation angle (`x=0000,y=0000,z=0000`), Installation mode (Front, Upwards, Downward, Suspended, Oblique upward, Oblique downward, Portrait), Temperature information (from the `temp?` command), Fan information (fan speed, from `fanrevo?`), and Pressure sensor information (from `psv?`). Several of these can be blank, and installation mode does not depend on the error type.

To turn the raw `temp?` response into named thermistors and degrees, run the value through the temperature log conversion tool. See temperature log conversion tool.

## Reading the code categories

### Thermal, cooling and sensor (FN / TH / SE)

These record fan and temperature-sensor conditions from the hardware built into the product. See [[wiki/error-codes/temp]], [[wiki/error-codes/fan]] and [[wiki/error-codes/thermistor]].

- **FN (Fan)** is an Error: a fan fault. Causes include dust on the fan, a cable connection problem, fan failure, or MA board failure. Response: clean off dust, recheck cable connections, replace the fan, replace the MA board.
- **TH (Temp)** appears as both an Error (internal overheat) and a Warning (high-temperature warning). Causes of the overheat error include the operating environment, a clogged air intake, a dirty air filter, or MA board failure. Response: clear obstructions near the intake/exhaust, clean the intake ports, clean or replace the air filter, replace the MA board.
- **SE (Thermistor)** is a temperature-sensor Error: an abnormal thermistor connection, thermistor failure, or failure of the thermistor mounted on a board. Response: recheck the thermistor connection, replace the thermistor, or replace the board it sits on.

A TH record also carries a Level field. Each thermistor is graded into temperature states based on measured temperature against a set threshold (the threshold varies by model and location): states T1 through T5, mapping the band from normal measurement up through warning and into error. In the log, `Level nn` greater than 3 means the temperature is higher than normal.

When an FN/TH/SE event fires, the device code shown next to the error code identifies which specific fan or sensor is involved. Look that device code up in the service manual.

### Laser and light source (YE)

YE is the laser-related family and is logged under the AS menu and IPS menu. The IPS Tool keeps a separate YE error counter and YE warning counter. There are 8 YE types, and they split cleanly across the error/warning line:

| Type | Meaning | Severity |
|---|---|---|
| Ary Err | Laser array error | Error |
| Ary War | Laser array warning | Warning |
| Drv Err | Laser driver error | Error |
| Drv War | Laser driver warning | Warning |
| Motor Err | Motor driver error | Error |
| Comm Err | Communication error | Error |
| Limit Current Err | Laser limit current value error | Error |
| Source War | Light source module warning | Warning |

On some models "Ary War" and "Drv War" are written together in the log as `Ary_Drv_War`. The deeper YE breakdown (error factors, occurrence conditions, and the cause/solution tables) is on ye and summarized in ye errors laser only.

### Communication (I2C)

An I2C error is a communication failure between the main IC chip and a specific device. Each device has a slave address, and that address is reported when the error fires. It is logged as `[II] I2C` in the Error Info of the AS menu. The three main failure modes: cable connection error (unconnected, loose, or broken wire), MA board failure, or failure of the board/device named by the slave address. Resolution detail is on i2c.

### Other codes

For any code not in the families above, the cause and solution are in the per-model service manual. The log tells you which code and which device; the manual tells you what it means on that model.

## How a technician should respond

1. Open the error/warning info in the IPS Tool and read the most recent relevant entry.
2. Read the severity prefix. `ERR` means the unit stopped the image to protect itself, so treat it as a halt-level fault. `WAR` means the unit kept running with a limitation, so treat it as a degradation to investigate, not an outage.
3. Read the two-letter code and its Warning/Error Name to place it in a family (thermal/cooling, laser, communication, other).
4. Use the supporting fields to localize: Device ID and the device code next to the code identify the specific part; Operation time, ON count, and Projector Status give the operating context; temperature and fan values (via the conversion tool) show whether one spot is hot or the whole unit is hot.
5. Open the model-specific sub-item ("Laser" for YE, "Temp info" for TH) for the detailed sub-error, then follow the cause/solution path on the matching code page or in the service manual.

Codes, device names, slave addresses, and thresholds are model-specific. Always confirm against the service manual for the model in hand. See [[wiki/glossary]] for the abbreviations used throughout the log.

## Related pages

- [[wiki/concepts/ips-tool]]
- ips error code dictionary
- temperature log conversion tool
- ye
- [[wiki/error-codes/temp]]
- [[wiki/error-codes/fan]]
- [[wiki/error-codes/thermistor]]
- i2c
- [[wiki/glossary]]
