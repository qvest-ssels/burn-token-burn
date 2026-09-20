/*
 * Rendering test for the docs site (docs/*.html).
 *
 * This is NOT part of the Python package's test suite (token-finops-cli/tests/).
 * It only checks that the static site in this directory renders: that every page
 * loads without console/network errors, that the asciinema player on each page
 * actually initialises and draws a terminal (rather than leaving a blank div),
 * and that the player is constrained to roughly 60 % of the viewport — the
 * `width: min(60vw, 720px)` rule in style.css — instead of running full-bleed.
 *
 * How to run it (Chromium only — the site is checked against the engine most
 * readers use, and asciinema-player's canvas sizing differs between engines):
 *
 *   # one-off setup. Everything lands in ./tmp/ — repo-local and gitignored,
 *   # per AGENTS.md: nothing is written outside the repository tree, and no
 *   # dependency of this script is committed.
 *   mkdir -p tmp/node-test && echo '{"private":true}' > tmp/node-test/package.json
 *   export NPM_CONFIG_CACHE="$(pwd)/tmp/npm-cache"
 *   export PLAYWRIGHT_BROWSERS_PATH="$(pwd)/tmp/playwright-browsers"
 *   npm install --prefix tmp/node-test playwright
 *   (cd tmp/node-test && ./node_modules/.bin/playwright install chromium)
 *
 *   # terminal 1 — serve the site
 *   python3 -m http.server 8899 --directory docs
 *
 *   # terminal 2 — run the checks
 *   export PLAYWRIGHT_BROWSERS_PATH="$(pwd)/tmp/playwright-browsers"
 *   PLAYWRIGHT_MODULE="$(pwd)/tmp/node-test/node_modules/playwright/index.mjs" \
 *     node docs/test-pages.mjs
 *
 * PLAYWRIGHT_MODULE just tells the script where playwright lives; drop it if
 * you have it installed somewhere node resolves on its own. Override the base
 * URL with BASE_URL=http://127.0.0.1:1234 if you serve the site elsewhere.
 *
 * Exits 0 when every check passes, 1 otherwise, and prints one line per check.
 */

const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || "playwright");

const BASE_URL = process.env.BASE_URL || "http://127.0.0.1:8899";

// A normal desktop window. 1440 wide means min(60vw, 720px) resolves to the
// 720px arm, so both halves of the rule get exercised together with the
// narrow-viewport case below.
const DESKTOP = { width: 1440, height: 900 };
const NARROW = { width: 800, height: 900 };

// `players` lists every asciinema container on the page; it may be empty for a
// pure-prose page, which still gets the HTTP/nav/console checks below.
const PAGES = [
  { path: "index.html", players: ["player-06", "player-07"] },
  { path: "report.html", players: ["player-01"] },
  { path: "statusline.html", players: ["player-02"] },
  { path: "self-audit.html", players: ["player-03"] },
  { path: "savings.html", players: ["player-04", "player-08"] },
  { path: "co2-research.html", players: ["player-08"] },
  { path: "synth.html", players: ["player-05"] },
  { path: "reference.html", players: [] },
];

// Every link in the shared nav bar, in order. Checked against each page so the
// nav cannot drift between pages.
const NAV_LINKS = PAGES.map((p) => p.path);

let failures = 0;

function check(name, ok, detail) {
  const status = ok ? "ok  " : "FAIL";
  console.log(`${status}  ${name}${detail ? "  — " + detail : ""}`);
  if (!ok) failures += 1;
}

async function openPage(context, path) {
  const page = await context.newPage();
  const problems = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") problems.push(`console: ${msg.text()}`);
  });
  page.on("pageerror", (err) => problems.push(`pageerror: ${err.message}`));
  page.on("requestfailed", (req) =>
    problems.push(`request failed: ${req.url()}`)
  );
  page.on("response", (res) => {
    if (res.status() >= 400) problems.push(`HTTP ${res.status()}: ${res.url()}`);
  });

  const response = await page.goto(`${BASE_URL}/${path}`, {
    waitUntil: "networkidle",
  });
  return { page, problems, response };
}

