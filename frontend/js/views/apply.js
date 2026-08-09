//módulo: apply — vista apply: generación, target, render

import { api } from "../api.js";
import { renderHeader, renderSectionNav, renderSections } from "../components.js";
import { $ } from "../dom.js";
import { blankEntryFor, deriveSectionTypes } from "../labels.js";
import { confirmAction, promptAddSection } from "../modals.js";
import { hideProgress, setGlobalStatus, setStatus, showProgress, toast } from "../notify.js";
import { dirty, markDirty, state } from "../state.js";
import { refreshKeywordWidgets } from "../widgets.js";

// ---------------------------------------------------------- vista: apply

$("#generate-btn").addEventListener("click", async () => {
  const statusEl = $("#generate-status");
  const jd = $("#job-description").value;
  if (!jd.trim()) { setStatus(statusEl, "Pegá la oferta laboral primero.", "error"); return; }
  if (jd.trim().length < 40) {
    const proceed = await confirmAction({
      title: "Oferta laboral corta",
      message: "La oferta parece muy corta. Con poco texto el modelo puede traer contenido genérico. ¿Generar igual?",
      confirmLabel: "Generar igual",
    });
    if (!proceed) return;
  }

  const manualKeywords = ($("#ats-keywords").value || "").split(",").map((s) => s.trim()).filter(Boolean);

  const btn = $("#generate-btn");
  btn.disabled = true;
  showProgress("#generate-progress");
  setGlobalStatus("");
  setStatus(statusEl, "Consultando al modelo de IA (local o remoto)…");
  try {
    const result = await api("/api/generate", {
      method: "POST",
      body: JSON.stringify({ job_description: jd, manual_keywords: manualKeywords }),
    });
    state.targetDoc = { cv: result.target_cv.cv, design: result.target_cv.design };
    state.targetSectionTypes = deriveSectionTypes(state.targetDoc);
    state.selection = result.selection;
    state.masterDocSnapshot = result.master_cv;
    state.keywordReport = result.keyword_report;
    dirty.apply = false;
    setStatus(statusEl, "Listo. Revisá la selección abajo.", "ok");
    $("#apply-result").hidden = false;
    $("#download-link").hidden = true;
    $("#download-link-summary").hidden = true;
    drawTargetView();
    $("#apply-result").scrollIntoView({ behavior: "smooth", block: "start" });
    toast("CV generado. Revisá la selección.");
  } catch (e) {
    setStatus(statusEl, e.message, "error");
    setGlobalStatus("No se pudo generar el CV: " + e.message, "error");
  } finally {
    btn.disabled = false;
    hideProgress("#generate-progress");
  }
});

function drawTargetView() {
  renderHeader($("#target-header"), state.targetDoc, () => markDirty("apply"));

  refreshKeywordWidgets();

  const ctx = {
    doc: state.targetDoc,
    isTarget: true,
    sectionTypes: state.targetSectionTypes,
    masterDoc: state.masterDocSnapshot,
    selection: state.selection,
    onRerender: () => { markDirty("apply"); drawTargetView(); },
  };
  renderSectionNav($("#target-nav"), $("#target-sections"), state.targetDoc.cv.sections);
  renderSections($("#target-sections"), ctx);
}

$("#ats-keywords").addEventListener("input", () => {
  if (state.targetDoc && state.keywordReport) refreshKeywordWidgets();
});

$("#add-section-target").addEventListener("click", async () => {
  const result = await promptAddSection();
  if (!result) return;
  if (state.targetDoc.cv.sections[result.name]) {
    setStatus($("#render-status"), "Ya existe una sección con ese nombre.", "error");
    return;
  }
  state.targetDoc.cv.sections[result.name] = result.type === "entries" ? [blankEntryFor(result.name, "entries")] : [];
  state.targetSectionTypes[result.name] = result.type;
  markDirty("apply");
  drawTargetView();
});

async function triggerRender() {
  const statusEl = $("#render-status");
  const statusSummary = $("#render-status-summary");
  const btn = $("#render-btn");
  const btnSummary = $("#render-btn-summary");
  const links = [$("#download-link"), $("#download-link-summary")];

  showProgress("#render-progress");
  setStatus(statusEl, "Compilando PDF…");
  setStatus(statusSummary, "Compilando PDF…");
  links.forEach((l) => { if (l) l.hidden = true; });
  btn.disabled = true;
  if (btnSummary) btnSummary.disabled = true;
  try {
    await api("/api/render", { method: "POST", body: JSON.stringify(state.targetDoc) });
    const url = "/api/download-pdf?t=" + Date.now();
    setStatus(statusEl, "PDF listo.", "ok");
    setStatus(statusSummary, "PDF listo.", "ok");
    links.forEach((l) => { if (l) { l.href = url; l.hidden = false; } });
    toast("PDF listo para descargar.");
  } catch (e) {
    setStatus(statusEl, e.message, "error");
    setStatus(statusSummary, e.message, "error");
    setGlobalStatus("Error al generar PDF: " + e.message, "error");
  } finally {
    btn.disabled = false;
    if (btnSummary) btnSummary.disabled = false;
    hideProgress("#render-progress");
  }
}

$("#render-btn").addEventListener("click", triggerRender);
$("#render-btn-summary").addEventListener("click", triggerRender);


export { drawTargetView, triggerRender };
