//módulo: master — vista master: carga, filtro, guardado

import { api } from "../api.js";
import { commitAllDrafts, renderHeader, renderSectionNav, renderSections } from "../components.js";
import { $ } from "../dom.js";
import { blankEntryFor, deriveSectionTypes } from "../labels.js";
import { promptAddSection } from "../modals.js";
import { setGlobalStatus, setStatus, toast } from "../notify.js";
import { markDirty, snapshotView, state } from "../state.js";
import { mountOnboarding } from "./onboarding.js";

// --------------------------------------------------------- vista: master

// F4: el master está vacío cuando no hay nombre y ninguna sección tiene
// entradas — es la señal de "usuario nuevo sin CV" que dispara el
// onboarding conversacional.
function isMasterEmpty(doc) {
  const cv = doc?.cv;
  if (!cv) return true;
  if ((cv.name || "").trim()) return false;
  return Object.values(cv.sections || {}).every(
    (entries) => !Array.isArray(entries) || entries.length === 0
  );
}

const EDITOR_PANES = [
  "#master-header",
  "#master-nav",
  ".master-tools",
  "#add-section-master",
  "#view-master .save-bar",
];

function setEditorPanesVisible(visible) {
  EDITOR_PANES.forEach((sel) => {
    const el = $(sel);
    if (el) el.hidden = !visible;
  });
}

async function loadMasterView() {
  state.masterDoc = await api("/api/master-cv");
  state.masterSectionTypes = deriveSectionTypes(state.masterDoc);
  snapshotView("master");
  if (isMasterEmpty(state.masterDoc) && !localStorage.getItem("onboardingSeen")) {
    setEditorPanesVisible(false);
    drawOnboarding();
  } else {
    drawMasterView();
  }
}

function drawOnboarding() {
  const container = $("#master-sections");
  container.innerHTML = "";
  mountOnboarding(container, () => {
    localStorage.setItem("onboardingSeen", "1");
    setEditorPanesVisible(true);
    drawMasterView();
  });
}

function drawMasterView() {
  renderHeader($("#master-header"), state.masterDoc, () => markDirty("master"));
  renderSectionNav($("#master-nav"), $("#master-sections"), state.masterDoc.cv.sections);
  const ctx = {
    doc: state.masterDoc,
    isTarget: false,
    sectionTypes: state.masterSectionTypes,
    onRerender: () => { markDirty("master"); drawMasterView(); },
  };
  renderSections($("#master-sections"), ctx);
  applyMasterFilter();
}

function applyMasterFilter() {
  const sections = $("#master-sections");
  const count = $("#master-filter-count");
  if (!sections || !count) return;
  const q = (state.masterFilter || "").trim().toLowerCase();

  const allCards = [...sections.querySelectorAll(".entry-card")];
  const allTextRows = [...sections.querySelectorAll(".highlight-row")]
    .filter((r) => !r.closest(".entry-card"));

  let visible = 0;
  const total = allCards.length + allTextRows.length;

  allTextRows.forEach((row) => {
    const v = !q || row.textContent.toLowerCase().includes(q);
    row.classList.toggle("filtered-out", !v);
    if (v) visible++;
  });

  allCards.forEach((card) => {
    const bullets = [...card.querySelectorAll(".highlight-row, .ach-card")];
    let anyBullet = false;
    bullets.forEach((b) => {
      const bv = !q || b.textContent.toLowerCase().includes(q);
      b.classList.toggle("filtered-out", !bv);
      if (bv) anyBullet = true;
    });
    const fieldsText = (card.querySelector(".entry-fields")?.textContent || "").toLowerCase();
    const cardVisible = !q || fieldsText.includes(q) || anyBullet;
    card.classList.toggle("filtered-out", !cardVisible);
    if (cardVisible) visible++;
  });

  sections.querySelectorAll(".section-block").forEach((block) => {
    const children = [...block.querySelectorAll(".entry-card, .highlight-row")];
    const blockVisible = children.some((el) => !el.classList.contains("filtered-out"));
    block.classList.toggle("filtered-out", q !== "" && !blockVisible);
  });

  if (q === "") {
    count.hidden = true;
    count.textContent = "";
    count.classList.remove("no-results");
    return;
  }
  count.hidden = false;
  count.textContent = visible === 0 ? "sin resultados" : `${visible} de ${total} visibles`;
  count.classList.toggle("no-results", visible === 0);
}

$("#master-filter").addEventListener("input", (e) => {
  state.masterFilter = e.target.value;
  applyMasterFilter();
});

$("#collapse-all-master").addEventListener("click", () => {
  state.collapsedMaster = {};
  Object.keys(state.masterDoc.cv.sections || {}).forEach((n) => { state.collapsedMaster[n] = true; });
  drawMasterView();
});

$("#expand-all-master").addEventListener("click", () => {
  state.collapsedMaster = {};
  drawMasterView();
});

$("#add-section-master").addEventListener("click", async () => {
  const result = await promptAddSection();
  if (!result) return;
  if (state.masterDoc.cv.sections[result.name]) {
    setStatus($("#master-status"), "Ya existe una sección con ese nombre.", "error");
    return;
  }
  state.masterDoc.cv.sections[result.name] = result.type === "entries" ? [blankEntryFor(result.name, "entries")] : [];
  state.masterSectionTypes[result.name] = result.type;
  markDirty("master");
  drawMasterView();
});

$("#save-master").addEventListener("click", async () => {
  const statusEl = $("#master-status");
  setStatus(statusEl, "Guardando…");
  const btn = $("#save-master");
  btn.disabled = true;
  try {
    commitAllDrafts();
    await api("/api/master-cv", { method: "POST", body: JSON.stringify(state.masterDoc) });
    snapshotView("master");
    setStatus(statusEl, "Guardado.", "ok");
    toast("CV maestro guardado.");
  } catch (e) {
    setStatus(statusEl, e.message, "error");
    setGlobalStatus("No se pudo guardar el CV maestro: " + e.message, "error");
  } finally {
    btn.disabled = false;
  }
});


export { applyMasterFilter, drawMasterView, loadMasterView };
