// Demo GIF: hero del README — flujo panorámico: pegar oferta (JD frontend,
// distinto al de apply), generar, revisar selección y descargar PDF.
//
// Uso: node record-hero.mjs

import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import {
  clickSel,
  gotoApp,
  hoverSel,
  launch,
  newCursor,
  openTab,
  pause,
  scrollIntoView,
  startRecording,
  typeIn,
} from "./record.mjs";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../..");

const browser = await launch();
const page = await browser.newPage();
const cursor = await newCursor(page);
const { mark, stop } = await startRecording(page, "hero");

try {
  await gotoApp(page);
  await page.waitForSelector('button.tab[data-view="apply"]', { visible: true });
  await openTab(page, cursor, "apply");
  await pause(700);

  // 1. Pegar la oferta (frontend — distinta a la del GIF de apply)
  const jd = readFileSync(resolve("work/jd_frontend.txt"), "utf8");
  await typeIn(page, cursor, "#job-description", jd, 6);
  await page.waitForSelector("#preview-keywords .preview-chip", {
    visible: true,
    timeout: 20000,
  });
  await hoverSel(page, cursor, "#preview-keywords .preview-chip", {
    afterScroll: 600,
    afterHover: 900,
  });

  // 2. Generar
  mark("gen_click");
  await clickSel(page, cursor, "#generate-btn");
  console.log("[hero] generando... (LLM, puede tardar)");
  await page.waitForSelector("#apply-result", {
    visible: true,
    timeout: 600000,
  });
  mark("gen_result");
  await pause(500);

  // 3. Recorrido panorámico (sin detenerse tanto como en apply)
  await scrollIntoView(page, cursor, "#result-summary", { afterScroll: 600 });
  await pause(1300);
  await scrollIntoView(page, cursor, "#keyword-report", { afterScroll: 600 });
  await pause(1200);
  await hoverSel(page, cursor, ".bullet-score", {
    afterScroll: 800,
    afterHover: 1800,
  });
  await page.waitForSelector("#jd-tooltip", { visible: true, timeout: 8000 }).catch(() => {});
  await pause(800);

  // 4. Renderizar y descargar
  await scrollIntoView(page, cursor, "#render-btn");
  await pause(600);
  mark("render_click");
  await clickSel(page, cursor, "#render-btn");
  console.log("[hero] renderizando PDF...");
  await page.waitForFunction(
    () => {
      const b = document.getElementById("render-btn");
      return b && b.textContent.trim() === "Descargar PDF";
    },
    { timeout: 300000 },
  );
  mark("render_done");
  await pause(2600);
  await stop();
} catch (err) {
  console.error("[hero] ERROR:", err);
  await stop().catch(() => {});
  process.exitCode = 1;
} finally {
  await browser.close();
}
