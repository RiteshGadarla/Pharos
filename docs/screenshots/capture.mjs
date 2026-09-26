// Captures the screenshots in docs/SCREENSHOTS.md from a running dev
// server. Playwright is already a frontend dependency, so this needs no
// extra install, but Node resolves its imports from the script's own
// directory: copy this file into frontend/ before running it.
//
//   make dev
//   cp docs/screenshots/capture.mjs frontend/
//   cd frontend && node capture.mjs && rm capture.mjs
//
// BASE overrides the dev server URL when Vite picks a different port.
//
// Pages are captured at 2x and downscaled back to the 1600px CSS width,
// which antialiases the small text far better than capturing at 1x. The
// downscale uses backend/.venv (Pillow comes in with the backend
// requirements), so run `make setup` first.

import { execFileSync } from 'node:child_process';
import { existsSync, mkdirSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { chromium } from 'playwright';

const BASE = process.env.BASE ?? 'http://localhost:5173';

// Walk up for PLAN.md rather than counting `..` segments, so the script
// finds the repo whether it is run from frontend/ or from where it lives.
const repoRoot = () => {
  let d = dirname(new URL(import.meta.url).pathname);
  for (let i = 0; i < 6; i++) {
    if (existsSync(resolve(d, 'PLAN.md'))) return d;
    d = dirname(d);
  }
  throw new Error('could not find the repo root (no PLAN.md above this script)');
};

const REPO = repoRoot();
const OUT = process.env.OUT ?? resolve(REPO, 'docs/screenshots');
const FIXTURES = resolve(REPO, 'backend/data/fixtures');
const PYTHON = resolve(REPO, 'backend/.venv/bin/python');

mkdirSync(OUT, { recursive: true });

// Moves the console to a numbered stage and lets deck.gl settle on the
// layers that stage turns on.
const gotoStage = async (page, n) => {
  await page.locator('.stage-step').nth(n - 1).click();
  await page.waitForTimeout(6000);
};

// Walks the time cursor back from the acquisition instant so the origin
// field is shown spread out rather than as the point it collapses to at
// t=0. `fraction` is how far back along the visible track to go.
const scrubBack = async (page, fraction) => {
  const slider = page.locator('input.scrubber-range');
  const { min, value } = await slider.evaluate((el) => ({ min: +el.min, value: +el.value }));
  await slider.fill(String(Math.round(value - (value - min) * fraction)));
  await page.waitForTimeout(4000);
  return page.locator('.scrubber-offset').innerText().catch(() => '?');
};

const shots = [
  {
    file: '01-landing.jpg',
    path: '/',
    ready: '.hero-brand-text strong',
    // The hero video autoplays; park it on a fixed frame so the capture is
    // deterministic instead of whatever frame the decoder happened to be on.
    after: async (page) => {
      await page.evaluate(async () => {
        const v = document.querySelector('video');
        if (!v) return;
        v.muted = true;
        try { await v.play(); } catch { /* autoplay blocked, seek anyway */ }
        v.currentTime = 6;
        await new Promise((r) => {
          if (v.readyState >= 2) return r();
          v.addEventListener('seeked', r, { once: true });
          setTimeout(r, 4000);
        });
        v.pause();
      });
      await page.waitForTimeout(1500);
    },
  },
  {
    file: '02-console-acquisition.png',
    path: '/run',
    ready: '.app-shell',
    after: (page) => gotoStage(page, 1),
  },
  {
    file: '03-console-drift.png',
    path: '/run',
    ready: '.app-shell',
    after: async (page) => {
      await gotoStage(page, 2);
      console.log(`     cursor: ${await scrubBack(page, 0.18)}`);
    },
  },
  {
    file: '04-console-attribution.png',
    path: '/run',
    ready: '.app-shell',
    after: (page) => gotoStage(page, 3),
  },
  {
    file: '05-inspector.png',
    path: '/inspect',
    ready: '.ins-drop-title',
    // An empty drop zone shows nothing about the page. The staged scene is
    // the one `make sample` runs, so the result matches the README and,
    // being a GeoTIFF, exercises the coordinates and km2 path.
    after: async (page) => {
      await page.setInputFiles('input[type=file]', `${FIXTURES}/synthetic_scene.tif`);
      await page.waitForSelector('.ins-button.is-primary:not([disabled])', { timeout: 30000 });
      await page.click('.ins-button.is-primary');
      await page.waitForSelector('.ins-running', { timeout: 15000 }).catch(() => {});
      await page.waitForSelector('.ins-running', { state: 'detached', timeout: 300000 });
      await page.waitForTimeout(2500);
    },
  },
];

// The console loads its bundle and paints the map before it is worth
// capturing; every /run shot waits on the same three things.
const consoleReady = async (page) => {
  await page.waitForSelector('.map-pane canvas', { timeout: 60000 });
  await page.waitForFunction(() => !document.querySelector('.loading'), null, { timeout: 60000 });
  await page.waitForTimeout(4000);
};

const browser = await chromium.launch({
  args: ['--no-sandbox', '--autoplay-policy=no-user-gesture-required'],
});
const ctx = await browser.newContext({
  viewport: { width: 1600, height: 1000 },
  deviceScaleFactor: 2,
  reducedMotion: 'reduce',
});

let failed = false;
for (const s of shots) {
  const page = await ctx.newPage();
  const errors = [];
  page.on('console', (m) => m.type() === 'error' && errors.push(m.text()));
  page.on('pageerror', (e) => errors.push(String(e)));
  try {
    await page.goto(BASE + s.path, { waitUntil: 'load', timeout: 60000 });
    await page.waitForSelector(s.ready, { timeout: 60000 });
    if (s.path === '/run') await consoleReady(page);
    if (s.after) await s.after(page);
    // The hero is a video frame, so JPEG costs nothing visually and a
    // quarter of the bytes. The UI pages stay PNG: they are mostly text.
    const jpeg = s.file.endsWith('.jpg');
    await page.screenshot({
      path: `${OUT}/${s.file}`,
      ...(jpeg ? { type: 'jpeg', quality: 92 } : {}),
    });
    console.log(`ok   ${s.path} -> ${s.file}${errors.length ? `  [console errors: ${errors.length}]` : ''}`);
    errors.slice(0, 5).forEach((e) => console.log(`     ! ${e.slice(0, 200)}`));
  } catch (e) {
    failed = true;
    console.log(`FAIL ${s.file}: ${e.message.split('\n')[0]}`);
    await page.screenshot({ path: `${OUT}/FAILED-${s.file}` }).catch(() => {});
  }
  await page.close();
}

await browser.close();

console.log(execFileSync(PYTHON, ['-c', `
import glob, os
from PIL import Image

for p in sorted(glob.glob(os.path.join(${JSON.stringify(OUT)}, "0*.*"))):
    im = Image.open(p).convert("RGB")
    if im.width <= 1600:
        continue
    im = im.resize((im.width // 2, im.height // 2), Image.LANCZOS)
    if p.endswith(".jpg"):
        im.save(p, "JPEG", quality=88, optimize=True, progressive=True)
    else:
        im.save(p, "PNG", optimize=True)
    print(f"  {os.path.basename(p):32} -> {im.width}x{im.height}  {os.path.getsize(p)/1e6:.2f} MB")
`], { encoding: 'utf8' }));

process.exit(failed ? 1 : 0);
