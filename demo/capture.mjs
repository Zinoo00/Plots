// Screenshots and recordings of the Plots demo for the README (Playwright + Chromium; ffmpeg for mp4/gif).
//
//   cd demo && npm install            once (Playwright 1.61.1; `npx playwright install chromium` if it has no browser)
//   node capture.mjs                  every screenshot, light and dark, into docs/assets/
//   node capture.mjs --only overview,chat --dark
//   node capture.mjs --video live     the page while demo/play.py works (docs/assets/live.mp4 + .gif)
//   node capture.mjs --video chat     asking Chat a question and the answer coming in
//
// It re-seeds the demo first (so dates read "today"; --no-reset keeps it), starts it (demo/run.sh), stops it after
// (--keep leaves it running), and never touches your own Plots data: everything runs against demo/.home on port 4399.
import { chromium } from 'playwright';
import { spawn, spawnSync } from 'node:child_process';
import { mkdirSync, rmSync, readdirSync, renameSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const DEMO = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(DEMO, '..');
const PORT = process.env.PLOTS_PORT || '4399';
const BASE = `http://127.0.0.1:${PORT}/?ws=juniper`;
const ENV = { ...process.env, PLOTS_HOME: join(DEMO, '.home'), PLOTS_PORT: PORT, PLOTS_NO_FORKS: '1', PLOTS_DEMO_NO_OPEN: '1' };
delete ENV.PLOTS_WS;

const args = process.argv.slice(2);
const opt = (k, d) => { const i = args.indexOf(k); return i >= 0 ? args[i + 1] : d; };
const OUT = resolve(opt('--out', join(ROOT, 'docs', 'assets')));
const ONLY = opt('--only', '') ? opt('--only').split(',') : null;
const THEMES = args.includes('--light') ? ['light'] : args.includes('--dark') ? ['dark'] : ['light', 'dark'];
const VIDEO = opt('--video', null);
const SCALE = Number(opt('--scale', 2));
const DESKTOP = { width: 1440, height: 900 };

// name, route, what to do once the page is up
const SHOTS = [
  { name: 'overview', hash: '#/overview' },
  { name: 'screens', hash: '#/screens/jn0220' },
  { name: 'decisions', hash: '#/decisions/5' },
  { name: 'activity', hash: '#/activity' },
  { name: 'chat', hash: '#/overview', run: (p) => p.evaluate(() => Plots.chat('1')) },
  { name: 'search', hash: '#/screens', run: (p) => p.evaluate(() => Plots.palette('')) },
  { name: 'phone', hash: '#/overview', viewport: { width: 390, height: 844 }, scale: 3 },
];

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function sh(cmd, a) {
  const r = spawnSync(cmd, a, { env: ENV, cwd: ROOT, encoding: 'utf8' });
  if (r.status) throw new Error(`${cmd} ${a.join(' ')}: ${r.stderr || r.stdout}`);
  return r.stdout.trim();
}

async function ready(page) {
  await page.waitForFunction(() => window.Plots && document.querySelector('.card, .ov, .fld-ta'), null, { timeout: 15000 });
  await page.evaluate(() => document.fonts && document.fonts.ready);
  await sleep(900);                                   // charts and segmented thumbs settle
}

async function newPage(browser, theme, viewport = DESKTOP, scale = SCALE, video = null) {
  const ctx = await browser.newContext({
    viewport, deviceScaleFactor: scale, colorScheme: theme, reducedMotion: video ? 'no-preference' : 'reduce',
    ...(video ? { recordVideo: { dir: video, size: viewport } } : {}),
  });
  const page = await ctx.newPage();
  page.on('pageerror', (e) => console.error('page error:', e.message));
  return { ctx, page };
}

async function screenshots(browser) {
  for (const shot of SHOTS.filter((s) => !ONLY || ONLY.includes(s.name))) {
    for (const theme of THEMES) {
      const { ctx, page } = await newPage(browser, theme, shot.viewport, shot.scale);
      await page.goto(BASE + shot.hash);
      await ready(page);
      if (shot.run) { await shot.run(page); await sleep(900); }
      const file = join(OUT, `${shot.name}-${theme}.png`);
      await page.screenshot({ path: file });
      console.log('ok', file.replace(ROOT + '/', ''));
      await ctx.close();
    }
  }
}

function convert(webm, name) {
  const mp4 = join(OUT, `${name}.mp4`);
  const gif = join(OUT, `${name}.gif`);
  const ff = (a) => spawnSync('ffmpeg', ['-y', '-loglevel', 'error', ...a], { stdio: 'inherit' });
  if (spawnSync('ffmpeg', ['-version']).status !== 0) { console.log('ffmpeg not found: kept', webm); return; }
  ff(['-i', webm, '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-crf', '20', '-movflags', '+faststart', mp4]);
  ff(['-i', webm, '-vf', 'fps=10,scale=960:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=128:stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle', gif]);
  rmSync(webm, { force: true });
  console.log('ok', mp4.replace(ROOT + '/', ''), '·', gif.replace(ROOT + '/', ''));
}

async function record(browser, kind) {
  const theme = THEMES[0];
  const tmp = join(OUT, '.video');
  rmSync(tmp, { recursive: true, force: true });
  const { ctx, page } = await newPage(browser, theme, DESKTOP, 1, tmp);
  await page.goto(BASE + '#/overview');
  await ready(page);
  await sleep(1200);
  if (kind === 'live') {
    const play = spawn('python3', ['-I', join(DEMO, 'play.py'), '--gap', opt('--gap', '2.5')], { env: ENV, stdio: 'inherit' });
    await new Promise((r) => play.on('exit', r));
    await sleep(2500);
  } else if (kind === 'chat') {
    await page.evaluate(() => Plots.newChat());
    await sleep(900);
    await page.locator('#chat-msg').click();
    await page.keyboard.type("What's blocked right now?", { delay: 55 });
    await sleep(500);
    await page.keyboard.press('Enter');
    await page.waitForFunction(() => /blocked:/i.test(document.body.innerText), null, { timeout: 30000 });
    await sleep(2500);
  } else {
    throw new Error('--video takes live or chat');
  }
  await ctx.close();
  const webm = readdirSync(tmp).find((f) => f.endsWith('.webm'));
  renameSync(join(tmp, webm), join(OUT, `${kind}.webm`));
  rmSync(tmp, { recursive: true, force: true });
  convert(join(OUT, `${kind}.webm`), `${kind}-${theme}`);
}

mkdirSync(OUT, { recursive: true });
sh('sh', [join(DEMO, 'run.sh'), args.includes('--no-reset') ? 'start' : 'reset']);
await sleep(800);
const browser = await chromium.launch();
try {
  if (VIDEO) await record(browser, VIDEO);
  else await screenshots(browser);
} finally {
  await browser.close();
}
if (!args.includes('--keep')) sh('sh', [join(DEMO, 'run.sh'), 'stop']);
