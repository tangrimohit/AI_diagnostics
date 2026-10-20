// Playwright verification of the Knowledge Gaps admin tab against the
// throwaway instance on :8001. Captures console errors, clicks the tab,
// verifies the table renders, exercises mark-addressed, screenshots.

import { chromium } from "playwright";
import { mkdirSync } from "node:fs";

const OUT = "C:/akari/data";
mkdirSync(OUT, { recursive: true });
const BASE = "http://127.0.0.1:8001";

const browser = await chromium.launch();
const page = await (await browser.newContext({ viewport: { width: 1440, height: 900 } })).newPage();

const errors = [];
page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));
page.on("console", (m) => { if (m.type() === "error") errors.push(`console.error: ${m.text()}`); });

console.log("nav -> /admin");
await page.goto(`${BASE}/admin`, { waitUntil: "load" });
await page.waitForSelector(".tabs", { timeout: 15000 });

// click the Knowledge Gaps tab
await page.getByRole("button", { name: "Knowledge Gaps" }).click();
await page.waitForSelector("table", { timeout: 8000 });
const rowCount = await page.locator("tbody tr").count();
console.log(`  gaps table rendered, ${rowCount} body rows`);
await page.screenshot({ path: `${OUT}/verify-gaps-1.png`, fullPage: true });

// expand examples on first row if present
const exBtn = page.getByRole("button", { name: /examples/ }).first();
if (await exBtn.count()) {
  await exBtn.click();
  await page.waitForTimeout(200);
  console.log("  examples expanded");
}

// mark first gap addressed, then verify it disappears (default hides addressed)
const before = await page.locator("tbody tr").count();
const markBtn = page.getByRole("button", { name: "mark addressed" }).first();
if (await markBtn.count()) {
  await markBtn.click();
  await page.waitForTimeout(600);
  const after = await page.locator("tbody tr").count();
  console.log(`  mark addressed: rows ${before} -> ${after}`);
  // turn on "show addressed" and confirm it returns with addressed styling
  await page.getByText("show addressed").click();
  await page.waitForTimeout(600);
  const withAddressed = await page.locator("tr.gap-addressed").count();
  console.log(`  show-addressed rows: ${withAddressed}`);
}
await page.screenshot({ path: `${OUT}/verify-gaps-2.png`, fullPage: true });

console.log("\n=== Browser console errors ===");
console.log(errors.length === 0 ? "(none)" : errors.map((e) => "  " + e).join("\n"));
await browser.close();
