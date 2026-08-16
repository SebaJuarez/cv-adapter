// Demo GIF: historial — variantes más usadas, keywords faltantes, filtros,
// estado de aplicación, comparar dos corridas y detalle "Análisis".
//
// Requiere 2+ corridas (grabar tras apply + hero).
// Uso: node record-history.mjs

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

const rowsCount = (page) =>
  page.evaluate(() => document.querySelectorAll("#history-list tbody tr").length);

const browser = await launch();
const page = await browser.newPage();
const cursor = await newCursor(page);
const { mark, stop } = await startRecording(page, "history");

try {
  await gotoApp(page);
  await page.waitForSelector('button.tab[data-view="history"]', { visible: true });
  await openTab(page, cursor, "history");
  await pause(700);

  // 1. "Tus variantes más usadas"
  await scrollIntoView(page, cursor, "#history-variant-stats", { afterScroll: 700 });
  await pause(1600);
  await page.waitForSelector("#history-variant-stats .history-empty, #history-variant-stats *", { visible: true, timeout: 15000 }).catch(() => {});
  await hoverSel(page, cursor, "#history-variant-stats", { afterScroll: 400, afterHover: 1500 });

  // 2. "Keywords que faltan en el CV maestro"
  await scrollIntoView(page, cursor, "#history-stats", { afterScroll: 700 });
  await pause(1400);
  await hoverSel(page, cursor, "#history-stats", { afterScroll: 400, afterHover: 1200 });

  // 3. Búsqueda por oferta (filtra server-side)
  await scrollIntoView(page, cursor, "#history-search", { afterScroll: 600 });
  await pause(400);
  await typeIn(page, cursor, "#history-search", "frontend");
  await pause(1200);
  const nFrontend = await rowsCount(page);
  console.log(`[history] filas con 'frontend': ${nFrontend}`);
  await pause(1000);
  await clickSel(page, cursor, "#history-search");
  await page.keyboard.down("Control");
  await page.keyboard.press("a");
  await page.keyboard.up("Control");
  await page.keyboard.press("Backspace");
  await pause(1200);
  const nAll = await rowsCount(page);
  console.log(`[history] filas totales: ${nAll}`);

  // 4. Estado de la aplicación: marcar la primera corrida como "aplicado"
  //    (select nativo: select() dispara el evento change)
  await scrollIntoView(page, cursor, 'select[aria-label="Estado de la aplicación"]', { afterScroll: 700 });
  await pause(600);
  await clickSel(page, cursor, 'select[aria-label="Estado de la aplicación"]');
  await page.select('select[aria-label="Estado de la aplicación"]', "aplicado");
  await page.waitForSelector("#toasts .toast", { visible: true, timeout: 8000 }).catch(() => {});
  await pause(1400);

  // 5. Chips de estado: Aplicado → Todas
  await scrollIntoView(page, cursor, "#history-status-chips", { afterScroll: 600 });
  await pause(500);
  await clickText(page, cursor, "Aplicado", "#history-status-chips");
  await pause(1000);
  const nAplicado = await rowsCount(page);
  console.log(`[history] filas 'Aplicado': ${nAplicado}`);
  await pause(900);
  await clickText(page, cursor, "Todas", "#history-status-chips");
  await pause(1000);

  // 6. Comparar dos corridas (el modal se abre solo con el 2º check)
  await scrollIntoView(page, cursor, "#history-list", { afterScroll: 700 });
  await pause(700);
  await page.evaluate(() => {
    const checks = document.querySelectorAll(".history-compare-check");
    if (checks[0]) {
      checks[0].setAttribute("data-cmp", "1");
      checks[0].scrollIntoView({ behavior: "smooth", block: "center" });
    }
  });
  await pause(800);
  await clickSel(page, cursor, "[data-cmp='1']");
  await pause(900);
  await page.evaluate(() => {
    const checks = document.querySelectorAll(".history-compare-check");
    if (checks[1]) {
      checks[1].setAttribute("data-cmp2", "1");
      checks[1].scrollIntoView({ behavior: "smooth", block: "center" });
    }
  });
  await pause(800);
  await clickSel(page, cursor, "[data-cmp2='1']");
  await page.waitForSelector("#modal-overlay .compare-block", { visible: true, timeout: 10000 });
  await pause(1500);
  await hoverSel(page, cursor, "#modal-overlay .compare-block", { afterScroll: 400, afterHover: 1500 });
  await clickText(page, cursor, "Cerrar", "#modal-overlay");
  await pause(900);

  // 7. Detalle de corrida: tab Análisis + variantes usadas
  await page.evaluate(() => {
    const btn = [...document.querySelectorAll("#history-list button")].find(
      (b) => b.textContent.trim() === "Ver",
    );
    if (btn) {
      btn.setAttribute("data-ver", "1");
      btn.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  });
  await pause(800);
  await clickSel(page, cursor, "[data-ver='1']");
  await page.waitForSelector("#modal-overlay .detail-tabs", { visible: true, timeout: 10000 });
  await pause(800);
  await clickText(page, cursor, "Análisis", ".detail-tabs");
  await pause(800);
  await scrollIntoView(page, cursor, "#modal-overlay .detail-score", { afterScroll: 600 });
  await pause(1400);
  await scrollIntoView(page, cursor, "#modal-overlay .detail-h4", { afterScroll: 600 });
  await pause(1600);
  await clickText(page, cursor, "Cerrar", "#modal-overlay");
  await pause(1000);

  await stop();
} catch (err) {
  console.error("[history] ERROR:", err);
  await stop().catch(() => {});
  process.exitCode = 1;
} finally {
  await browser.close();
}
