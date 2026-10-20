---
type: index
---

# AKARI Wiki — Index

Master catalog. Every wiki page is linked from here.

## Projector families

Shared diagnostic pages. Models on the same engineering platform share failure modes and service parts, so the family page is the primary reference and each model page is a thin stub that links to it.

- [[wiki/platforms/pu22-large-venue-laser/index]] — Large-venue laser (PU22 series): EB-PU2216B
- [[wiki/platforms/portable-co/index]] — Portable: CO-FH02

## Projectors

### EB-X49 lamp 3LCD family (shared chassis)
- [[wiki/projectors/eb-x49/index]] — EB-X49 (H982), primary documented model
 - [[wiki/projectors/eb-x49/specs]]
 - [[wiki/projectors/eb-x49/parts-reference]] — lamp, main board, ballast, optical engine

### Large-venue laser
- [[wiki/projectors/eb-pu2216b/index]] — EB-PU2216B

### Laser installation
- [[wiki/projectors/eb-l260f/index]] — EB-L260F

### Portable
- [[wiki/projectors/co-fh02/index]] — CO-FH02

## Error codes

Per-code pages written for the lamp 3LCD chassis family. Codes marked shared also occur on laser projectors but with different causes and parts, so for a laser model use that model's platform family page error reference rather than the lamp causes here.

- [[wiki/error-codes/temp]] — Internal overheat
- [[wiki/error-codes/fan]] — Fan error (fan hardware or board)
- [[wiki/error-codes/thermistor]] — Sensor error (Light Valve FPC or thermistor)

## Procedures
- [[wiki/procedures/diagnostic-workflow]] — canonical error workflow (IPS log to service manual to diagram)
- [[wiki/procedures/image-confirmation]] — confirming projected image quality (focus, uniformity, convergence, flare, pixel defects)

## Concepts
- [[wiki/concepts/ips-tool]] — capturing and reading IPS Tool TSV logs
- [[wiki/concepts/cooling-system]] — airflow, thermistor placement, fan-control feedback, warning/error escalation
- [[wiki/concepts/error-warning-framework]] — Error vs Warning indicators and how a log entry is read
- [[wiki/concepts/projector-model-naming]] — decoding Epson model numbers and the H-code join key
- [[wiki/concepts/technical-support-basics]] — structured support-case handling (gather, reproduce, isolate, escalate)

## Root pages
- [[wiki/overview]]
- [[wiki/glossary]]
