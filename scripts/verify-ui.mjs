// Playwright verification of the redesigned user UI.
// Drives http://localhost:8000 through the three visual states (empty,
// loading, results) and saves screenshots to data/verify-ui-*.png.

import { chromium } from "playwright";
import { mkdirSync } from "node:fs";

const OUT = "C:/akari/data";
mkdirSync(OUT, { recursive: true });

const browser = await chromium.launch();
const ctx = await browser.newContext({
  viewport: { width: 1440, height: 900 },
  deviceScaleFactor: 1,
});
const page = await ctx.newPage();

const errors = [];
page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));
page.on("console", (m) => {
  if (m.type() === "error") errors.push(`console.error: ${m.text()}`);
});

// 1. Empty state
console.log("nav -> /");
await page.goto("http://localhost:8000/", { waitUntil: "load" });
await page.waitForSelector(".empty-state .kanji", { timeout: 15000 });
await page.screenshot({ path: `${OUT}/verify-ui-1-empty.png`, fullPage: true });
console.log("  empty-state captured");

// 2. Loading state — submit a query, screenshot mid-inference
console.log("submit canonical query");
await page.fill('textarea#problem', "EB-X49 yellow tint at 1200h");
await page.click(".btn-primary");
await page.waitForSelector(".loading-state .kanji", { timeout: 8000 });
// Give the breathing animation ~2s of cycle for the screenshot to catch it mid-pulse.
await page.waitForTimeout(2000);
await page.screenshot({ path: `${OUT}/verify-ui-2-loading.png`, fullPage: true });
console.log("  loading-state captured");

// 3. Results — wait until the diag-body renders (or 180s)
console.log("waiting for results (up to 180s)");
await page.waitForSelector(".diag-body", { timeout: 180000 });
// Let solutions/escalation mount.
await page.waitForTimeout(500);
await page.screenshot({ path: `${OUT}/verify-ui-3-results.png`, fullPage: true });
console.log("  results captured");

// 4. Click first solution to expand reasoning, screenshot expanded state
const firstSolutionHead = page.locator(".solution-head").first();
if (await firstSolutionHead.count()) {
  await firstSolutionHead.click();
  await page.waitForTimeout(250);
  await page.screenshot({ path: `${OUT}/verify-ui-4-solution-expanded.png`, fullPage: true });
  console.log("  solution-expanded captured");
}

console.log();
console.log("=== Browser console errors ===");
if (errors.length === 0) console.log("(none)");
else for (const e of errors) console.log("  " + e);

await browser.close();
