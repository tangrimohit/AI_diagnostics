// Playwright: load /admin/health as a browser, confirm the dashboard renders
// (status state, indicator dots, cards) with no JS errors. Screenshot for review.
import { chromium } from "playwright";
import { mkdirSync } from "node:fs";
const OUT = "C:/akari/data";
mkdirSync(OUT, { recursive: true });

const browser = await chromium.launch();
const page = await browser.newContext({ viewport: { width: 900, height: 760 } }).then(c => c.newPage());
const errors = [];
page.on("pageerror", e => errors.push("pageerror: " + e.message));
page.on("console", m => { if (m.type() === "error") errors.push("console.error: " + m.text()); });

await page.goto("http://127.0.0.1:8000/admin/health", { waitUntil: "networkidle", timeout: 30000 });
let state = null, dots = 0, labels = [];
try {
  await page.waitForSelector(".state", { timeout: 10000 });
  state = (await page.locator(".state").first().textContent()).trim();
  dots = await page.locator(".dot").count();
  labels = await page.locator(".lbl").allTextContents();
} catch (e) { errors.push("render: " + e.message); }
await page.waitForTimeout(500);
await page.screenshot({ path: OUT + "/verify-health.png", fullPage: true });

console.log("state banner:", JSON.stringify(state));
console.log("indicator dots:", dots);
console.log("cards:", labels.join(" | "));
console.log("PAGE ERRORS:", errors.length);
errors.slice(0, 10).forEach(e => console.log("   " + e));
await browser.close();
process.exit(errors.length === 0 && state ? 0 : 1);
