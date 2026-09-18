#!/usr/bin/env node
/**
 * Social share card generator.
 *
 * Hugo renders a 1200x630 card for home + every page as a second HTML output
 * at <page>/og.html (see config/_default/hugo.toml, layouts/_default/
 * baseof.ogcard.html, layouts/partials/og-card.html). This script screenshots
 * those into static/og/<key>.jpg with Chromium, so the cards use the real
 * site CSS (the theme's own compiled main.scss) and the actual scans.
 *
 * The results are committed to the repo, and a card is only re-rendered when
 * something that affects how it looks has changed. data/og/manifest.json
 * records, per page, a hash of the rendered og.html (with the inlined
 * <style> block stripped, since that's the whole compiled stylesheet and
 * would churn every card whenever an unrelated page's CSS changed) combined
 * with a hash of the card templates themselves. On a site that rarely
 * changes, `npm run og` is a no-op.
 *
 *   npm run og          render missing/stale cards
 *   npm run og:check    exit 1 if any card is missing or stale (no browser)
 *
 * Run `hugo --minify` first — this reads from public/.
 */

import fs from 'node:fs';
import path from 'node:path';
import http from 'node:http';
import crypto from 'node:crypto';

const ROOT = process.cwd();
const PUBLIC = path.join(ROOT, 'public');
const OUT_DIR = path.join(ROOT, 'static', 'og');
const MANIFEST = path.join(ROOT, 'data', 'og', 'manifest.json');
const DEFAULT_KEY = '__default__';

const WIDTH = 1200;
const HEIGHT = 630;
const QUALITY = 88;

const checkOnly = process.argv.includes('--check');

// ─── Discovery ───────────────────────────────────────────────────────────────

/** Every og.html under public/, keyed by the page path it belongs to. */
function findCards(dir = PUBLIC) {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) return findCards(full);
    if (entry.name !== 'og.html') return [];
    const rel = path.relative(PUBLIC, path.dirname(full));
    // public/og.html -> "home"; public/1931-1939-courting--marriage/og.html -> "1931-1939-courting--marriage"
    return [{ key: rel === '' ? 'home' : rel.split(path.sep).join('/'), file: full }];
  });
}

const sha256 = (...parts) => {
  const h = crypto.createHash('sha256');
  for (const part of parts) h.update(part);
  return h.digest('hex');
};

/**
 * Styling/template inputs shared by every card. A change to any of these
 * should re-render everything, not just the page that was edited.
 */
const globalTemplateHash = sha256(
  ...['layouts/partials/og-card.html', 'layouts/_default/baseof.ogcard.html'].map((f) =>
    fs.readFileSync(path.join(ROOT, f)),
  ),
);

/**
 * A card's identity: its rendered markup, minus the inlined stylesheet (the
 * full compiled CSS, identical on every card, which would otherwise
 * invalidate the whole set any time an unrelated template changed a class).
 */
const cardHash = (file) =>
  sha256(globalTemplateHash, fs.readFileSync(file, 'utf8').replace(/<style>[\s\S]*?<\/style>/, ''));

function readManifest() {
  try {
    return JSON.parse(fs.readFileSync(MANIFEST, 'utf8'));
  } catch {
    return {};
  }
}

function writeManifest(manifest) {
  const sorted = Object.fromEntries(Object.keys(manifest).sort().map((k) => [k, manifest[k]]));
  fs.mkdirSync(path.dirname(MANIFEST), { recursive: true });
  fs.writeFileSync(MANIFEST, JSON.stringify(sorted, null, 2) + '\n');
}

const outFile = (key) => (key === DEFAULT_KEY ? path.join(ROOT, 'static', 'og-default.jpg') : path.join(OUT_DIR, `${key}.jpg`));

/** Drop directories left behind when a whole album stops being published. */
function pruneEmptyDirs(dir) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (entry.isDirectory()) pruneEmptyDirs(path.join(dir, entry.name));
  }
  if (dir !== OUT_DIR && fs.readdirSync(dir).length === 0) fs.rmdirSync(dir);
}

// ─── Static server (Playwright needs real URLs for fonts and images) ─────────

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.css': 'text/css',
  '.js': 'text/javascript',
  '.json': 'application/json',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.webp': 'image/webp',
  '.woff2': 'font/woff2',
  '.ttf': 'font/ttf',
};

