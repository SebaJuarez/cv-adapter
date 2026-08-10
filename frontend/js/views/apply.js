//módulo: apply — vista apply: generación, target, render

import { api } from "../api.js";
import { renderHeader, renderSectionNav, renderSections } from "../components.js";
import { $ } from "../dom.js";
import { blankEntryFor, deriveSectionTypes } from "../labels.js";
import { confirmAction, promptAddSection } from "../modals.js";
import { hideProgress, setGlobalStatus, setStatus, showProgress, toast } from "../notify.js";
import { markDirty, snapshotView, state } from "../state.js";
import { refreshKeywordWidgets, renderPageEstimate, keywordPresentIn } from "../widgets.js";

// ---------------------------------------------------------- vista: apply

// La oferta es un contenteditable (P2.3, habilita <mark>): el texto se lee
// como innerText, no .value.
function jdText() {
  const jd = $("#job-description");
  return jd ? jd.innerText : "";
}

$("#generate-btn").addEventListener("click", async () => {
  const statusEl = $("#generate-status");
  const jd = jdText();
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
  // "Forzar regeneración" (P0.1): saltea el cache de selección en el backend.
  const force = $("#force-regenerate").checked;

  const btn = $("#generate-btn");
  btn.disabled = true;
  showProgress("#generate-progress");
  setGlobalStatus("");
  setStatus(statusEl, "Consultando al modelo de IA (local o remoto)…");
  try {
    const result = await api("/api/generate", {
      method: "POST",
      body: JSON.stringify({ job_description: jd, manual_keywords: manualKeywords, force }),
    });
    state.targetDoc = { cv: result.target_cv.cv, design: result.target_cv.design };
    state.targetSectionTypes = deriveSectionTypes(state.targetDoc);
    state.selection = result.selection;
    state.masterDocSnapshot = result.master_cv;
    state.keywordReport = result.keyword_report;
    state.pageEstimate = result.page_estimate;
    state.currentRunId = result.run_id;
    snapshotView("apply");
    setStatus(statusEl, "Listo. Revisá la selección abajo.", "ok");
    setRenderButton("generate");
    $("#apply-result").hidden = false;
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
  renderPageEstimate();

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

// ------------------------------------------- preview en vivo de keywords (P1.2)

// Solo extract_keywords en el backend (sin modelos ni LLM): debounce de 400ms
// y abort de la petición anterior si el texto siguió cambiando.
const PREVIEW_MIN_CHARS = 40;
const PREVIEW_DEBOUNCE_MS = 400;

let previewTimer = null;
let previewAbort = null;

function renderPreviewChips(payload) {
  const el = $("#preview-keywords");
  if (!el) return;
  const kws = payload.keywords_detected || [];
  if (!kws.length) {
    el.hidden = true;
    el.innerHTML = "";
    return;
  }
  const hint = document.createElement("span");
  hint.className = "preview-hint";
  hint.textContent = "Keywords detectadas en la oferta:";
  const chips = kws.map((kw) => {
    const chip = document.createElement("span");
    chip.className = "preview-chip" + (payload.in_master[kw] ? " in-master" : " not-in-master");
    chip.textContent = kw;
    chip.title = payload.in_master[kw]
      ? "Ya está en tu CV maestro"
      : "No está en tu CV maestro";
    return chip;
  });
  el.innerHTML = "";
  el.append(hint, ...chips);
  el.hidden = false;
}

async function fetchKeywordPreview() {
  const jd = jdText().trim();
  const el = $("#preview-keywords");
  if (jd.length < PREVIEW_MIN_CHARS) {
    el.hidden = true;
    el.innerHTML = "";
    return;
  }
  if (previewAbort) previewAbort.abort();
  previewAbort = new AbortController();
  el.hidden = false;
  el.innerHTML = '<span class="preview-hint">Detectando keywords…</span>';
  try {
    const payload = await api("/api/preview-keywords", {
      method: "POST",
      signal: previewAbort.signal,
      body: JSON.stringify({ job_description: jd }),
    });
    renderPreviewChips(payload);
  } catch (e) {
    if (e.name === "AbortError") return;
    el.hidden = true; // preview es opcional: falla silencioso
  }
}

$("#job-description").addEventListener("input", () => {
  clearJdMarks();
  clearTimeout(previewTimer);
  previewTimer = setTimeout(fetchKeywordPreview, PREVIEW_DEBOUNCE_MS);
});

// ------------------------------------- resaltado bidireccional JD ↔ bullet (P2.3)

// Pegado como texto plano: el contenteditable no debe traer HTML.
$("#job-description").addEventListener("paste", (e) => {
  e.preventDefault();
  const text = (e.clipboardData || window.clipboardData).getData("text/plain");
  document.execCommand("insertText", false, text);
});

function clearJdMarks() {
  const jd = $("#job-description");
  if (!jd) return;
  jd.querySelectorAll("mark.jd-mark").forEach((m) => {
    m.replaceWith(document.createTextNode(m.textContent));
  });
}

// Marca en el JD cada término (variante sinónima) con límites de palabra,
// fusionando rangos solapados y sin marcar dentro de otro <mark>.
function highlightJdTerms(terms) {
  const jd = $("#job-description");
  if (!jd) return;
  clearJdMarks();
  if (!terms.length) return;
  const patterns = terms.filter(Boolean).map((t) => {
    const esc = t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    return new RegExp(`(^|[^a-z0-9])(${esc})([^a-z0-9]|$)`, "gi");
  });
  const walk = (node) => {
    if (node.nodeType === Node.TEXT_NODE) {
      markTextNode(node, patterns);
    } else if (node.nodeType === Node.ELEMENT_NODE) {
      if (node.classList && node.classList.contains("jd-mark")) return;
      [...node.childNodes].forEach(walk);
    }
  };
  [...jd.childNodes].forEach(walk);
}

function markTextNode(node, patterns) {
  const text = node.textContent;
  const lower = text.toLowerCase();
  const ranges = [];
  for (const re of patterns) {
    let m;
    while ((m = re.exec(lower)) !== null) {
      const start = m.index + m[1].length;
      ranges.push([start, start + m[2].length]);
    }
  }
  if (!ranges.length) return;
  ranges.sort((a, b) => a[0] - b[0]);
  const merged = [];
  for (const [s, e] of ranges) {
    const last = merged[merged.length - 1];
    if (last && s <= last[1]) last[1] = Math.max(last[1], e);
    else merged.push([s, e]);
  }
  const frag = document.createDocumentFragment();
  let pos = 0;
  for (const [s, e] of merged) {
    if (s > pos) frag.appendChild(document.createTextNode(text.slice(pos, s)));
    const mark = document.createElement("mark");
    mark.className = "jd-mark";
    mark.title = "Mostrar los bullets de tu CV que matchean esta palabra";
    mark.textContent = text.slice(s, e);
    frag.appendChild(mark);
    pos = e;
  }
  if (pos < text.length) frag.appendChild(document.createTextNode(text.slice(pos)));
  node.parentNode.replaceChild(frag, node);
}

// Click en un bullet del target → marca en el JD los términos que matchea.
$("#target-sections").addEventListener("click", (e) => {
  const ta = e.target.closest("textarea.highlight-text");
  if (!ta || !state.keywordReport) return;
  const terms = [];
  const variants = state.keywordReport.keyword_variants || {};
  const bulletCorpus = ta.value.toLowerCase();
  for (const kw of state.keywordReport.all_keywords || []) {
    if (!keywordPresentIn(bulletCorpus, kw, variants)) continue;
    const vs = variants[kw] || [String(kw).toLowerCase()];
    vs.forEach((v) => { if (!terms.includes(v)) terms.push(v); });
  }
  highlightJdTerms(terms);
});

// Click en un <mark> del JD → flash de los bullets que matchean la palabra.
$("#job-description").addEventListener("click", (e) => {
  const mark = e.target.closest("mark.jd-mark");
  if (!mark) return;
  const variants = (state.keywordReport && state.keywordReport.keyword_variants) || {};
  let flashed = 0;
  document.querySelectorAll("#target-sections textarea.highlight-text").forEach((ta) => {
    if (!keywordPresentIn(ta.value.toLowerCase(), mark.textContent, variants)) return;
    const row = ta.closest(".highlight-row");
    if (!row) return;
    row.classList.remove("bullet-flash");
    void row.offsetWidth; // reiniciar la animación
    row.classList.add("bullet-flash");
    flashed++;
  });
  if (flashed > 0) {
    const sec = $("#target-sections");
    if (sec) sec.scrollIntoView({ behavior: "smooth", block: "start" });
  }
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

let renderBtnMode = "generate";
let downloadUrl = "";

function setRenderButton(mode) {
  renderBtnMode = mode;
  const btn = $("#render-btn");
  if (btn) btn.textContent = mode === "download" ? "Descargar PDF" : "Generar PDF";
}

async function triggerRender() {
  const statusEl = $("#render-status");
  const btn = $("#render-btn");

  showProgress("#render-progress");
  setStatus(statusEl, "Compilando PDF…");
  btn.disabled = true;
  try {
    await api("/api/render", {
      method: "POST",
      body: JSON.stringify({ ...state.targetDoc, run_id: state.currentRunId }),
    });
    downloadUrl = "/api/download-pdf?t=" + Date.now();
    setStatus(statusEl, "PDF listo.", "ok");
    setRenderButton("download");
    toast("PDF listo para descargar.");
  } catch (e) {
    setStatus(statusEl, e.message, "error");
    setGlobalStatus("Error al generar PDF: " + e.message, "error");
  } finally {
    btn.disabled = false;
    hideProgress("#render-progress");
  }
}

$("#render-btn").addEventListener("click", () => {
  if (renderBtnMode === "download") {
    window.location.href = downloadUrl;
    return;
  }
  triggerRender();
});

document.addEventListener("cv:apply-dirty", () => setRenderButton("generate"));


export { drawTargetView, triggerRender };
