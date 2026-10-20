---
type: procedure
keywords: [image quality, focus, uniformity, color uniformity, convergence, dead pixel, test pattern, flare]
applies_to: [all]
difficulty: easy
---

# Image Confirmation Procedure

Standard visual quality check for a projected image. Use it to confirm image
quality before or after a repair by inspecting eight categories: color
uniformity, color binding, dust/scratch/dirt, pixel defect, convergence
(pixel misalignment), flare, and focus.

## When to use

- Before repair, to characterize the reported image fault.
- After repair, to confirm the projected image meets quality expectations.
- Whenever a unit needs a structured pass over the optical image quality.

The eight check categories, in order:

1. Preparation
2. Color uniformity
3. Color binding
4. Dust, scratch, and dirt
5. Pixel defect
6. Convergence (pixel misalignment)
7. Flare
8. Focus

## Prerequisites

Set up the unit before any measurement (step "Preparation"):

1. Set the projection distance per the projector's spec.
2. Set the lens zoom to maximum wide.
3. Set the screen size to 60 inches.
4. Input a signal at the same resolution as the product's native resolution.
5. Take measurements only after the lamp has operated for 3 minutes.

You will also need the test patterns referenced below (white at 0%, 1.7%, 50%,
and 100%, plus cross hatch and H patterns), an ND filter for pixel-defect
inspection, and a sheet of white paper for the focus measurement.

## Steps

### 1. Color uniformity

Color uniformity is non-uniformity of color tone across the screen. Each of the
R, G, and B panels can vary in brightness depending on which part of the panel
you look at, so the overall image shows uneven illuminance and color (for
example red, orange, yellow, green, magenta, or cyan tints in different zones).
Projectors use many optical parts (polarization plate, light valve, contrast-
improving parts, dichroic mirror, and so on), so projecting without any color
unevenness is not easy. When projecting gray, the color uniformity correction
function works to even out the color.

Check pattern: white at 100%, 50%, 1.7%, and 0% (white 0% equals black).

Measurement method:

1. Look at the screen and check for uneven color uniformity.
2. Identify the two points (A and B) with the most different color.
3. Calculate the difference using the formula on the u, v color values of the
   two points: (u1 - u2) + (v1 - v2), where point A is (u1, v1) and point B is
   (u2, v2).

### 2. Color binding

Color binding is a color shift seen at the edges of the screen, top-to-bottom or
left-to-right. The cause is an optical part (lens or mirror) that has moved
slightly out of its correct position.

Check pattern: white 100%.

Confirmation method:

1. Apply a shock by dropping the unit about 2 inches on the right/left sides and
   the front/back sides.
2. After the shock, check for color binding again.

### 3. Dust, scratch, and dirt

Dust, scratch, and dirt appear as a shadow-like mark on the screen. The cause is
a flaw in the TFT panel or optical lens, or dust that has entered the projector
engine.

Check pattern: white 100% and white 0%.

Confirmation method: focus on the screen and check whether dust, scratches, or
dirt are visible. Do not focus on the dust or dirt itself.

### 4. Pixel defect

Pixel defect is an LCD panel defect. Types:

- Bright pixel defect: light passes through a dot pixel of the TFT panel.
- Black pixel defect: light does not pass through a dot pixel of the TFT panel.
- Chain of pixel defect: connected pixel defects spanning more than two dots.
- Micro pixel defect: dim light passes through a dot pixel of the TFT panel.

Check patterns depend on defect type and on whether the unit is a home or
business projector:

| Defect | Home PJ | Business PJ |
|---|---|---|
| Bright pixel | W1.7%, W50%, W0% | W1.7%, W0% |
| Black pixel | W100%, W50%, W0% | W100%, W1.7% |
| Chain | W100%, W1.7%, W50%, W0% | W100%, W1.7%, W0% |
| Micro | W100%, W1.7%, W50%, W0% | W100%, W1.7%, W50%, W0% |

Confirmation method:

1. Look at the screen through an ND filter.
2. Confirm the transmissivity of the pixel defect through the ND filter.

### 5. Convergence (pixel misalignment)

Convergence is a misadjustment between the red, green, and blue LCD panels.
Misalignment is measured as horizontal distance (ΔH) and vertical distance (ΔV)
of the red and blue lines relative to the green panel, which is used as the
reference, expressed against pixel pitch (ΔHmax, ΔVmax).

Check pattern: cross hatch pattern.

Confirmation method: focus on the screen and look for the point of worst
convergence.

### 6. Flare

Flare is a tail of light that appears when projecting a high-contrast image or
picture on the screen. It can be characterized by its width in pixels (for
example 1-pixel flare or 2-pixel flare).

Check pattern: H pattern or cross hatch pattern.

Confirmation method: focus on the screen and measure the flare.

### 7. Focus

Focus error is when a projector focused on the screen still ends up out of
focus.

Measurement method:

1. Focus fully on the screen at the 60-inch screen size.
2. Place a sheet of white paper at the screen position.
3. Slide the white paper forward and back and measure the focus limit distance
   (the measured distance to the focus limit).

## What to look for

- Color uniformity: even color tone across the whole screen; flag any zone that
  reads noticeably darker, brighter, or color-shifted from the rest.
- Color binding: color fringing at the screen edges, especially after the shock
  test.
- Dust/scratch/dirt: shadow-like marks visible when focused on the screen.
- Pixel defect: bright, black, chain, or micro defects seen through the ND
  filter on the prescribed white patterns.
- Convergence: R/B lines offset from the G reference at the worst point.
- Flare: the light tail width in pixels on high-contrast patterns.
- Focus: the focus limit distance from the white-paper slide test.

## If it fails

If the image fails any category, investigate the matching optical or panel
cause: optical part position for color binding, TFT panel or lens flaws and
engine contamination for dust/scratch/dirt and pixel defects, and panel
alignment for convergence. Continue with optical engine teardown and
adjustment.

## Related pages

- optical engine image troubleshooting
- product inspection
- test patterns