async function run() {
  const browser = await chromium.launch();

  // ---- desktop viewport: rendering, nav, and player sizing ---------------
  const desktop = await browser.newContext({ viewport: DESKTOP });

  for (const spec of PAGES) {
    const { page, problems, response } = await openPage(desktop, spec.path);

    check(`${spec.path}: HTTP 200`, response && response.status() === 200,
      response ? `got ${response.status()}` : "no response");

    for (const playerId of spec.players) {
      // The player is created by docs/player.js from the container's data-cast
      // attribute. asciinema-player replaces the container's contents with its
      // own DOM (.ap-player > .ap-term > canvas), so finding that tree is the
      // signal that init succeeded rather than leaving an empty div behind.
      const wrapper = page.locator(`#${playerId}`);
      await wrapper.waitFor({ state: "visible", timeout: 10000 });

      let initialised = false;
      try {
        // The theme class comes from the shared options in docs/player.js, so
        // this also proves the page picked those options up.
        await page
          .locator(`#${playerId} .ap-player.asciinema-player-theme-asciinema .ap-term canvas`)
          .first()
          .waitFor({ state: "attached", timeout: 15000 });
        initialised = true;
      } catch {
        initialised = false;
      }
      check(`${spec.path}: player ${playerId} initialised`, initialised);

      const box = await wrapper.boundingBox();
      check(`${spec.path}/${playerId}: player has a non-zero box`,
        !!box && box.width > 100 && box.height > 50,
        box ? `${Math.round(box.width)}x${Math.round(box.height)}` : "no box");

      // Not blank: play the recording for a moment, then read the terminal
      // canvas back. A player that failed to load its cast stays a single flat
      // colour; a working one has painted text by now.
      const painted = await page.evaluate(async (id) => {
        const root = document.getElementById(id);
        const btn = root.querySelector(".ap-play-button, .ap-playback-button");
        if (btn) btn.click();
        await new Promise((r) => setTimeout(r, 3000));
        const canvas = root.querySelector(".ap-term canvas");
        if (!canvas || !canvas.width || !canvas.height) return { colours: 0 };
        const ctx = canvas.getContext("2d");
        const data = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
        const seen = new Set();
        for (let i = 0; i < data.length; i += 4) {
          seen.add((data[i] << 16) | (data[i + 1] << 8) | data[i + 2]);
          if (seen.size > 4) break;
        }
        return { colours: seen.size, w: canvas.width, h: canvas.height };
      }, playerId);
      check(`${spec.path}/${playerId}: painted terminal content (not blank)`,
        painted.colours > 1,
        `${painted.colours} distinct colours on a ${painted.w}x${painted.h} canvas`);

      // Sizing: min(60vw, 720px) at 1440px wide => 720px, and definitely not
      // the full 1440px / full content column.
      const expected = Math.min(0.6 * DESKTOP.width, 720);
      const widthOk = !!box && Math.abs(box.width - expected) <= 2;
      check(`${spec.path}/${playerId}: player width is min(60vw, 720px)`, widthOk,
        box ? `${Math.round(box.width)}px, expected ${expected}px` : "no box");

      const notFullBleed = !!box && box.width < DESKTOP.width * 0.75;
      check(`${spec.path}/${playerId}: player is not full-bleed`, notFullBleed,
        box ? `${Math.round((box.width / DESKTOP.width) * 100)}% of viewport` : "no box");

      // Left-aligned with the prose, not centred: the player's left edge lines
      // up with the surrounding text column. The tolerance covers the .featured
      // panel's padding on the home page.
      const offsets = await page.evaluate((id) => {
        const el = document.getElementById(id);
        const prose = document.querySelector(".wrap h1, .wrap header h1");
        if (!el || !prose) return null;
        return {
          player: el.getBoundingClientRect().left,
          prose: prose.getBoundingClientRect().left,
        };
      }, playerId);
      check(`${spec.path}/${playerId}: player is left-aligned with the prose`,
        !!offsets && Math.abs(offsets.player - offsets.prose) <= 40,
        offsets ? `player ${Math.round(offsets.player)}px vs prose ${Math.round(offsets.prose)}px` : "not found");

    }

    // Navigation: the shared nav bar, exactly one link marked as the current
    // page, and it points at this page.
    const nav = await page.evaluate(() => {
      const links = Array.from(document.querySelectorAll(".topbar nav a"));
      return {
        count: links.length,
        current: links
          .filter((a) => a.getAttribute("aria-current") === "page")
          .map((a) => a.getAttribute("href")),
        hrefs: links.map((a) => a.getAttribute("href")),
      };
    });
    check(`${spec.path}: nav has ${NAV_LINKS.length} links`,
      nav.count === NAV_LINKS.length, `got ${nav.count}`);
    check(`${spec.path}: nav links match the shared set`,
      JSON.stringify(nav.hrefs) === JSON.stringify(NAV_LINKS),
      JSON.stringify(nav.hrefs));
    check(`${spec.path}: nav marks this page as current`,
      nav.current.length === 1 && nav.current[0] === spec.path,
      JSON.stringify(nav.current));

    check(`${spec.path}: no console/network errors`, problems.length === 0,
      problems.join(" | "));

    await page.close();
  }

  // ---- nav actually navigates -------------------------------------------
  {
    const { page } = await openPage(desktop, "index.html");
    await page.click('.topbar nav a[href="savings.html"]');
    await page.waitForURL(/savings\.html$/);
    const current = await page.getAttribute(
      '.topbar nav a[aria-current="page"]',
      "href"
    );
    check("nav: clicking 'savings' lands on savings.html", current === "savings.html",
      String(current));
    await page.close();
  }

  // ---- narrow viewport: the media query hands back the full width --------
  {
    const narrow = await browser.newContext({ viewport: NARROW });
    const { page } = await openPage(narrow, "report.html");
    const box = await page.locator("#player-01").boundingBox();
    const wrapWidth = await page.evaluate(
      () => document.querySelector(".wrap").getBoundingClientRect().width
        - parseFloat(getComputedStyle(document.querySelector(".wrap")).paddingLeft)
        - parseFloat(getComputedStyle(document.querySelector(".wrap")).paddingRight)
    );
    check("report.html @800px: player falls back to full column width",
      !!box && Math.abs(box.width - wrapWidth) <= 2,
      box ? `${Math.round(box.width)}px vs column ${Math.round(wrapWidth)}px` : "no box");
    await page.close();
    await narrow.close();
  }

  await desktop.close();
  await browser.close();

  console.log("");
  if (failures) {
    console.log(`${failures} check(s) failed`);
    process.exit(1);
  }
  console.log("all checks passed");
}

run().catch((err) => {
  console.error(err);
  process.exit(1);
});
