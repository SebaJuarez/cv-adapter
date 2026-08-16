// Módulo común de grabación de demos.
// Stack: Puppeteer + ghost-cursor + puppeteer-screen-recorder (mp4 vía CDP).
// El cursor visible es un overlay SVG de flecha inyectado en la página que
// sigue los eventos de mouse reales que despacha ghost-cursor.

import puppeteer from "puppeteer";
import { GhostCursor } from "ghost-cursor";
import { PuppeteerScreenRecorder } from "puppeteer-screen-recorder";
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));

export const APP_URL = process.env.APP_URL || "http://127.0.0.1:8000";
export const VIDEOS_DIR = resolve(__dirname, "videos");
export const FFMPEG = resolve(
  __dirname,
  "node_modules/@ffmpeg-installer/win32-x64/ffmpeg.exe",
);

export const pause = (ms) => new Promise((r) => setTimeout(r, ms));

// Opciones de click "humanas" pero con pacing predecible para demo.
export const CLICK_OPTS = {
  moveDelay: 350,
  randomizeMoveDelay: false,
  hesitate: 250,
  waitForClick: 60,
};

// ------------------------------------------------------------------ cursor

// Overlay de flecha SVG que sigue al cursor real (los movimientos de
// ghost-cursor llegan como eventos de mouse reales del navegador).
export async function injectCursorOverlay(page) {
  await page.evaluateOnNewDocument(() => {
    const ARROW =
      '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" style="filter:drop-shadow(0 1px 2px rgba(0,0,0,.45))"><path d="M5.5 2.8 19.2 11.6 12.4 13 9.6 20.4z" fill="#ffffff" stroke="#1a1a1a" stroke-width="1.5" stroke-linejoin="round"/></svg>';
    function mount() {
      if (!document.body || window.__demoCursorMounted) return;
      window.__demoCursorMounted = true;
      const el = document.createElement("div");
      el.id = "__demo-cursor";
      el.style.cssText =
        "position:fixed;left:0;top:0;width:0;height:0;z-index:2147483647;pointer-events:none;will-change:transform;";
      const svg = document.createElement("div");
      svg.style.cssText =
        "position:absolute;transform:translate(-3px,-2px);transition:transform .05s linear;";
      svg.innerHTML = ARROW;
      el.appendChild(svg);
      document.body.appendChild(el);
      el.style.transform = "translate(300px, 200px)";
      document.addEventListener(
        "mousemove",
        (e) => {
          el.style.transform = `translate(${e.clientX}px, ${e.clientY}px)`;
        },
        true,
      );
      document.addEventListener(
        "mousedown",
        () => {
          svg.style.transform = "translate(-3px,-2px) scale(.82)";
        },
        true,
      );
      document.addEventListener(
        "mouseup",
        () => {
          svg.style.transform = "translate(-3px,-2px)";
        },
        true,
      );
    }
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", mount);
    } else {
      mount();
    }
  });
}

export async function newCursor(page) {
  await injectCursorOverlay(page);
  return new GhostCursor(page, { start: { x: 300, y: 200 }, visible: false });
}

// --------------------------------------------------------------- recorder

export async function startRecording(page, name) {
  mkdirSync(VIDEOS_DIR, { recursive: true });
  const outPath = resolve(VIDEOS_DIR, `${name}.mp4`);
  const recorder = new PuppeteerScreenRecorder(page, {
    fps: 15,
    ffmpeg_Path: FFMPEG,
    videoFrame: { width: 1280, height: 900 },
  });
  await recorder.start(outPath);
  const t0 = Date.now();
  const marks = [];
  const mark = (n) => marks.push({ name: n, t: (Date.now() - t0) / 1000 });
  const stop = async () => {
    await recorder.stop();
    writeFileSync(
      resolve(VIDEOS_DIR, `${name}.timeline.json`),
      JSON.stringify(marks, null, 2),
    );
  };
  return { mark, stop, outPath };
}

// ----------------------------------------------------------------- accion

