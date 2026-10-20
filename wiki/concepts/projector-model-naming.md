---
type: concept
keywords: [model number, model name, naming convention, decode model, suffix, h-code]
---

# Projector Model Naming

Epson projector model numbers are built from a small set of repeated parts: a
letter **prefix** that ties the unit to a sales brand, a **body** that encodes
the panel resolution class plus a series/grade number, and optional **suffixes**
for body color, throw type, or revision. The same physical product is sold under
several prefixes at once, so the prefix tells you the brand line while the body
identifies the actual hardware. This page maps those parts back to the underlying
projector family.

For how the factory H-code relates to the model, see
h code attribution. Term definitions are in [[wiki/glossary]].

## How a model number breaks down

A modern model name reads as:

```
<prefix> - <resolution-class letter> <series number> <suffix>
```

Example shapes from the data:

- `EB-X25` — EB brand, X = XGA panel, series 25.
- `EB-W22` — EB brand, W = WXGA panel, series 22.
- `EB-U32` — EB brand, U = WUXGA panel, series 32.
- `EB-FH52` — EB brand, FH = Full HD (1080p) panel, series 52.
- `EH-TW5000` — EH brand, TW = home-theater wide line, series 5000.
- `EB-L1300U` — EB brand, L = laser light source, series 1300, U trailing = WUXGA.

The brightness and light source are **not** fully derivable from the name alone;
they are separate attributes (see Light source below). The name gives you the
brand, the panel resolution class, and a relative grade within the line.

## Brand prefixes

The same chassis ships under multiple two-letter prefixes that differ only by
sales channel or region/market variant. Treat siblings as the same unit for
diagnosis.

| Prefix | Line | Notes |
|--------|------|-------|
| `EB-` | Business / installation (the largest line) | Most common prefix in the data |
| `CB-` | Sibling of `EB-` for a different region/market | Same chassis, same H-code as the matching `EB-` |
| `EH-` | Home cinema | Often paired with `TW`/`LS` body codes |
| `CH-` | Sibling of `EH-` for a different region/market | Same chassis, same H-code as the matching `EH-` |
| `EF-` | Compact / lifestyle home | LED or laser light source |
| `EV-` | Lighting / "light source" projector line | Phosphor laser |
| `CO-` | Entry compact home line | Lamp-based |
| `MG-` | Small specialty line | Few entries |
| `PowerLite` | Brand name used alongside `EB-`/`CB-` | A full word, not a letter code |
| `BrightLink` | Interactive ultra-short-throw line | Models carry an `i` interactivity suffix |
| `MovieMate` | Older all-in-one home line | Legacy |

Legacy prefixes seen in older rows: `ELP-` and `EMP-` (early business/portable
lines) and `PowerLite` numbers without a letter body. These predate the
resolution-class-letter convention and use plain series numbers (e.g.
`EMP-7000`, `PowerLite 5000`).

### Sibling relationship

A single product row in the source frequently lists two or three model names
that share one H-code, for example `CB-...` next to the matching `EB-...`, or
`CH-...` next to the matching `EH-...`. These are the same hardware under
different brand prefixes for different regions/markets. Match on the H-code, not
the prefix.

## Resolution-class letter

In the model body, the leading letter of the body segment encodes the LCD panel
resolution class. Confirmed mappings from the data:

| Letter | Resolution class | Pixels (from the data) |
|--------|------------------|------------------------|
| `S` | SVGA | 800 x 600 |
| `X` | XGA | 1024 x 768 |
| `W` | WXGA | 1280 x 800 |
| `U` | WUXGA | 1920 x 1200 |
| `F` / `FH` | Full HD / 1080p | 1920 x 1080 |
| `Q` | 4K-class | listed as 1080p panel with 4K processing in recent rows |

Within one line, a higher series number is generally a higher grade (more
brightness or features) but this is relative, not a fixed formula. The resolution
class is fixed by the letter; the number ranks the variant.

## Suffixes

Trailing characters modify a base model. Observed suffixes:

- `W` (trailing on `EH-LS...`, `CH-...`) and `B` — body color variant (white vs
  black), same H-code differs only by the color row.
- `NL` — "no lens" version of a lens-interchangeable installation model
  (high-brightness lines). Same chassis, lens not bundled.
- `i` — interactive (e.g. `BrightLink ...Wi`, `...Ui`, `...Fi`).
- `+` — a refreshed or plus revision of the base model.
- `e`, `V`, `H`, `S`, `G`, `D`, `SK` — minor regional, mounting, or feature
  variants seen on entry/classroom models (e.g. `EB-X6` vs `EB-X62` vs `EB-X6e`).
- Suffix letters on `BrightLink` models (`Wi`, `Ui`, `Fi`) repeat the resolution
  class: `Wi` = WXGA interactive, `Ui` = WUXGA interactive, `Fi` = wide/FWXGA
  interactive.

## Light source

The source distinguishes three light-engine types. This is recorded in the lamp
column, not in the model name, though laser models often carry an `L` in the body
(e.g. `EB-L1300U`, `EH-LS670W`).

| Marker in data | Light source |
|----------------|--------------|
| Lamp part code (e.g. `LP96`, `LP97`) plus a wattage like `M200W`, `Y200W`, `U275W`, `P245W` | UHE lamp |
| `LD` | Laser diode |
| `蛍光体LD` | Phosphor laser |
| `LED` | LED |

In lamp models, the leading letter of the lamp wattage code (`Y`, `M`, `P`, `U`)
denotes the lamp grade/type and the number is wattage (e.g. `U275W` = a 275 W
U-grade lamp). Laser (`LD`), phosphor-laser, and LED models have a dash in the
lamp part column because they have no replaceable lamp. For lamp date-code
decoding see lamp date code decoding; laser-specific faults are
in ye errors laser only.

## Brightness and resolution attributes

Brightness (lumens) and exact panel pixels are stored as their own columns and
are not encoded positionally in the model number beyond the resolution-class
letter. Two models in the same line and resolution class can differ in brightness
(e.g. several `WUXGA` `EB-L....U` units span 5000 to 12000 lm). Always read the
stated lumen and pixel values rather than inferring them from the series number.

## Mapping a model number to its family

1. Strip the brand **prefix** (`EB-`, `CB-`, `EH-`, `CH-`, `EF-`, `EV-`, `CO-`,
   or a legacy `ELP-`/`EMP-`/`PowerLite`). Siblings collapse to one unit.
2. Read the **resolution-class letter** in the body (`S`/`X`/`W`/`U`/`F`/`Q`,
   and `L` indicating laser).
3. Use the **series number** as a relative grade within that line.
4. Note any **suffix** (`NL`, `i`, `+`, `B`/`W` color, etc.) for the exact
   variant.
5. Confirm the unit by its **H-code** (see h code attribution),
   which is shared across all sibling prefixes of one chassis.

## Factory code relationship

Every row carries a factory code in addition to the model name. Older units use
an `H` code (e.g. `H272`, `H7330`); newer units use `HA`, `HB`, or `HC` codes
(e.g. `HB820`, `HC130`). This code is the chassis-level identifier and is shared
by all brand-prefix siblings of the same product. When a model name is ambiguous
or rebranded across regions/markets, the factory code is the reliable join key.
Full attribution logic lives in h code attribution.
