---
type: concept
keywords: [cooling, airflow, fan, filter, dust, overheat, ventilation, thermistor]
---

# Projector cooling system

How Epson lamp projectors keep themselves at a safe operating temperature. Applies to the EB-X49 and the broader H971-H988 lamp family. Useful background for any TH (Temp) or FN (Fan) error case.

## Airflow

Two-fan system:

- **Intake fan**: pulls room air in through the filter intake.
- **Exhaust fan**: pushes hot air out through the exhaust vent.

In between, the air flow cools three zones:

1. **PBS** (Polarization Beam Splitter, part of the optical engine)
2. **Lamp** (light source)
3. **LCD panel** (the panels inside the optical engine)

Then the now-warm air exits via the exhaust fan.

## Thermistors (temperature sensors)

Three thermistor locations are documented:

- **PBS thermistor** — monitors temperature near the polarization beam splitter.
- **Lamp thermistor** — monitors temperature near the lamp module.
- **LCD panel thermistor** — monitors temperature near the LCD panels in the POP.

Plus the **MAB thermistor** on the main board itself (mentioned in the H971 family troubleshooting).

All are **NTC type** (Negative Temperature Coefficient): the thermistor's electrical resistance decreases as temperature rises. The main board reads each thermistor and uses the value to control fan speed and to decide whether a warning or error should be emitted.

## Fan control logic

The MAB reads thermistor voltages continuously. As any monitored zone heats up:

1. The MAB detects the rise in temperature.
2. It raises the voltage to the relevant fan (LCD panel fan and/or exhaust fan).
3. Fan rotational speed increases, pulling more air through.
4. If temperature keeps rising, fan voltage continues to rise until max speed.

This is a closed-loop temperature → fan-speed → temperature feedback. Under normal conditions it stabilizes well below the warning threshold.

The two fans respond in a staged order as heat builds, not simultaneously. The training reference shows a worked example measured on an EMP-73 unit in a 35°C ambient room:

1. Detection of a rise in heat at the LCD panel thermistor.
2. LCD panel fan voltage rises → its rotational speed increases first.
3. Detection of a continued rise in heat (lamp thermistor).
4. Exhaust fan voltage rises → its rotational speed increases.

So the panel-cooling fan typically spins up before the exhaust fan as a zone heats. The thermistor temperature trace lags the fan-voltage trace, which is the expected closed-loop behavior.

## Warning and error thresholds

When cooling can't keep up (clogged filter, high ambient, high altitude, blocked vents, failed fan, failed thermistor), the temperature climbs past the fan's ability to control. The escalation, in order of severity:

1. Cooling fan speed increases (normal response).
2. Maximum fan speed reached.
3. **High temp warning** (corresponds to TH Warning levels T2/T3 in the IPS log; image projection continues but with functional limitation).
4. **High temp error** (TH Error levels T4/T5).
5. **Shutdown** (projector cuts power to protect itself, "after a few minutes or at the same time" as high temp error per the cooling-system reference).

See [[wiki/error-codes/temp]] for the IPS log encoding.

## Effect of altitude / ambient temperature

The reference shows two temperature curves on the same time axis:

- **Normal environment** — temperature rises during warmup, stabilizes below warning threshold once fans equilibrate.
- **High altitude or high-temperature room** — temperature rises higher because thinner air (less cooling per fan rotation) or hotter intake air pushes the steady-state past the warning threshold and into error / shutdown.

This is why **high-altitude mode** is a configurable menu setting on the projector: enabling it changes the fan curve so that even thin air can sustain enough cooling. Mis-set high-altitude mode (off when actually at altitude) was the implicit hypothesis tested in.

## What this means for diagnostic suggestions

When a query touches TH / FN / SE errors on X49:

- First-pass cause is usually environmental (filter, vent obstruction, ambient temp, altitude). Always recommend cleaning the filter and confirming high-altitude mode before parts replacement.
- If environmental causes are ruled out, the next-likely component is the failing thermistor (SE error path; see [[wiki/error-codes/thermistor]]) or the fan itself (FN error path; see [[wiki/error-codes/fan]]).
- MA Board temperature-sensing circuit failure is the cause if the thermistor and fan check out and the unit still reports overheating. Confirmed in the H971 manual: "MA Board circuit error" when no actual abnormality.

## Related pages

- [[wiki/error-codes/temp]] (TH error/warning encoding)
- [[wiki/error-codes/fan]] (FN error)
- [[wiki/error-codes/thermistor]] (SE error)
- fan temperature (X49 case patterns)
- temperature log conversion tool (decode raw `temp?` values)
