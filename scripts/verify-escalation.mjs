// Playwright check of the expanded escalation draft (gap highlighting).
// Drives the dev server on :8001, submits the canonical X49 query, waits for
// results, and screenshots the escalation card + the full results page.

import { chromium } from "playwright";
import { mkdirSync } from "node:fs";

const BASE = process.env.AKARI_BASE || "http://127.0.0.1:8001";
const OUT = "C:/akari/data";
mkdirSync(OUT, { recursive: true });

const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1440, height: 1200 }, deviceScaleFactor: 2 });
const page = await ctx.newPage();
const errors = [];
page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));
page.on("console", (m) => { if (m.type() === "error") errors.push(`console.error: ${m.text()}`); });

await page.goto(`${BASE}/`, { waitUntil: "load" });
await page.waitForSelector("textarea#problem", { timeout: 15000 });
await page.fill("textarea#problem", "EB-X49 yellow tint on projection after 1200 hours");
// Model is now a required combobox: open it, filter, pick EB-X49.
await page.click("#model-combo-trigger");
await page.fill(".model-combo-search", "X49");
await page.locator(".model-combo-list .combo-opt", { hasText: "EB-X49" }).first().click();
await page.waitForSelector(".btn-primary:not([disabled])", { timeout: 5000 });
await page.click(".btn-primary");
console.log("submitted; waiting for results (up to 180s)");
await page.waitForSelector(".escalation", { timeout: 180000 });
await page.waitForTimeout(400);

const card = page.locator(".escalation");
await card.scrollIntoViewIfNeeded();
await card.screenshot({ path: `${OUT}/verify-escalation-card.png` });
await page.screenshot({ path: `${OUT}/verify-escalation-full.png`, fullPage: true });

const gaps = await page.locator(".escalation .needs-input").count();
const hint = await page.locator(".escalation-hint").count();
const rows = await page.locator(".escalation-row").count();
console.log(`rows=${rows} highlighted-gaps=${gaps} hint=${hint ? "shown" : "absent"}`);
console.log("console errors:", errors.length ? errors : "(none)");

await browser.close();