// ghost-cursor (puppeteer 24) no puede scrollear: usa page._client(), que ya
// no existe, y su scrollIntoView es un no-op silencioso. Acá se scrollea el
// elemento con JS puro y recién entonces se mueve el cursor.
async function ensureInView(page, selector, smooth = false) {
  const offscreen = await page.evaluate((sel) => {
    const el = document.querySelector(sel);
    if (!el) return false;
    const r = el.getBoundingClientRect();
    return (
      r.bottom > window.innerHeight - 8 ||
      r.top < 8 ||
      r.right > window.innerWidth - 8 ||
      r.left < 8
    );
  }, selector);
  if (offscreen) {
    await page.evaluate(
      (sel, smooth) =>
        document
          .querySelector(sel)
          .scrollIntoView({ behavior: smooth ? "smooth" : "auto", block: "center" }),
      selector,
      smooth,
    );
    if (smooth) await pause(750);
  }
  return offscreen;
}

export async function clickSel(page, cursor, selector, opts = {}) {
  await page.waitForSelector(selector, {
    visible: true,
    timeout: opts.timeout ?? 30000,
  });
  await ensureInView(page, selector, true);
  await cursor.click(selector, { ...CLICK_OPTS, ...opts });
}

export async function clickText(page, cursor, text, scope = null, opts = {}) {
  const sel = scope ? `${scope} ::-p-text(${text})` : `::-p-text(${text})`;
  const handle = await page.waitForSelector(sel, {
    visible: true,
    timeout: opts.timeout ?? 30000,
  });
  await handle.evaluate((el) => el.setAttribute("data-demo-click", "1"));
  try {
    await ensureInView(page, '[data-demo-click="1"]', true);
    await cursor.click('[data-demo-click="1"]', CLICK_OPTS);
  } finally {
    await handle
      .evaluate((el) => el.removeAttribute("data-demo-click"))
      .catch(() => {});
  }
}

export async function scrollIntoView(page, cursor, selector, opts = {}) {
  await page.waitForSelector(selector, {
    visible: true,
    timeout: opts.timeout ?? 30000,
  });
  await page.evaluate(
    (sel) =>
      document
        .querySelector(sel)
        .scrollIntoView({ behavior: "smooth", block: "center" }),
    selector,
  );
  await pause(opts.afterScroll ?? 900);
  const pos = await page.evaluate((sel) => {
    const el = document.querySelector(sel);
    const b = el.getBoundingClientRect();
    return { x: b.x + b.width / 2, y: b.y + b.height / 2 };
  }, selector);
  await cursor.moveTo({ x: pos.x, y: pos.y });
  await pause(300);
}

// Hover prolongado (para tooltips/scores): scrollea a la vista, mueve el
// cursor real y queda parado sobre el elemento un rato.
export async function hoverSel(page, cursor, selector, opts = {}) {
  await scrollIntoView(page, cursor, selector, opts);
  await pause(opts.afterHover ?? 1500);
}

export async function typeIn(page, cursor, selector, text, delay = 8) {
  await clickSel(page, cursor, selector);
  await page.keyboard.down("Control");
  await page.keyboard.press("a");
  await page.keyboard.up("Control");
  await page.keyboard.type(text, { delay });
}

export async function openTab(page, cursor, view) {
  await clickSel(page, cursor, `button.tab[data-view="${view}"]`);
  await pause(600);
  // Verificación: si la vista no quedó activa (p.ej. scroll suave en curso
  // o un modal que interceptó el click), reintentar con click JS puro.
  const active = await page.evaluate(
    (v) => document.getElementById(`view-${v}`)?.classList.contains("is-active"),
    view,
  );
  if (!active) {
    await page.evaluate(
      (v) => document.querySelector(`button.tab[data-view="${v}"]`)?.click(),
      view,
    );
    await pause(800);
  }
}

export async function waitToast(page, text, timeout = 15000) {
  await page.waitForSelector(`#toasts .toast ::-p-text(${text})`, {
    visible: true,
    timeout,
  });
}

// ------------------------------------------------------------------ util

export async function launch(browserOpts = {}) {
  return puppeteer.launch({
    headless: true,
    defaultViewport: { width: 1280, height: 900 },
    protocolTimeout: 600000,
    ...browserOpts,
  });
}

export async function gotoApp(page) {
  await page.goto(APP_URL, { waitUntil: "domcontentloaded", timeout: 30000 });
}
