// Demo GIF: editor de logros — hechos vs variantes, ángulos, "usada en N
// CVs", enriquecer un bullet legacy y guardar el master.
//
// Requiere logros en el master demo (grabar tras record-imports).
// Uso: node record-achievements.mjs

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
  waitToast,
} from "./record.mjs";

const browser = await launch();
const page = await browser.newPage();
const cursor = await newCursor(page);
const { mark, stop } = await startRecording(page, "achievements");

try {
  await gotoApp(page);
  await page.waitForSelector('button.tab[data-view="master"]', { visible: true });
  await openTab(page, cursor, "master");
  await pause(700);

  // 1. Expandir todo para ver las entradas con sus bullets
  await clickSel(page, cursor, "#expand-all-master");
  await pause(900);

  // 2. Enriquecer el primer bullet de la primera entrada (Acme Corp):
  //    pasa toda la entrada a formato logro, con hechos extraídos
  await scrollIntoView(page, cursor, 'button[aria-label="Enriquecer este bullet"]', { afterScroll: 700 });
  await pause(600);
  await clickSel(page, cursor, 'button[aria-label="Enriquecer este bullet"]');
  await waitToast(page, "formato logro");
  await pause(1000);

  // 3. El logro enriquecido: hechos (acción, herramientas, alcance, resultados)
  await scrollIntoView(page, cursor, ".ach-card", { afterScroll: 700 });
  await pause(1800);
  await hoverSel(page, cursor, ".ach-facts textarea", { afterScroll: 500, afterHover: 1200 });

  // 4. Variantes: ángulo y estado, y el badge de uso
  await scrollIntoView(page, cursor, ".ach-variant", { afterScroll: 700 });
  await pause(1400);
  await hoverSel(page, cursor, ".ach-variant .ach-used", { afterScroll: 500, afterHover: 1400 });

  // 5. Interacción real: cambiar el ángulo de la variante a "liderazgo"
  //    (select nativo: select() dispara el evento change)
  await clickSel(page, cursor, '.ach-variant select[aria-label="Ángulo"]');
  await page.select('.ach-variant select[aria-label="Ángulo"]', "liderazgo");
  await pause(900);

  // 5b. Editar la redacción (evento input → badge "● sin guardar" y botones
  //     Previsualizar / Guardar / Descartar en .ach-actions)
  await scrollIntoView(page, cursor, ".ach-variant textarea", { afterScroll: 600 });
  await pause(500);
  await page.evaluate(() => {
    const ta = document.querySelector(".ach-variant textarea");
    ta.focus();
    ta.setSelectionRange(ta.value.length, ta.value.length);
  });
  await page.keyboard.type(" (nuevo enfoque)", { delay: 40 });
  await pause(900);

  // 6. Guardar el logro (aparece el botón Guardar con el draft sucio)
  await scrollIntoView(page, cursor, ".ach-actions .btn-primary", { afterScroll: 600 });
  await pause(500);
  await clickSel(page, cursor, ".ach-actions .btn-primary");
  await waitToast(page, "Logro guardado");
  await pause(1000);

  // 7. El logro importado (última entrada de experiencia): facts + variantes
  await page.evaluate(() => {
    const cards = document.querySelectorAll(".ach-card");
    if (cards.length) {
      cards[cards.length - 1].setAttribute("data-last-ach", "1");
      cards[cards.length - 1].scrollIntoView({ behavior: "smooth", block: "center" });
    }
  });
  await pause(1200);
  await hoverSel(page, cursor, "[data-last-ach='1']", { afterScroll: 300, afterHover: 2000 });
  await scrollIntoView(page, cursor, "[data-last-ach='1'] .ach-variant", { afterScroll: 500 });
  await pause(1600);

  // 8. Guardar el master (persiste el used_count de las corridas previas)
  await scrollIntoView(page, cursor, "#save-master", { afterScroll: 600 });
  await pause(500);
  mark("save_click");
  await clickSel(page, cursor, "#save-master");
  await waitToast(page, "CV maestro guardado");
  await pause(1200);

  await stop();
} catch (err) {
  console.error("[achievements] ERROR:", err);
  await stop().catch(() => {});
  process.exitCode = 1;
} finally {
  await browser.close();
}
