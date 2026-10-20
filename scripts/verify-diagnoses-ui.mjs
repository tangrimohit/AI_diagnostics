// Playwright check: Diagnoses tab compiles, chip is a reasonable size, and the
// LAST column's filter popover opens fully within the viewport (no overflow).
import { chromium } from "playwright";
import { mkdirSync } from "node:fs";

const OUT = "C:/akari/data";
mkdirSync(OUT, { recursive: true });

const browser = await chromium.launch();
const page = await browser.newContext({ viewport: { width: 1600, height: 1000 } }).then(c => c.newPage());
const errors = [];
page.on("pageerror", e => errors.push("pageerror: " + e.message));
page.on("console", m => { if (m.type() === "error") errors.push("console.error: " + m.text()); });

await page.goto("http://127.0.0.1:8000/admin", { waitUntil: "networkidle", timeout: 30000 });
let ok = true;
try {
  await page.getByText("Diagnoses", { exact: true }).first().click();
  await page.waitForSelector("text=Show service / headless", { timeout: 15000 });
} catch (e) { ok = false; errors.push("nav/render: " + e.message); }

const chips = page.locator("thead .th-filter");
const nChips = await chips.count();
const chipBox = await chips.first().boundingBox();

// Open the LAST column's filter (Feedback) and check the popover stays on screen
let popRight = null, vw = await page.evaluate(() => window.innerWidth);
let withinViewport = false, popItems = 0;
try {
  await chips.nth(nChips - 1).click();
  await page.waitForSelector(".cf-pop", { timeout: 5000 });
  const box = await page.locator(".cf-pop").boundingBox();
  popRight = box.x + box.width;
  withinViewport = popRight <= vw - 1 && box.x >= 0;
  popItems = await page.locator(".cf-pop .cf-item").count();
  await page.screenshot({ path: OUT + "/verify-diagnoses-lastcol.png", fullPage: false });
} catch (e) { errors.push("last-col popover: " + e.message); }

console.log("JSX compiled / tab opened:", ok);
console.log("chips:", nChips, "| chip size:", chipBox ? Math.round(chipBox.width) + "x" + Math.round(chipBox.height) + "px" : "n/a");
console.log("last-col popover items:", popItems);
console.log("viewport width:", vw, "| popover right edge:", popRight ? Math.round(popRight) : "n/a", "| within viewport:", withinViewport);
console.log("PAGE ERRORS:", errors.length);
errors.slice(0, 10).forEach(e => console.log("   " + e));
await browser.close();
process.exit(errors.length === 0 && ok && withinViewport ? 0 : 1);
