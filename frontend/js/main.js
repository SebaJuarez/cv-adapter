//módulo: main — bootstrap: tabs, init, listeners globales y encabezado original

import { $, h } from "./dom.js";
import { loadMasterView } from "./views/master.js";
import { confirmAction } from "./modals.js";
import { setGlobalStatus } from "./notify.js";
import { loadSettingsView } from "./views/settings.js";
import { loadHistoryView } from "./views/history.js";
import { loadImportsView } from "./views/imports.js";
import { dirty, hasUnsavedChanges, state, updateUndoButton } from "./state.js";

"use strict";

/* =====================================================================
   cv-adapter — frontend v2.2
   Features:
   - Relevancia por bullet (score 0-100 con mini barra)
   - Heatmap de entrada (borde colorido según score promedio)
   - JD snippet en hover (tooltip flotante con el fragmento de oferta)
   - Oportunidades críticas (keywords de alta frecuencia missing)
   - Delta de fit al agregar bullets
   - Pullback ordenado por relevancia
   - Resumen del resultado + keyword report unificado (incluye manuales)
   - Contenido no incluido agrupado, toasts, progreso, dirty state,
     filtro/colapso en master, undo multi-nivel por vista (P2.1)
   ===================================================================== */

// --------------------------------------------------- altura de la topbar

function syncTopbarHeight() {
  const tb = document.querySelector(".topbar");
  if (tb) document.documentElement.style.setProperty("--topbar-h", tb.offsetHeight + "px");
}
window.addEventListener("resize", syncTopbarHeight);

// ------------------------------------------------------------- tabs/init

function viewNameFor(id) {
  return id === "view-master" ? "master"
    : id === "view-apply" ? "apply"
    : id === "view-imports" ? "imports"
    : id === "view-history" ? "history"
    : "settings";
}

async function switchView(btn) {
  const currentView = document.querySelector(".view.is-active");
  const viewName = viewNameFor(currentView.id);
  if (hasUnsavedChanges(viewName) && !btn.classList.contains("is-active")) {
    const ok = await confirmAction({
      title: "Cambios sin guardar",
      message: "Tenés cambios sin guardar en esta vista. ¿Salir igual?",
      confirmLabel: "Salir igual",
      cancelLabel: "Quedarme",
    });
    if (!ok) return;
  } else {
    // Sin cambios reales: limpiar el flag por si quedó sucio (p.ej. undo).
    dirty[viewName] = false;
  }
  document.querySelectorAll(".tab").forEach((t) => {
    const active = t === btn;
    t.classList.toggle("is-active", active);
    t.setAttribute("aria-selected", String(active));
  });
  document.querySelectorAll(".view").forEach((v) => {
    v.classList.toggle("is-active", v.id === "view-" + btn.dataset.view);
  });
  updateUndoButton();
  const heading = document.querySelector(".view.is-active .view-head h1");
  if (heading) heading.focus({ preventScroll: true });
}

$("#tabs").addEventListener("click", (e) => {
  const btn = e.target.closest(".tab");
  if (!btn) return;
  switchView(btn);
});

$("#tabs").addEventListener("keydown", (e) => {
  if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
  const tabs = [...document.querySelectorAll(".tab")];
  const idx = tabs.indexOf(document.activeElement);
  if (idx === -1) return;
  const dir = e.key === "ArrowRight" ? 1 : -1;
  const next = tabs[(idx + dir + tabs.length) % tabs.length];
  next.focus();
  switchView(next);
});

(async function init() {
  syncTopbarHeight();
  const [master, settings, history, imports] = await Promise.allSettled([
    loadMasterView(), loadSettingsView(), loadHistoryView(), loadImportsView(),
  ]);
  const failures = [master, settings, history, imports].filter((x) => x.status === "rejected");
  if (failures.length > 0) {
    const detail = failures.map((f) => f.reason && f.reason.message ? f.reason.message : String(f.reason)).join(" | ");
    setGlobalStatus("No se pudo cargar toda la app: " + detail, "error");
    console.error(detail);
  }
})();

export { switchView, syncTopbarHeight, viewNameFor };
