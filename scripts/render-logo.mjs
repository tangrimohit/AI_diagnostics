// Render the AKARI primary lockup to a crisp transparent PNG so it can be used
// as the login-page logo (fonts baked in by rendering).
import { chromium } from "playwright";

const OUT = "C:/akari/data/akari-login-logo.png";
const SCALE = 3; // 360x160 viewBox -> 1080x480 PNG

const svg = `
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 360 160" width="${360 * SCALE}" height="${160 * SCALE}">
  <style>
    .dot   { fill: #D69D3F; }
    .kanji { fill: #1A1A1A; font-family: "Noto Sans JP","Yu Gothic",sans-serif; font-weight: 400; }
    .mark  { fill: #1A1A1A; font-family: "Inter","Segoe UI",sans-serif; font-weight: 300; letter-spacing: 5px; }
    .tag   { fill: #807468; font-family: "Inter","Segoe UI",sans-serif; font-weight: 400; }
  </style>
  <circle class="dot" cx="60" cy="40" r="32" opacity="0.10" />
  <circle class="dot" cx="60" cy="40" r="20" opacity="0.25" />
  <circle class="dot" cx="60" cy="40" r="11" />
  <text class="kanji" x="60" y="118" font-size="32" text-anchor="middle">明かり</text>
  <text class="mark" x="138" y="100" font-size="26">AKARI</text>
  <text class="tag"  x="138" y="122" font-size="11">Bringing light to every case</text>
</svg>`;

const html = `<!doctype html><html><head>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400&family=Noto+Sans+JP:wght@400&display=swap" rel="stylesheet">
<style>html,body{margin:0;padding:0;background:transparent}#wrap{display:inline-block}</style>
</head><body><div id="wrap">${svg}</div></body></html>`;

const browser = await chromium.launch();
const page = await browser.newPage({ deviceScaleFactor: 1 });
await page.setContent(html, { waitUntil: "networkidle" });
try { await page.evaluate(() => document.fonts.ready); } catch {}
await page.waitForTimeout(600);
const el = await page.$("#wrap");
await el.screenshot({ path: OUT, omitBackground: true });
await browser.close();
console.log("WROTE", OUT);
