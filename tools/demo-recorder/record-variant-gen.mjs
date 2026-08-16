// Demo GIF: generación asistida de variante — botón ✏ en un bullet con
// logro → modal de comparación lado a lado (términos no verificados
// resaltados) → "Usar y guardar como variante nueva" → popover ⇄ con la
// variante nueva.
//
// Requiere que el master demo tenga logros (grabar tras record-imports).
// Uso: node record-variant-gen.mjs

import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import {
  clickSel,
  clickText,
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
const { mark, stop } = await startRecording(page, "variant-gen");

try {
  await gotoApp(page);
  await page.waitForSelector('button.tab[data-view="apply"]', { visible: true });
  await openTab(page, cursor, "apply");
  await pause(700);

  // 1. Generar el target con un JD alineado al logro importado (cacheo
  //    distribuido con Redis): ese bullet debe ganar un slot del target
  //    para que exista el botón ✏ (los temas de los CVs importados no
  //    duplican los highlights del master de ejemplo).
  const jd = readFileSync(resolve("work/jd_variantgen.txt"), "utf8");
  await typeIn(page, cursor, "#job-description", jd, 6);
  await page.waitForSelector("#preview-keywords .preview-chip", {
    visible: true,
    timeout: 20000,
  });
  await pause(600);
  mark("gen_click");
  await clickSel(page, cursor, "#generate-btn");
  console.log("[variant-gen] generando target...");
  await page.waitForSelector("#apply-result", {
    visible: true,
    timeout: 600000,
  });
  await pause(500);

  // 2. Bullet con logro → botón de generación (aparece SIEMPRE en logros)
  await scrollIntoView(page, cursor, "button.ach-gen", { afterScroll: 800 });
  await pause(800);
  await hoverSel(page, cursor, "button.ach-gen", { afterHover: 1400 });

  mark("gen_click");
  await clickSel(page, cursor, "button.ach-gen");
  console.log("[variant-gen] generando variante con el LLM...");

  // 3. Modal de comparación lado a lado (espera del LLM; el corte la saca)
  await page.waitForSelector("#modal-overlay .vc-text", {
    visible: true,
    timeout: 600000,
  });
  mark("gen_result");
  await pause(1000);
  await scrollIntoView(page, cursor, "#modal-overlay .modal-box", { afterScroll: 600 });
  await pause(1800);

  // Términos no verificables resaltados (si el modelo devolvió alguno)
  const hasChips = await page
    .waitForSelector("#modal-overlay .vc-chip-warn", { visible: true, timeout: 3000 })
    .then(() => true)
    .catch(() => false);
  if (hasChips) {
    await hoverSel(page, cursor, "#modal-overlay .vc-chip-warn", {
      afterScroll: 500,
      afterHover: 1600,
    });
  }

  // 4. "Usar y guardar como variante nueva" → toast
  await clickText(page, cursor, "Usar y guardar como variante nueva");
  await page.waitForSelector("#toasts .toast", { visible: true, timeout: 8000 }).catch(() => {});
  await pause(1600);

  // 5. Cierre: el popover ⇄ muestra la variante nueva
  await scrollIntoView(page, cursor, "button.ach-switch", { afterScroll: 800 });
  await pause(600);
  await clickSel(page, cursor, "button.ach-switch");
  await page.waitForSelector(".ach-switch-popover", { visible: true, timeout: 8000 });
  await pause(2000);
  await hoverSel(page, cursor, ".ach-switch-option", { afterScroll: 400, afterHover: 1600 });
  await pause(400);

  await stop();
} catch (err) {
  console.error("[variant-gen] ERROR:", err);
  await stop().catch(() => {});
  process.exitCode = 1;
} finally {
  await browser.close();
}
