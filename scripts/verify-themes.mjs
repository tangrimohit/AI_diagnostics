// Verify all three themes: empty + loading per theme, plus the open theme menu.
// Caches the diagnose result from the first theme run to avoid 3× inference cost.

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

async function setTheme(id) {
  // Open the theme dropdown via the palette button.
  await page.click(".theme-btn");
  await page.waitForSelector(".theme-menu", { timeout: 4000 });
  await page.waitForTimeout(150);
  // Click the matching row.
  await page.locator(`.theme-row >> text="${id}"`).click();
  // Let the 200ms cross-fade finish.
  await page.waitForTimeout(350);
}

console.log("nav -> /");
await page.goto("http://localhost:8000/", { waitUntil: "networkidle" });
await page.waitForSelector(".empty-state .kanji", { timeout: 12000 });
await page.waitForTimeout(800); // let fonts settle

// --- AKARI Light (default) ---
await page.screenshot({ path: `${OUT}/theme-1-light-empty.png`, fullPage: false });
console.log("  light-empty captured");

// Open the theme menu for the dropdown screenshot
await page.click(".theme-btn");
await page.waitForSelector(".theme-menu", { timeout: 4000 });
await page.waitForTimeout(200);
await page.screenshot({ path: `${OUT}/theme-2-dropdown.png`, fullPage: false });
console.log("  dropdown captured");
// close the menu by clicking elsewhere
await page.click(".header");
await page.waitForTimeout(150);

// --- AKARI Dark ---
await setTheme("AKARI Dark");
await page.screenshot({ path: `${OUT}/theme-3-dark-empty.png`, fullPage: false });
console.log("  dark-empty captured");

// --- Epson ---
await setTheme("Epson");
await page.screenshot({ path: `${OUT}/theme-4-epson-empty.png`, fullPage: false });
console.log("  epson-empty captured");

// --- Loading state in Epson theme (proves the kanji breathe uses Epson blue) ---
await page.fill("textarea#problem", "EB-X49 yellow tint at 1200h");
await page.click(".btn-primary");
await page.waitForSelector(".loading-state .kanji", { timeout: 8000 });
await page.waitForTimeout(2000);
await page.screenshot({ path: `${OUT}/theme-5-epson-loading.png`, fullPage: false });
console.log("  epson-loading captured");

// --- Results in Epson (verify severity bars stay amber/green/red, not blue) ---
await page.waitForSelector(".diag-body", { timeout: 180000 });
await page.waitForTimeout(800);
await page.screenshot({ path: `${OUT}/theme-6-epson-results.png`, fullPage: true });
console.log("  epson-results captured");

// --- Switch back to AKARI Light, results should re-style ---
await setTheme("AKARI Light");
await page.screenshot({ path: `${OUT}/theme-7-light-results.png`, fullPage: true });
console.log("  light-results captured");

// --- Tight zoom: Dark theme solutions section ---
await setTheme("AKARI Dark");
await page.waitForTimeout(400);
const dark1100 = await ctx.newPage();
await dark1100.setViewportSize({ width: 1100, height: 1400 });
await dark1100.goto("http://localhost:8000/");
// already cached diagnose? probably not, render the page in dark and rely on cached body
await dark1100.waitForTimeout(800);
const solSec = page.locator(".solutions-section");
if (await solSec.count()) {
  await solSec.screenshot({ path: `${OUT}/theme-8-dark-solutions-zoom.png` });
  console.log("  dark-solutions-zoom captured");
}
await dark1100.close();

console.log();
console.log("=== console errors ===");
if (errors.length === 0) console.log("(none)");
else for (const e of errors) console.log("  " + e);

await browser.close();
