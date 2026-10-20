---
type: procedure
applies_to: [all]
estimated_time_minutes: 30
difficulty: easy
---

# Diagnostic workflow (canonical 4-step)

The standard the manufacturer-recommended sequence for diagnosing a projector with an error. Distilled from the practical-level IPS Tool training. Use this as the outer loop for any error-based case.

## When to use

A customer or engineer reports an error or warning on a projector (any model). Before reaching for parts, work through these four steps in order.

## The four steps

### 1. Get the IPS log

Connect the projector to a PC via USB in VCOM mode and capture a TSV log via IPS Tool. See [[wiki/concepts/ips-tool]] for the full connection procedure.

What to look for in the log:
- **Error counter** sheet: which error codes have any occurrences (highlighted in orange when non-zero). Captures cumulative history.
- **Error/Warning Info** sheet: today's log, chronological. Date / time / sequence number / error code / projector status at the moment of the error.
- **Temp info** sheet (for TH errors): raw `temp?` readings. Decode using temperature log conversion tool.
- **Laser info** sheet (for YE errors, laser models only).

### 2. Check the per-model service manual

Look up the error code in the service manual's troubleshooting table. For X49 (H971-H988 family), see [[wiki/projectors/eb-x49/index]] and the per-error pages under `wiki/error-codes/`.

The manual's resolution is the **starting point**, not the final answer. The practical training documents multiple cases where the manual's standard remedy didn't fully resolve the error.

### 3. Check the diagram

When the standard remedy doesn't resolve the issue, **look at the wiring / block diagram in the service manual**. Identify parts adjacent to the suspected component. Example from the training:

- TH error survived LLC-MP + MA + P4COMBO replacement. **LDDR sits between MAB and LLC on the block diagram**, so it's the next-most-likely cause. Replacing LDDR resolved the issue.
- I2C error at slave address 0088 survived MA + DR + cable replacements. The detailed connection diagram revealed an RLY Board between RCN and MA carrying a separate FFC cable that hadn't been checked. Replacing the FFC,220-H874 resolved it.

The principle: **the failing device may be electrically adjacent to the one you've already replaced**. Block diagrams expose that adjacency.

### 4. Ask CS member by depot

If steps 1-3 don't resolve, escalate to the manufacturer via the depot ticket process. Provide the IPS log, the parts you've already replaced (with PNs and serial), and a hypothesis. the manufacturer has analysis tools the depot doesn't (e.g. teardown of returned units that revealed a burnt DC connector pin in the EF-12 case).

When escalating from L3, this follows the path documented in critical issues ( is the canonical the field escalation that needed the manufacturer engagement).

## Expected outcome

The error stops recurring after the right part is replaced, the firmware is updated, or the cable is reseated.

## If it fails

Repeat from step 2 with the next-suspected part per the service manual ordering, or with a part adjacent in the diagram to what you've already replaced. After 3-4 unsuccessful replacements, escalate to the manufacturer rather than continuing the parts-swap loop.

## Related pages

- [[wiki/concepts/ips-tool]]
- temperature log conversion tool
- optical engine image troubleshooting
- critical issues
- i2c
- [[wiki/error-codes/fan]]
- [[wiki/error-codes/temp]]
