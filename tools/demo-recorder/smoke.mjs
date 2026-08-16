// Smoke test del stack: lanza, inyecta el cursor, hace un movimiento de
// ghost-cursor sobre el tab "Historial", graba 3s y saca un screenshot.
// Uso: node smoke.mjs

import {
  clickSel,
  gotoApp,
  launch,
  newCursor,
  pause,
  startRecording,
} from "./record.mjs";

const browser = await launch();
const page = await browser.newPage();
const cursor = await newCursor(page);
const { stop } = await startRecording(page, "smoke");

try {
  await gotoApp(page);
  await page.waitForSelector('button.tab[data-view="history"]', {
    visible: true,
  });
  await clickSel(page, cursor, 'button.tab[data-view="history"]');
  await pause(1500);
  const info = await page.evaluate(() => {
    const el = document.getElementById("__demo-cursor");
    const active = document.querySelector("button.tab.is-active");
    return {
      overlay: !!el,
      transform: el ? el.style.transform : null,
      activeTab: active ? active.textContent.trim() : null,
    };
  });
  console.log("[smoke] overlay:", info.overlay, "| transform:", info.transform, "| tab:", info.activeTab);
  if (!info.overlay || !info.transform || info.activeTab !== "Historial") {
    throw new Error("overlay o click fallaron: " + JSON.stringify(info));
  }
  await page.screenshot({ path: "work/smoke.png" });
  console.log("[smoke] OK: cursor movido y click sobre Historial");
} catch (err) {
  console.error("[smoke] ERROR:", err);
  process.exitCode = 1;
} finally {
  await stop().catch(() => {});
  await browser.close();
}
