// Tight screenshots: zoom into the solutions section + admin diag detail.

import { chromium } from "playwright";

const OUT = "C:/akari/data";
const browser = await chromium.launch();
const ctx = await browser.newContext({
  viewport: { width: 1100, height: 1400 },
  deviceScaleFactor: 2,
});
const page = await ctx.newPage();

// User UI — wait for the cached diagnosis we just ran (or run again if cache miss)
await page.goto("http://localhost:8000/");
await page.fill('textarea#problem', "EB-X49 yellow tint at 1200h");
await page.click(".btn-primary");
await page.waitForSelector(".diag-body", { timeout: 180000 });
await page.waitForTimeout(800);

const solSec = page.locator(".solutions-section");
if (await solSec.count()) {
  await solSec.screenshot({ path: `${OUT}/verify-ui-5-solutions-zoom.png` });
}

// Click first solution to expand and zoom that one card
await page.locator(".solution-head").first().click();
await page.waitForTimeout(300);
const firstSol = page.locator(".solution").first();
await firstSol.screenshot({ path: `${OUT}/verify-ui-6-solution-expanded-zoom.png` });

// Admin UI
console.log("nav admin");
await page.goto("http://localhost:8000/admin");
await page.waitForSelector("table", { timeout: 8000 }).catch(() => {});
await page.waitForTimeout(800);
await page.screenshot({ path: `${OUT}/verify-ui-7-admin.png`, fullPage: false });

// Click first diagnoses row to open the detail modal
await page.goto("http://localhost:8000/admin#tab=diagnoses").catch(() => {});
await page.waitForTimeout(500);
const tab = page.getByText(/diagnoses/i).first();
if (await tab.count()) {
  await tab.click().catch(() => {});
  await page.waitForTimeout(800);
  const firstRow = page.locator(".row-link").first();
  if (await firstRow.count()) {
    await firstRow.click();
    await page.waitForTimeout(600);
    await page.screenshot({ path: `${OUT}/verify-ui-8-admin-detail.png`, fullPage: true });
  }
}

await browser.close();
console.log("done");