function serve(root) {
  const server = http.createServer((req, res) => {
    const rel = decodeURIComponent(new URL(req.url, 'http://x').pathname);
    const file = path.join(root, path.normalize(rel).replace(/^(\.\.[/\\])+/, ''));
    if (!file.startsWith(root) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) {
      res.writeHead(404).end('not found');
      return;
    }
    res.writeHead(200, { 'Content-Type': MIME[path.extname(file)] ?? 'application/octet-stream' });
    fs.createReadStream(file).pipe(res);
  });
  return new Promise((resolve) => {
    server.listen(0, '127.0.0.1', () => resolve({ server, port: server.address().port }));
  });
}

// ─── Main ────────────────────────────────────────────────────────────────────

if (!fs.existsSync(PUBLIC)) {
  console.error('public/ not found — run `hugo --minify` first.');
  process.exit(1);
}

const cards = findCards().sort((a, b) => a.key.localeCompare(b.key));
if (cards.length === 0) {
  console.error('No og.html files in public/ — is the ogcard output format configured?');
  process.exit(1);
}

// The fallback card for any page not yet in the manifest (a brand-new album
// added since the last `npm run og`) is rendered from the home page's own
// og.html — same formal-vs-photo logic, just saved under a second name.
cards.push({ key: DEFAULT_KEY, file: cards.find((c) => c.key === 'home').file });

const manifest = readManifest();
const hashes = Object.fromEntries(cards.map((c) => [c.key, cardHash(c.file)]));

const stale = cards.filter(
  ({ key }) => manifest[key] !== hashes[key] || !fs.existsSync(outFile(key)),
);
// Cards in the manifest whose page no longer exists.
const orphans = Object.keys(manifest).filter((key) => !(key in hashes));

if (checkOnly) {
  if (stale.length === 0 && orphans.length === 0) {
    console.log(`OG cards up to date (${cards.length} pages).`);
    process.exit(0);
  }
  for (const { key } of stale) console.error(`  stale or missing: ${key}`);
  for (const key of orphans) console.error(`  orphaned (page removed): ${key}`);
  console.error('\nRun `npm run og` and commit static/og/, static/og-default.jpg and data/og/manifest.json.');
  process.exit(1);
}

for (const key of orphans) {
  fs.rmSync(outFile(key), { force: true });
  delete manifest[key];
  console.log(`removed ${key}.jpg (page no longer exists)`);
}
if (orphans.length > 0) pruneEmptyDirs(OUT_DIR);

if (stale.length === 0) {
  writeManifest(manifest);
  console.log(`0 cards regenerated — all ${cards.length} are current.`);
  process.exit(0);
}

const { chromium } = await import('playwright');
const { server, port } = await serve(PUBLIC);
// Playwright's own Chromium by default. CHROMIUM_PATH points it at a system
// or preinstalled browser instead, for environments that can't download one.
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || undefined });
const page = await browser.newPage({
  viewport: { width: WIDTH, height: HEIGHT },
  deviceScaleFactor: 1,
});

try {
  for (const { key, file } of stale) {
    const cardKey = key === DEFAULT_KEY ? 'home' : key;
    const url = `http://127.0.0.1:${port}/${cardKey === 'home' ? '' : cardKey + '/'}og.html`;
    const response = await page.goto(url, { waitUntil: 'networkidle' });
    if (!response?.ok()) throw new Error(`${url} returned ${response?.status()}`);
    // Google Fonts is loaded with font-display:swap — without this the card
    // can screenshot mid-swap in the fallback face.
    await page.evaluate(() => document.fonts.ready);

    const dest = outFile(key);
    fs.mkdirSync(path.dirname(dest), { recursive: true });
    await page.screenshot({
      path: dest,
      type: 'jpeg',
      quality: QUALITY,
      clip: { x: 0, y: 0, width: WIDTH, height: HEIGHT },
    });
    manifest[key] = hashes[key];
    console.log(`rendered ${path.relative(ROOT, dest)}`);
  }
} finally {
  await browser.close();
  server.close();
}

writeManifest(manifest);
console.log(`\n${stale.length} card${stale.length === 1 ? '' : 's'} regenerated.`);
