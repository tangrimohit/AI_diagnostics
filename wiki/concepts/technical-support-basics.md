---
type: concept
keywords: [gather information, reproduce, isolate, escalate, support case, diagnostic process]
---

# Technical Support Basics for Projector Service

## Definition

A structured approach to handling a projector support case. The goal is to move
from a reported symptom to an isolated cause, using knowledge of how the
projector is built and how its parts can fail. The service training this page is
drawn from frames diagnosis as mapping a failure symptom back to the cause part,
then confirming with checks before any part is replaced.

## Context

Effective diagnosis depends on knowing the major subsystems and how they
interact, because a single visible symptom (no power, no image, dark image,
color problem, shutdown) can originate in several different parts. The training
organizes this as a "relationship of failure symptom and cause parts" model:
each symptom has a short list of candidate causes, and each candidate is
confirmed or ruled out with specific checks.

Key subsystems referenced:
- Power supply unit (converts AC 100 to 240V input into DC rails such as 5, 13,
  18V for the main board, and supplies the ballast).
- Ballast and lamp (the ballast controls lamp power and detects lamp-on, cover,
  and over-temperature conditions).
- Main board (MAB), which drives image processing and cooling control.
- Cooling system: intake fan, exhaust fan, and thermistors that detect
  temperature rise and adjust fan voltage. See [[wiki/concepts/cooling-system]].
- Optical engine and its optical parts. See internal structure.

## The structured support approach

### 1. Gather information

Collect what is known about the unit and the fault before touching it:
- The reported symptom (no power, no image, color problem, dark image,
  shutdown, lamp fault).
- Connection and setting state: whether AV and signal cables are connected, and
  whether the source/output equipment is set correctly. Component connections in
  particular are a known source of color problems.
- Environment. Brightness loss and other degradation track strongly with
  operating environment. The training shows brightness reduction over hours from
  dust/sand and from smoking environments, and contamination (dust, cigarette
  residue) on optical parts as a cause of a dark image.
- For lamp issues, the lamp Lot No. The lamp carries a printed manufacturing date
  and other identifying information. If the Lot No. is reported when a lamp
  problem occurs, the manufacture date and any past history for that lamp can be
  retrieved. See lamp date code decoding.

### 2. Reproduce and observe the fault

Confirm the symptom directly and classify it, because the candidate-cause list
depends on which symptom you actually see. The training distinguishes between, for
example, lamp symptoms (arc tube crack, no lamp on, shutdown, blackening, white
spot) and system-level symptoms (no power, no image, color problem, dark).
Observing the exact symptom narrows the search before any disassembly.

### 3. Isolate the cause

For each confirmed symptom, work through its candidate causes and the
corresponding checks. The training pairs symptoms with cause checks as follows.

**No power on.** Possible causes: broken power supply unit, broken ballast,
broken fan, broken lamp, broken main board (MAB). Checks: is the thermistor
connected, is the fan connected, is the lamp cover closed, is the control panel
state correct.

**Shutdown.** Possible causes: broken fan, broken power supply unit, broken
ballast, broken lamp. Checks: is the air filter dusty, has the intake/exhaust
opening been blocked, is the thermistor connected at the correct position, is the
fan connected at the correct position, is the MAB broken. (A blocked or dusty
airflow path drives overheating, which is why dust and blockage appear under a
shutdown symptom.)

**No image.** Checks: is the AV cable connected, is the output equipment setting
correct, is the light valve (L/V) cable connected, is the MAB broken.

**Color problem.** Checks: is the L/V cable connected, is the MAB broken, is the
output equipment setting correct (especially at component connection),
deterioration of optical parts, dirt on optical parts, gap/misalignment of
optical parts from damage such as a fall.

**Dark image.** Checks: lamp deterioration, deterioration of optical parts, dirt
on optical parts, gap/misalignment of optical parts from damage such as a fall,
dirt from cigarette smoke or dust.

### Lamp-specific isolation

Lamp faults map to causes as follows:
- Arc tube broken or cracked: high temperature, distortion, transformation, seal
  crack.
- No lamp on: mercury adhering between the arc tubes (which prevents voltage from
  being applied), a broken arc tube, a ballast mismatch, or a ballast defect.
- Shutdown: unstable interelectrode distance making interelectrode voltage
  unstable, a halogen-cycle problem (influence of impurities), a ballast mismatch
  or a ballast defect.
- Blackening: low-temperature operation, halogen-cycle problem (impurities).
- White spot: high-temperature operation, halogen-cycle problem (impurities).

See lamp failures for model-specific lamp
detail.

### 4. What to record

Capture enough to support a decision or a handover:
- The symptom as observed and classified.
- The unit's environment (dusty, sand, smoking, high heat) when relevant to
  brightness loss or contamination.
- For lamp faults, the lamp Lot No., which links the part back to its manufacture
  date and history.
- Which checks were performed and their results (cable connections, filter/airflow
  state, thermistor and fan connection and position, cover and control-panel
  state).
- The suspected cause part and the reasoning that pointed to it.

### 5. When and how to escalate

Escalate when the candidate causes cannot be isolated locally, or when the
suspected cause points to a part or condition that requires manufacturer
attention. When escalating, provide the recorded symptom, the environment, the
checks already performed with their results, and, for lamp cases, the lamp Lot
No. so manufacture date and any prior history can be looked up. Keep the
escalation factual and grounded in what was observed and checked.

## Examples

- A unit that will not power on: confirm the lamp cover is closed and the control
  panel state is correct, verify the thermistor and fan are connected, then
  consider a broken power supply unit, ballast, fan, lamp, or MAB.
- A unit that shuts down during use: check the air filter for dust and the
  intake/exhaust openings for blockage first (cheap, reversible), then verify
  thermistor and fan connection and position, before suspecting a broken fan,
  power supply unit, ballast, or lamp.
- A dim image: weigh lamp deterioration and optical-part contamination
  (including dust and cigarette residue) against optical-part misalignment from a
  drop.

## Related pages

- [[wiki/procedures/diagnostic-workflow]]
- [[wiki/concepts/error-warning-framework]]
- [[wiki/concepts/ips-tool]]
- [[wiki/concepts/cooling-system]]
- internal structure
- lamp date code decoding
- optical engine image troubleshooting
