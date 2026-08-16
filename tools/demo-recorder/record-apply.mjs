// Demo GIF: "Nueva aplicación" — pegar oferta, keyword report completo,
// scores por bullet con tooltip de JD, contenido excluido, traer bullet
// manual y renderizar PDF.
//
// Uso: node record-apply.mjs

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
const { mark, stop } = await startRecording(page, "apply");

try {
  await gotoApp(page);
  await page.waitForSelector('button.tab[data-view="apply"]', { visible: true });
  await openTab(page, cursor, "apply");
  await pause(700);

  // 1. Pegar la oferta (JD backend de ejemplo) + preview de keywords en vivo
  const jd = readFileSync(
    resolve(ROOT, "data/job_description_example.txt"),
    "utf8",
  );
  await typeIn(page, cursor, "#job-description", jd, 6);
  await page.waitForSelector("#preview-keywords .preview-chip", {
    visible: true,
    timeout: 20000,
  });
  await hoverSel(page, cursor, "#preview-keywords .preview-chip", {
    afterScroll: 600,
    afterHover: 1000,
  });

  // 2. Generar (el corte por timeline saca la espera del LLM del GIF)
  mark("gen_click");
  await clickSel(page, cursor, "#generate-btn");
  console.log("[apply] generando... (LLM, puede tardar)");
  await page.waitForSelector("#apply-result", {
    visible: true,
    timeout: 600000,
  });
  mark("gen_result");
  await pause(500);

  // 3. Resumen: ATS score + cobertura
  await scrollIntoView(page, cursor, "#result-summary", { afterScroll: 600 });
  await pause(1600);

  // 4. Keyword report completo
  await scrollIntoView(page, cursor, "#keyword-report", { afterScroll: 700 });
  await pause(1600);

  // 5. Scores por bullet + tooltip de JD al hacer hover (2 bullets)
  await hoverSel(page, cursor, ".bullet-score", {
    afterScroll: 800,
    afterHover: 2200,
  });
  await page.waitForSelector("#jd-tooltip", {
    visible: true,
    timeout: 8000,
  }).catch(() => {});
  await pause(1200);
  await hoverSel(page, cursor, "#target-sections .entry-card:nth-child(2) .bullet-score", {
    afterScroll: 800,
    afterHover: 2200,
  });

  // 6. Panel "Contenido no incluido": oportunidades críticas + excluidos
  await scrollIntoView(page, cursor, "#notincluded-panel", { afterScroll: 700 });
  await pause(600);
  await clickSel(page, cursor, "#notincluded-panel summary");
  await page.waitForSelector("#opportunities-panel:not([hidden]), #excluded-panel:not([hidden])", {
    visible: true,
    timeout: 10000,
  });
  await pause(800);
  await scrollIntoView(page, cursor, "#opportunities-panel", { afterScroll: 700 }).catch(() => {});
  await pause(1200);
  await scrollIntoView(page, cursor, "#excluded-content", { afterScroll: 700 }).catch(() => {});
  await pause(1200);

  // 7. Traer un bullet excluido manualmente (interacción real)
  await clickSel(page, cursor, "details.pullback summary");
  await page.waitForSelector('button[aria-label="Agregar este bullet"]', {
    visible: true,
    timeout: 10000,
  });
  await pause(600);
  await clickSel(page, cursor, 'button[aria-label="Agregar este bullet"]');
  await page.waitForSelector("#toasts .toast", { visible: true, timeout: 8000 }).catch(() => {});
  await pause(1600);

  // 8. Renderizar PDF
  await scrollIntoView(page, cursor, "#render-btn");
  await pause(600);
  mark("render_click");
  await clickSel(page, cursor, "#render-btn");
  console.log("[apply] renderizando PDF...");
  await page.waitForFunction(
    () => {
      const b = document.getElementById("render-btn");
      return b && b.textContent.trim() === "Descargar PDF";
    },
    { timeout: 300000 },
  );
  mark("render_done");
  await pause(2400);
  await stop();
} catch (err) {
  console.error("[apply] ERROR:", err);
  await stop().catch(() => {});
  process.exitCode = 1;
} finally {
  await browser.close();
}
