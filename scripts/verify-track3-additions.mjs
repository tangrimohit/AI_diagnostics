// Track 3 additions phase-gate screenshots:
//   1. New loading state with step list (multiple frames as phases advance)
//   2. Solution meta-block (no $$$, no minutes; Time = Quick/Moderate/Long with bars)
//   3. Disclaimer block above feedback

import { chromium } from "playwright";

const OUT = "C:/akari/data";
const browser = await chromium.launch();
const ctx = await browser.newContext({
  viewport: { width: 1440, height: 900 },
  deviceScaleFactor: 2,
});
const page = await ctx.newPage();

const errors = [];
page.on("pageerror", e => errors.push("pageerror: " + e.message));
page.on("console", m => { if (m.type() === "error") errors.push("console.error: " + m.text()); });

console.log("nav -> /");
await page.goto("http://localhost:8000/", { waitUntil: "networkidle" });
await page.waitForSelector(".empty-state .kanji", { timeout: 10000 });
await page.waitForTimeout(600);

console.log("submit");
await page.fill("textarea#problem", "EB-X49 yellow tint at 1200h");
await page.click(".btn-primary");

// Capture loading state at three points so we can see different active steps.
await page.waitForSelector(".step-list", { timeout: 8000 });
await page.waitForTimeout(800);
await page.screenshot({ path: `${OUT}/t3add-loading-1-early.png`, fullPage: false });
console.log("  loading-early captured");

// Wait a few seconds and capture again (analyzing phase likely active)
await page.waitForTimeout(6000);
await page.screenshot({ path: `${OUT}/t3add-loading-2-mid.png`, fullPage: false });
console.log("  loading-mid captured");

// Wait until just before result lands (drafting phase ~ near end)
// Poll by checking the current active step from the DOM
async function waitForDraftingOrDone(timeoutMs = 120000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const result = await page.evaluate(() => {
      const active = document.querySelector(".step.active .step-text")?.textContent || "";
      const hasResult = !!document.querySelector(".diag-body");
      return { active, hasResult };
    });
    if (result.hasResult) return "done";
    if (result.active.toLowerCase().includes("drafting")) return "drafting";
    await new Promise(r => setTimeout(r, 800));
  }
  return "timeout";
}
const phase = await waitForDraftingOrDone();
if (phase === "drafting") {
  await page.screenshot({ path: `${OUT}/t3add-loading-3-drafting.png`, fullPage: false });
  console.log("  loading-drafting captured");
}

// Wait for results
await page.waitForSelector(".diag-body", { timeout: 60000 });
await page.waitForTimeout(700);

// Zoom into the solutions section
const solSec = page.locator(".solutions-section");
if (await solSec.count()) {
  await solSec.screenshot({ path: `${OUT}/t3add-solutions-zoom.png` });
  console.log("  solutions-zoom captured (verify no $ / no minutes, Time has bars)");
}

// Zoom into the disclaimer
const disclaimer = page.locator(".disclaimer");
if (await disclaimer.count()) {
  await disclaimer.screenshot({ path: `${OUT}/t3add-disclaimer-zoom.png` });
  console.log("  disclaimer-zoom captured");
}

// Full results page
await page.screenshot({ path: `${OUT}/t3add-results-full.png`, fullPage: true });
console.log("  results-full captured");

console.log();
console.log("=== console errors ===");
if (errors.length === 0) console.log("(none)");
else for (const e of errors) console.log("  " + e);

await browser.close();
