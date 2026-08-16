// Demo: imports — subir 3 CVs → bandeja de clusters con diff → confirmar.
// Uso: node record-imports.mjs

import { readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
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

const FILES = [
  resolve("work/cvs/cv1.txt"),
  resolve("work/cvs/cv2.txt"),
  resolve("work/cvs/cv3.txt"),
];

const browser = await launch();
const page = await browser.newPage();
const cursor = await newCursor(page);
const consoleMsgs = [];
page.on("console", (m) => consoleMsgs.push(`${m.type()}: ${m.text()}`));
page.on("pageerror", (e) => consoleMsgs.push(`pageerror: ${e.message}`));
await gotoApp(page);
const { mark, stop } = await startRecording(page, "imports");

await openTab(page, cursor, "imports");
await pause(600);

// 1. Subir los 3 CVs (input file; la lista de archivos aparece en la UI)
await scrollIntoView(page, cursor, 'input[aria-label="Archivos de CV para importar"]', { afterScroll: 500 });
const fileInput = await page.$('input[aria-label="Archivos de CV para importar"]');
await fileInput.uploadFile(...FILES);
await pause(1200);
await scrollIntoView(page, cursor, ".imports-upload", { afterScroll: 600 });

// 2. Agrupar (embeddings; ya pre-calentados antes de grabar)
await clickText(page, cursor, "Importar y agrupar");
await page.waitForSelector(".imp-cluster", { visible: true, timeout: 120000 });
await pause(800);

// 3. Recorrer la bandeja: clusters con el diff resaltado
await scrollIntoView(page, cursor, ".imp-cluster", { afterScroll: 800 });
await pause(1800);
const clusters = await page.$$(".imp-cluster");
if (clusters.length > 1) {
  await page.evaluate(() => {
    document.querySelectorAll(".imp-cluster")[1].scrollIntoView({ behavior: "smooth", block: "center" });
  });
  await pause(1600);
}
if (clusters.length > 2) {
  await page.evaluate(() => {
    document.querySelectorAll(".imp-cluster")[2].scrollIntoView({ behavior: "smooth", block: "center" });
  });
  await pause(1600);
}

// 4. Resolver el cluster del logro destacado ("cacheo distribuido con
//    Redis"): el LLM genera el logro candidato (redacciones del grupo
//    como variantes). Confirmar ese cluster fija el logro que luego usa
//    record-variant-gen (mismo tema en su JD).
await page.evaluate(() => {
  const cards = [...document.querySelectorAll(".imp-cluster")];
  const i = cards.findIndex((c) => c.textContent.includes("cacheo distribuido"));
  (cards[Math.max(0, i)] || cards[0]).scrollIntoView({ behavior: "smooth", block: "center" });
});
await pause(1000);
await page.evaluate(() => {
  const cards = [...document.querySelectorAll(".imp-cluster")];
  const i = cards.findIndex((c) => c.textContent.includes("cacheo distribuido"));
  (cards[Math.max(0, i)] || cards[0]).setAttribute("data-demo-merge", "1");
});
mark("gen_click");
try {
  await clickText(page, cursor, "Es el mismo logro", '.imp-cluster[data-demo-merge="1"]');
} finally {
  await page
    .evaluate(() => document.querySelectorAll(".imp-cluster").forEach((c) => c.removeAttribute("data-demo-merge")))
    .catch(() => {});
}
console.log("[imports] generando candidato con el LLM...");
await page.waitForSelector(".imp-candidates", { visible: true, timeout: 300000 });
mark("gen_result");
await pause(800);

// 5. Candidatos: el logro propuesto (facts + variantes) → confirmar
await scrollIntoView(page, cursor, ".imp-candidates", { afterScroll: 800 });
await pause(1500);
await scrollIntoView(page, cursor, ".imp-candidates .ach-card", { afterScroll: 800 });
await pause(1200);
await clickText(page, cursor, "Confirmar", ".imp-candidate-actions", { timeout: 15000 });
await waitToast(page, "logro");
await pause(1200);

// 6. Cierre: el logro llegó al CV maestro
await openTab(page, cursor, "master");
await page.waitForSelector(".ach-card", { visible: true, timeout: 30000 });
await hoverSel(page, cursor, ".ach-card", { afterScroll: 900, afterHover: 1800 });

await stop();
await browser.close();
console.log("ok imports");
writeFileSync(resolve("work/imports-console.json"), JSON.stringify(consoleMsgs, null, 2));
