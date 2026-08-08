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
     filtro/colapso en master, undo del último borrado
   ===================================================================== */

const state = {
  masterDoc: null,
  targetDoc: null,
  selection: null,
  config: null,
  masterDocSnapshot: null,
  masterSectionTypes: {},
  targetSectionTypes: {},
  keywordReport: null,
  masterFilter: "",
  collapsedMaster: {},
  lastUndo: null,
};

const dirty = { master: false, apply: false, settings: false };

// ---------------------------------------------------------------- utils

function $(sel, root = document) { return root.querySelector(sel); }

function h(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k.startsWith("on") && typeof v === "function") node.addEventListener(k.slice(2), v);
    else if (v !== null && v !== undefined) node.setAttribute(k, v);
  }
  for (const child of [].concat(children)) {
    if (child === null || child === undefined) continue;
    node.appendChild(typeof child === "string" ? document.createTextNode(child) : child);
  }
  return node;
}

function autoResize(textarea) {
  textarea.style.height = "auto";
  textarea.style.height = textarea.scrollHeight + "px";
}

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const isJson = (res.headers.get("content-type") || "").includes("application/json");
  const body = isJson ? await res.json() : null;
  if (!res.ok) {
    const detail = body && body.detail ? body.detail : res.statusText;
    const message = Array.isArray(detail) ? detail.join("\n") : String(detail);
    throw new Error(message);
  }
  return body;
}

function setStatus(el, message, kind) {
  el.textContent = message || "";
  el.className = "status" + (kind ? " " + kind : "");
}

function setGlobalStatus(message, kind) {
  const el = $("#global-status");
  if (!el) return;
  el.textContent = message || "";
  el.className = "global-status" + (kind ? " global-" + kind : "");
  el.hidden = !message;
}

// ---------------------------------------------------------------- toasts

function toast(message, kind) {
  const container = $("#toasts");
  if (!container) return;
  const el = h("div", { class: "toast" + (kind ? " toast-" + kind : "") }, message);
  container.appendChild(el);
  setTimeout(() => {
    el.classList.add("toast-out");
    setTimeout(() => el.remove(), 320);
  }, 4000);
}

// ---------------------------------------------------------------- progreso

function showProgress(id) { const el = $(id); if (el) el.hidden = false; }
function hideProgress(id) { const el = $(id); if (el) el.hidden = true; }

// -------------------------------------------------------- dirty state

function markDirty(view) {
  dirty[view] = true;
  const el = view === "master" ? $("#master-status")
    : view === "apply" ? $("#render-status")
    : $("#settings-status");
  if (el) setStatus(el, "Hay cambios sin guardar.", "dirty");
}

document.addEventListener("input", (e) => {
  if (e.target && e.target.id === "master-filter") return;
  const activeView = document.querySelector(".view.is-active");
  if (!activeView) return;
  if (activeView.id === "view-master") markDirty("master");
  else if (activeView.id === "view-apply") markDirty("apply");
  else if (activeView.id === "view-settings") markDirty("settings");
}, true);

// ---------------------------------------------------------------- undo

function rememberUndo(label, restore) {
  state.lastUndo = { label, restore };
  const btn = $("#undo-btn");
  if (btn) {
    btn.hidden = false;
    btn.title = "Deshacer: " + label;
  }
}

function undoLast() {
  if (!state.lastUndo) return;
  const undo = state.lastUndo;
  state.lastUndo = null;
  const btn = $("#undo-btn");
  if (btn) btn.hidden = true;
  undo.restore();
  toast("Se deshizo: " + undo.label + ".");
}

$("#undo-btn").addEventListener("click", undoLast);

// ------------------------------------------------------ labels de campos

const FIELD_LABELS = {
  company: "Empresa", position: "Puesto", location: "Ubicación",
  start_date: "Fecha inicio", end_date: "Fecha fin",
  institution: "Institución", area: "Área", degree: "Título",
  name: "Nombre", date: "Fecha", label: "Categoría", details: "Detalle",
};

function fieldLabel(key) {
  return FIELD_LABELS[key] || key.replace(/_/g, " ");
}

// --------------------------------------------------- altura de la topbar

function syncTopbarHeight() {
  const tb = document.querySelector(".topbar");
  if (tb) document.documentElement.style.setProperty("--topbar-h", tb.offsetHeight + "px");
}
window.addEventListener("resize", syncTopbarHeight);

// -------------------------------------------------------- tooltip JD

function showJDSnippet(text, el) {
  const tooltip = $("#jd-tooltip");
  if (!tooltip || !text) return;
  tooltip.textContent = text;
  tooltip.hidden = false;
  const rect = el.getBoundingClientRect();
  tooltip.style.left = (rect.left + window.scrollX) + "px";
  tooltip.style.top = (rect.bottom + window.scrollY + 6) + "px";
}

function hideJDSnippet() {
  const tooltip = $("#jd-tooltip");
  if (tooltip) tooltip.hidden = true;
}

// -------------------------------------------------------- corpus de texto

function buildDocCorpus(doc) {
  if (!doc) return "";
  const parts = [];
  const walk = (v) => {
    if (typeof v === "string") parts.push(v);
    else if (Array.isArray(v)) v.forEach(walk);
    else if (v && typeof v === "object") {
      Object.entries(v).forEach(([k, val]) => { if (!k.startsWith("_")) walk(val); });
    }
  };
  walk((doc.cv && doc.cv.sections) || {});
  return parts.join(" \n ").toLowerCase();
}

// -------------------------------------------------------- keywords manuales

function getManualKeywords() {
  const raw = ($("#ats-keywords") && $("#ats-keywords").value) || "";
  return raw.split(",").map((s) => s.trim()).filter(Boolean);
}

function effectiveKeywordList() {
  const base = (state.keywordReport && state.keywordReport.all_keywords) || [];
  const manual = getManualKeywords();
  const out = base.slice();
  manual.forEach((kw) => {
    if (!out.some((k) => String(k).toLowerCase() === kw.toLowerCase())) out.push(kw);
  });
  return out;
}

// ----------------------------------------------------- keyword report

function renderResultSummary() {
  const panel = $("#result-summary");
  const value = $("#result-score-value");
  const statsCovered = $("#result-stats-covered");
  const statsCritical = $("#result-stats-critical");
  if (!panel || !value || !statsCovered || !statsCritical) return;
  if (!state.keywordReport) {
    panel.hidden = true;
    return;
  }
  const all = effectiveKeywordList();
  if (all.length === 0) {
    panel.hidden = true;
    return;
  }
  const pct = state.keywordReport.ats_impact_score || 0;

  panel.hidden = false;
  value.textContent = pct + "%";
  value.className = "result-score-value" + (pct >= 80 ? " good" : pct >= 50 ? " mid" : " bad");
  const covered = Object.values(state.keywordReport.in_target || {}).filter(Boolean).length;
  statsCovered.textContent = `${covered} de ${all.length} keywords cubiertas`;
  const critical = state.keywordReport.critical_missing || [];
  statsCritical.hidden = critical.length === 0;
  statsCritical.textContent = ` · ${critical.length} faltantes críticas`;
}

function renderKeywordReport() {
  const container = $("#keyword-report");
  if (!container) return;
  container.innerHTML = "";

  if (!state.keywordReport) return;
  const { frequencies, in_master, in_target } = state.keywordReport;
  const masterCorpus = buildDocCorpus(state.masterDocSnapshot);
  const targetCorpus = buildDocCorpus(state.targetDoc);
  const all = effectiveKeywordList();
  if (all.length === 0) return;

  const wrap = h("div", { class: "kw-report" });

  const legend = h("div", { class: "kw-legend" }, [
    h("span", { class: "kw-legend-item" }, [h("span", { class: "kw-dot kw-dot-ok" }), " en el CV"]),
    h("span", { class: "kw-legend-item" }, [h("span", { class: "kw-dot kw-dot-missing" }), " en master, no en target"]),
    h("span", { class: "kw-legend-item" }, [h("span", { class: "kw-dot kw-dot-notmaster" }), " no está en master"]),
  ]);
  wrap.appendChild(legend);

  const missingInTarget = [];
  const notInMaster = [];

  const list = h("div", { class: "keywords-list" });
  all.forEach((kw) => {
    const low = String(kw).toLowerCase();
    const freq = frequencies[kw] || 1;
    const inT = in_target[kw] !== undefined ? in_target[kw] : targetCorpus.includes(low);
    const inM = in_master[kw] !== undefined ? in_master[kw] : masterCorpus.includes(low);
    let cls = "kw-chip";
    let title = "";
    let clickable = false;
    if (inT) {
      cls += " kw-chip-ok";
      title = `Presente en el CV generado (aparece ${freq}x en la oferta)`;
    } else if (inM) {
      cls += " kw-chip-missing";
      title = `Está en tu CV maestro pero no en esta selección. Aparece ${freq}x en la oferta. Clic para traer bullets.`;
      clickable = true;
      missingInTarget.push(kw);
    } else {
      cls += " kw-chip-notmaster";
      title = `La oferta la pide (${freq}x) pero no está en tu CV maestro — gap real`;
      notInMaster.push(kw);
    }
    const label = freq > 1 ? `${kw} ×${freq}` : kw;
    const chip = h("span", { class: cls, title }, label);
    if (clickable) {
      chip.style.cursor = "pointer";
      chip.addEventListener("click", () => handleMissingKeywordClick(kw));
    }
    list.appendChild(chip);
  });
  wrap.appendChild(list);

  if (missingInTarget.length > 0) {
    wrap.appendChild(h("p", { class: "kw-summary" },
      `Faltan en el target: ${missingInTarget.join(", ")}. Clic en una para traer bullets del master.`));
  }
  if (notInMaster.length > 0) {
    wrap.appendChild(h("p", { class: "kw-summary kw-summary-gap" },
      `No tenés en el master: ${notInMaster.join(", ")}.`));
  }

  container.appendChild(wrap);
}

// ----------------------------------------------------- oportunidades

function renderOpportunities() {
  const panel = $("#opportunities-panel");
  const list = $("#opportunities-list");
  if (!panel || !list) return;

  const critical = state.keywordReport?.critical_missing || [];
  panel.hidden = critical.length === 0;
  list.innerHTML = "";

  critical.forEach((kw) => {
    const freq = state.keywordReport.frequencies[kw] || 1;
    const item = h("div", { class: "opp-item" }, [
      h("div", { class: "opp-keyword" }, [
        h("strong", {}, kw),
        h("span", { class: "opp-freq" }, `×${freq}`),
      ]),
      h("button", {
        class: "btn btn-sm",
        onclick: () => handleMissingKeywordClick(kw),
      }, "Traer bullet"),
    ]);
    list.appendChild(item);
  });

  updateNotIncludedPanel();
}

// ----------------------------------------------------- contenido no incluido

function countExcluded() {
  if (!state.selection) return 0;
  return (state.selection.excluded_experience?.length || 0)
    + (state.selection.excluded_projects?.length || 0)
    + (state.selection.excluded_skills_indices?.length || 0)
    + (state.selection.excluded_education_indices?.length || 0);
}

function updateNotIncludedPanel() {
  const panel = $("#notincluded-panel");
  if (!panel) return;
  const critical = state.keywordReport?.critical_missing || [];
  const excluded = countExcluded();
  const total = critical.length + excluded;
  if (total === 0) {
    panel.hidden = true;
    return;
  }
  panel.hidden = false;
  const count = $("#notincluded-count");
  if (count) count.textContent = `${total} ítems · `;
}

function refreshKeywordWidgets() {
  recalcKeywordReport();
  renderResultSummary();
  renderKeywordReport();
  renderOpportunities();
  renderExcludedPanel();
}

// ----------------------------------------------------- bullet scores


// ----------------------------------------------------- excluded panel

function addEntryToTarget(sectionName, entryIdx) {
  if (!state.masterDocSnapshot || !state.targetDoc) return;
  const masterSections = state.masterDocSnapshot.cv?.sections || {};
  const masterEntry = masterSections[sectionName]?.[entryIdx];
  if (!masterEntry) return;

  const targetSections = state.targetDoc.cv.sections;
  if (!targetSections[sectionName]) {
    targetSections[sectionName] = [];
  }
  const exists = targetSections[sectionName].find(
    (e) => e._src_section === sectionName && e._src_index === entryIdx
  );
  if (exists) return;

  const copy = JSON.parse(JSON.stringify(masterEntry));
  copy._src_section = sectionName;
  copy._src_index = entryIdx;
  targetSections[sectionName].push(copy);
}

function addBulletToTarget(sectionName, entryIdx, bulletText) {
  if (!state.masterDocSnapshot || !state.targetDoc) return;
  const targetSections = state.targetDoc.cv.sections;
  if (!targetSections[sectionName]) {
    addEntryToTarget(sectionName, entryIdx);
  }
  const targetEntry = targetSections[sectionName].find(
    (e) => e._src_section === sectionName && e._src_index === entryIdx
  );
  if (!targetEntry) return;
  if (!targetEntry.highlights.includes(bulletText)) {
    targetEntry.highlights.push(bulletText);
  }
}

function renderExcludedPanel() {
  const panel = $("#excluded-panel");
  const content = $("#excluded-content");
  if (!panel || !content) return;

  if (!state.selection || !state.masterDocSnapshot) {
    panel.hidden = true;
    return;
  }

  const masterSections = state.masterDocSnapshot.cv?.sections || {};
  const hasAny = (
    (state.selection.excluded_experience?.length || 0) > 0 ||
    (state.selection.excluded_projects?.length || 0) > 0 ||
    (state.selection.excluded_skills_indices?.length || 0) > 0 ||
    (state.selection.excluded_education_indices?.length || 0) > 0
  );

  if (!hasAny) {
    panel.hidden = true;
    updateNotIncludedPanel();
    return;
  }

  panel.hidden = false;
  content.innerHTML = "";

  const sections = [
    { key: "experience", label: "Experiencia", nameKey: "company" },
    { key: "projects", label: "Proyectos", nameKey: "name" },
    { key: "skills", label: "Skills", nameKey: "label" },
    { key: "education", label: "Educación", nameKey: "institution" },
  ];

  sections.forEach((sec) => {
    let excludedItems;
    if (sec.key === "skills") {
      excludedItems = (state.selection.excluded_skills_indices || []).map((idx) => ({ index: idx }));
    } else if (sec.key === "education") {
      excludedItems = (state.selection.excluded_education_indices || []).map((idx) => ({ index: idx }));
    } else {
      excludedItems = state.selection[`excluded_${sec.key}`] || [];
    }

    if (excludedItems.length === 0) return;

    const secWrap = h("div", { class: "excluded-section" });
    secWrap.appendChild(h("h4", {}, sec.label));

    excludedItems.forEach((item) => {
      const idx = item.index;
      const masterEntry = masterSections[sec.key]?.[idx];
      if (!masterEntry) return;

      const name = masterEntry[sec.nameKey] || masterEntry.position || masterEntry.degree || `Entrada ${idx}`;
      const score = item.entry_score || null;
      const scoreLabel = score !== null ? `score: ${Math.round(score * 100)}%` : "";

      const entryWrap = h("div", { class: "excluded-entry" });
      entryWrap.appendChild(h("div", { class: "excluded-entry-header" }, [
        h("strong", {}, name),
        h("span", { class: "excluded-score" }, scoreLabel),
      ]));

      // Botón traer entrada completa
      entryWrap.appendChild(h("button", {
        class: "btn btn-sm btn-ghost",
        style: "margin-bottom:0.4rem",
        onclick: () => {
          addEntryToTarget(sec.key, idx);
          drawTargetView();
          toast(`Entrada "${name}" agregada desde excluidos.`);
        },
      }, "+ Traer entrada completa"));

      // Bullets individuales (solo para experience/projects)
      if (sec.key === "experience" || sec.key === "projects") {
        const highlights = masterEntry.highlights || [];
        const order = item.highlight_order || highlights.map((_, i) => i);
        order.forEach((bIdx) => {
          const text = highlights[bIdx];
          if (!text) return;
          const bulletId = `${sec.key}_${idx}_bullet_${bIdx}`;
          const bScore = state.selection.bullet_scores?.[bulletId];
          const bScoreLabel = bScore !== null ? `${Math.round(bScore * 100)}%` : "";

          const row = h("div", { class: "excluded-bullet" }, [
            h("span", { class: "bullet-mark" }, "—"),
            h("p", {}, text),
            h("span", { style: "font-family:var(--font-mono);font-size:0.7rem;color:var(--ink-faint);white-space:nowrap;" }, bScoreLabel),
            h("button", {
              class: "btn-icon",
              title: "Agregar este bullet",
              "aria-label": "Agregar este bullet",
              onclick: () => {
                addBulletToTarget(sec.key, idx, text);
                drawTargetView();
                toast("Bullet agregado desde excluidos.");
              },
            }, "+"),
          ]);
          entryWrap.appendChild(row);
        });
      }

      // Para skills: mostrar details
      if (sec.key === "skills") {
        const details = masterEntry.details || "";
        if (details) {
          entryWrap.appendChild(h("p", { style: "font-size:0.85rem;color:var(--ink-soft);margin:0.3rem 0;" }, details));
        }
        entryWrap.appendChild(h("button", {
          class: "btn btn-sm btn-ghost",
          onclick: () => {
            addEntryToTarget(sec.key, idx);
            drawTargetView();
            toast(`Skill "${name}" agregada desde excluidos.`);
          },
        }, "+ Traer skill"));
      }

      // Para education: mostrar highlights si existen
      if (sec.key === "education") {
        const highlights = masterEntry.highlights || [];
        highlights.forEach((text) => {
          entryWrap.appendChild(h("p", { style: "font-size:0.85rem;color:var(--ink-soft);margin:0.2rem 0;" }, `— ${text}`));
        });
        entryWrap.appendChild(h("button", {
          class: "btn btn-sm btn-ghost",
          onclick: () => {
            addEntryToTarget(sec.key, idx);
            drawTargetView();
            toast(`Educación "${name}" agregada desde excluidos.`);
          },
        }, "+ Traer educación"));
      }

      secWrap.appendChild(entryWrap);
    });

    content.appendChild(secWrap);
  });

  updateNotIncludedPanel();
}

function getBulletScore(bulletId) {
  if (!state.selection || !state.selection.bullet_scores) return null;
  return state.selection.bullet_scores[bulletId] || null;
}

function getJDSnippet(bulletId) {
  if (!state.selection || !state.selection.jd_snippets) return null;
  return state.selection.jd_snippets[bulletId] || null;
}

function getScoreMode() {
  return state.selection?.score_mode || "positional_fallback";
}

function getEntryScore(section, entryIdx) {
  if (!state.selection || !state.selection.section_scores) return null;
  const sec = state.selection.section_scores[section];
  if (!sec) return null;
  return sec[entryIdx] || null;
}

function renderBulletScore(bulletId) {
  const score = getBulletScore(bulletId);
  if (score === null) return null;
  const pct = Math.round(score * 100);
  const isFallback = getScoreMode() === "positional_fallback";
  const fillClass = isFallback ? "bullet-score-fill fallback" : "bullet-score-fill";
  const label = isFallback ? `${pct}% (estimado)` : `${pct}%`;
  const title = isFallback
    ? `Score estimado por posición: ${pct}% (cross-encoder no disponible)`
    : `Score de relevancia: ${pct}% (cross-encoder)`;
  const bar = h("div", { class: "bullet-score", title }, [
    h("div", { class: "bullet-score-bar" }, [
      h("div", { class: fillClass, style: `width:${pct}%` }),
    ]),
  ]);
  return bar;
}

function renderEntryHeatBorder(section, entryIdx) {
  const score = getEntryScore(section, entryIdx);
  if (score === null) return "";
  if (score >= 0.7) return "entry-heat-high";
  if (score >= 0.4) return "entry-heat-mid";
  return "entry-heat-low";
}

// ----------------------------------------------------- keyword click

async function handleMissingKeywordClick(keyword) {
  if (!state.masterDocSnapshot || !state.targetDoc) return;
  const kwLow = keyword.toLowerCase();

  // Buscar bullets en el master que contengan la keyword, con scores
  const matches = [];
  const sections = state.masterDocSnapshot.cv?.sections || {};
  for (const [sectionName, entries] of Object.entries(sections)) {
    if (!Array.isArray(entries)) continue;
    for (let entryIdx = 0; entryIdx < entries.length; entryIdx++) {
      const entry = entries[entryIdx];
      if (!entry || typeof entry !== "object") continue;
      const highlights = entry.highlights || [];
      for (let bulletIdx = 0; bulletIdx < highlights.length; bulletIdx++) {
        const text = highlights[bulletIdx];
        if (typeof text === "string" && text.toLowerCase().includes(kwLow)) {
          const bulletId = `${sectionName}_${entryIdx}_bullet_${bulletIdx}`;
          const score = getBulletScore(bulletId) || 0;
          matches.push({ sectionName, entryIdx, bulletIdx, text, entry, score });
        }
      }
    }
  }

  if (matches.length === 0) {
    await showMessageModal("Sin coincidencias", `No se encontró ningún bullet en el CV maestro que contenga "${keyword}".`);
    return;
  }

  // Ordenar por relevancia (score descendente)
  matches.sort((a, b) => b.score - a.score);

  const chosen = await openModal((close) => {
    const list = h("div", { class: "pullback-list" });
    matches.forEach((m) => {
      const label = m.entry.company || m.entry.name || m.entry.institution || `Entrada ${m.entryIdx}`;
      const scorePct = m.score > 0 ? Math.round(m.score * 100) : "—";
      const row = h("div", { class: "pullback-item" }, [
        h("div", { class: "pullback-info" }, [
          h("div", { class: "pullback-header" }, [
            h("strong", {}, label),
            h("span", { class: "pullback-score" }, `relevancia: ${scorePct}%`),
          ]),
          h("p", { class: "pullback-text" }, m.text),
        ]),
        h("button", {
          class: "btn-icon",
          title: "Agregar este bullet",
          "aria-label": "Agregar este bullet",
          onclick: () => close(m),
        }, "+"),
      ]);
      list.appendChild(row);
    });

    return h("div", {}, [
      h("h3", {}, `Bullets con "${keyword}"`),
      h("p", { class: "hint" }, "Ordenados por relevancia para esta oferta:"),
      list,
      h("div", { class: "modal-actions" }, [
        h("button", { class: "btn btn-ghost", onclick: () => close(null) }, "Cancelar"),
      ]),
    ]);
  });

  if (!chosen) return;

  // Calcular fit score antes
  const beforeScore = state.keywordReport?.ats_impact_score || 0;

  // Agregar el bullet al target
  const targetSections = state.targetDoc.cv.sections;
  const targetEntries = targetSections[chosen.sectionName];
  if (!targetEntries) {
    const masterEntry = JSON.parse(JSON.stringify(chosen.entry));
    masterEntry._src_section = chosen.sectionName;
    masterEntry._src_index = chosen.entryIdx;
    targetSections[chosen.sectionName] = [masterEntry];
  } else {
    let targetEntry = targetEntries.find((e) => e._src_index === chosen.entryIdx && e._src_section === chosen.sectionName);
    if (!targetEntry) {
      const masterEntry = JSON.parse(JSON.stringify(chosen.entry));
      masterEntry._src_section = chosen.sectionName;
      masterEntry._src_index = chosen.entryIdx;
      targetEntries.push(masterEntry);
      targetEntry = masterEntry;
    }
    if (!targetEntry.highlights.includes(chosen.text)) {
      targetEntry.highlights.push(chosen.text);
    }
  }

  // Recalcular keyword report localmente (aproximado)
  recalcKeywordReport();
  const afterScore = state.keywordReport?.ats_impact_score || 0;
  const delta = afterScore - beforeScore;

  drawTargetView();
  const deltaMsg = delta > 0 ? ` (+${delta}% ATS)` : "";
  toast(`Bullet agregado para "${keyword}"${deltaMsg}.`);
}

function recalcKeywordReport() {
  if (!state.keywordReport || !state.targetDoc) return;
  const masterCorpus = buildDocCorpus(state.masterDocSnapshot);
  const targetCorpus = buildDocCorpus(state.targetDoc);
  const { frequencies, in_master } = state.keywordReport;
  const all = effectiveKeywordList();

  let coveredWeight = 0;
  let totalWeight = 0;
  const newInTarget = {};
  const newMissing = [];
  const newCritical = [];

  for (const kw of all) {
    const low = String(kw).toLowerCase();
    const present = targetCorpus.includes(low);
    newInTarget[kw] = present;
    const freq = frequencies[kw] || 1;
    const inM = in_master[kw] !== undefined ? in_master[kw] : masterCorpus.includes(low);
    totalWeight += freq;
    if (present) coveredWeight += freq;
    else {
      if (inM) newMissing.push(kw);
      if (freq >= 2 && inM) newCritical.push(kw);
    }
  }

  state.keywordReport.in_target = newInTarget;
  state.keywordReport.missing_in_target = newMissing;
  state.keywordReport.critical_missing = newCritical;
  state.keywordReport.ats_impact_score = totalWeight > 0 ? Math.round((coveredWeight / totalWeight) * 100) : 100;
}

// -------------------------------------------------------------- modal

function openModal(builder) {
  return new Promise((resolve) => {
    const overlay = $("#modal-overlay");
    const box = $("#modal-box");
    const previousFocus = document.activeElement;
    box.innerHTML = "";
    let settled = false;
    const close = (value) => {
      if (settled) return;
      settled = true;
      overlay.hidden = true;
      overlay.onclick = null;
      overlay.onkeydown = null;
      if (previousFocus && typeof previousFocus.focus === "function") previousFocus.focus();
      resolve(value);
    };
    box.appendChild(builder(close));
    overlay.hidden = false;
    overlay.onclick = (e) => { if (e.target === overlay) close(null); };
    overlay.onkeydown = (e) => {
      if (e.key === "Escape") {
        e.preventDefault();
        close(null);
        return;
      }
      if (e.key !== "Tab") return;
      const focusables = box.querySelectorAll("button, [href], input, select, textarea, [tabindex]:not([tabindex='-1'])");
      if (focusables.length === 0) return;
      const first = focusables[0];
      const last = focusables[focusables.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    };
    const firstFocusable = box.querySelector("input, button, textarea, select, [href], [tabindex]:not([tabindex='-1'])");
    if (firstFocusable && typeof firstFocusable.focus === "function") firstFocusable.focus();
  });
}

function showMessageModal(title, message) {
  return openModal((close) => h("div", {}, [
    h("h3", {}, title),
    h("p", {}, message),
    h("div", { class: "modal-actions" }, [
      h("button", { class: "btn btn-primary", onclick: () => close(true) }, "Entendido"),
    ]),
  ]));
}

function confirmAction(opts) {
  const title = opts.title || "Confirmar acción";
  const message = opts.message || "¿Querés continuar?";
  const confirmLabel = opts.confirmLabel || "Confirmar";
  const cancelLabel = opts.cancelLabel || "Cancelar";
  return openModal((close) => h("div", {}, [
    h("h3", {}, title),
    h("p", {}, message),
    h("div", { class: "modal-actions" }, [
      h("button", { class: "btn btn-ghost", onclick: () => close(false) }, cancelLabel),
      h("button", { class: "btn btn-primary", onclick: () => close(true) }, confirmLabel),
    ]),
  ]));
}

function promptAddSection() {
  return openModal((close) => {
    const nameInput = h("input", { type: "text", placeholder: "ej: certifications, awards" });
    let type = "entries";
    const typeRow = h("div", { class: "type-options" }, [
      h("label", {}, [
        h("input", { type: "radio", name: "sec-type", value: "entries", checked: "checked",
          onchange: () => (type = "entries") }),
        "Entradas con viñetas ",
        h("span", { class: "type-hint" }, "— como experiencia o proyectos"),
      ]),
      h("label", {}, [
        h("input", { type: "radio", name: "sec-type", value: "label_details",
          onchange: () => (type = "label_details") }),
        "Lista etiqueta / detalle ",
        h("span", { class: "type-hint" }, "— como skills"),
      ]),
      h("label", {}, [
        h("input", { type: "radio", name: "sec-type", value: "text",
          onchange: () => (type = "text") }),
        "Texto simple ",
        h("span", { class: "type-hint" }, "— como el resumen"),
      ]),
    ]);

    return h("div", {}, [
      h("h3", {}, "Nueva sección"),
      h("div", { class: "field" }, [
        h("label", {}, "Nombre de la sección"),
        nameInput,
      ]),
      h("div", { class: "field" }, [
        h("label", {}, "Tipo de contenido"),
        typeRow,
      ]),
      h("div", { class: "modal-actions" }, [
        h("button", { class: "btn btn-ghost", onclick: () => close(null) }, "Cancelar"),
        h("button", {
          class: "btn btn-primary",
          onclick: () => {
            const name = nameInput.value.trim().toLowerCase().replace(/\s+/g, "_");
            if (!name) { nameInput.focus(); return; }
            close({ name, type });
          },
        }, "Agregar"),
      ]),
    ]);
  });
}

// -------------------------------------------------------- section types

function defaultSectionType(name) {
  if (["summary", "objective", "keywords", "interests"].includes(name)) return "text";
  if (["skills", "languages"].includes(name)) return "label_details";
  return "entries";
}

function detectSectionType(name, entries, sectionTypes) {
  if (!entries || entries.length === 0) return null;
  const first = entries[0];
  if (typeof first === "string") return "text";
  if (first && typeof first === "object" && "highlights" in first) return "entries";
  return "label_details";
}

function deriveSectionTypes(doc) {
  const sections = doc?.cv?.sections || {};
  const out = {};
  Object.keys(sections).forEach((name) => {
    out[name] = detectSectionType(name, sections[name], null) || defaultSectionType(name);
  });
  return out;
}

function blankEntryFor(sectionName, type) {
  if (type === "text") return "";
  if (type === "label_details") return { label: "", details: "" };
  if (sectionName === "experience") {
    return { company: "", position: "", location: "", start_date: "", end_date: "", highlights: [] };
  }
  if (sectionName === "education") {
    return { institution: "", area: "", degree: "", start_date: "", end_date: "", highlights: [] };
  }
  return { name: "", date: "", highlights: [] };
}

// ------------------------------------------------------------ renderer

function renderSections(container, ctx) {
  container.innerHTML = "";
  const sections = ctx.doc.cv.sections || {};
  for (const name of Object.keys(sections)) {
    container.appendChild(renderSectionBlock(name, sections[name], ctx));
  }
}

function renderSectionNav(container, sectionsContainer, sections) {
  if (!container) return;
  container.innerHTML = "";
  const names = Object.keys(sections || {});
  if (names.length === 0) return;
  names.forEach((name) => {
    const entries = sections[name] || [];
    const count = Array.isArray(entries) ? entries.length : 0;
    const label = `${humanizeSectionName(name)} (${count})`;
    const btn = h("button", {
      type: "button",
      onclick: () => {
        const target = sectionsContainer.querySelector(`[data-section="${name}"]`);
        if (target) target.scrollIntoView({ behavior: "smooth", block: "start" });
      },
    }, label);
    container.appendChild(btn);
  });
}

function renderSectionBlock(name, entries, ctx) {
  const type = detectSectionType(name, entries, ctx.sectionTypes) || ctx.sectionTypes?.[name] || defaultSectionType(name);
  const block = h("div", { class: "section-block", "data-section": name });

  const removeBtn = h("button", {
    class: "btn-icon danger", title: "Sacar sección", "aria-label": "Sacar sección",
    onclick: async () => {
      const isCoreMasterSection = !ctx.isTarget && ["experience", "education", "skills"].includes(name);
      const confirmed = await confirmAction({
        title: "Eliminar sección",
        message: isCoreMasterSection
          ? `La sección "${humanizeSectionName(name)}" es base para el armado del CV. ¿Seguro que querés eliminarla del CV maestro?`
          : `¿Sacar la sección "${humanizeSectionName(name)}" del ${ctx.isTarget ? "CV generado" : "CV maestro"}?`,
        confirmLabel: "Eliminar sección",
      });
      if (!confirmed) return;
      const sections = ctx.doc.cv.sections;
      const removed = sections[name];
      const removedType = ctx.sectionTypes ? ctx.sectionTypes[name] : null;
      rememberUndo("Eliminar sección " + humanizeSectionName(name), () => {
        sections[name] = removed;
        if (ctx.sectionTypes && removedType !== null) ctx.sectionTypes[name] = removedType;
        ctx.onRerender();
      });
      delete sections[name];
      if (ctx.sectionTypes) delete ctx.sectionTypes[name];
      ctx.onRerender();
    },
  }, "×");

  const regeneratable = ["experience", "projects", "skills"];
  let regenBtn = null;
  if (ctx.isTarget && regeneratable.includes(name)) {
    regenBtn = h("button", { class: "btn-icon regen", title: "Regenerar esta sección con la IA", "aria-label": "Regenerar esta sección con la IA" }, "↻");
    regenBtn.addEventListener("click", async () => {
      const jd = $("#job-description").value;
      if (!jd.trim()) {
        await showMessageModal("Falta la oferta laboral", "Primero pegá la oferta laboral para poder regenerar esta sección.");
        return;
      }
      regenBtn.disabled = true;
      regenBtn.textContent = "…";
      try {
        const result = await api("/api/regenerate-section", {
          method: "POST",
          body: JSON.stringify({ job_description: jd, section_name: name }),
        });
        ctx.doc.cv.sections[name] = result.entries;
        if (ctx.sectionTypes) ctx.sectionTypes[name] = detectSectionType(name, result.entries, ctx.sectionTypes) || defaultSectionType(name);
        state.selection = state.selection || {};
        Object.assign(state.selection, result.selection);
        ctx.onRerender();
        toast(`Se regeneró "${humanizeSectionName(name)}".`);
      } catch (e) {
        setGlobalStatus("No se pudo regenerar la sección: " + e.message, "error");
      } finally {
        regenBtn.disabled = false;
        regenBtn.textContent = "↻";
      }
    });
  }

  const sectionActions = h("div", { class: "section-actions" }, [regenBtn, removeBtn]);

  if (!ctx.isTarget) {
    const collapsed = Boolean(state.collapsedMaster && state.collapsedMaster[name]);
    const toggleBtn = h("button", {
      class: "btn-icon",
      title: collapsed ? "Expandir sección" : "Contraer sección",
      "aria-label": "Contraer o expandir sección",
      onclick: () => {
        state.collapsedMaster = state.collapsedMaster || {};
        state.collapsedMaster[name] = !state.collapsedMaster[name];
        ctx.onRerender();
      },
    }, collapsed ? "▸" : "▾");
    sectionActions.insertBefore(toggleBtn, sectionActions.firstChild);
  }

  block.appendChild(h("div", { class: "section-head" }, [
    h("div", { class: "titles" }, [
      h("h2", {}, humanizeSectionName(name)),
      h("span", { class: "eyebrow" }, name),
    ]),
    sectionActions,
  ]));

  const body = h("div", { class: "section-body" });
  if (type === "text") body.appendChild(renderTextList(name, entries, ctx));
  else if (type === "label_details") body.appendChild(renderLabelDetailsList(name, entries, ctx));
  else body.appendChild(renderEntriesList(name, entries, ctx));
  block.appendChild(body);

  if (state.collapsedMaster && state.collapsedMaster[name]) block.classList.add("collapsed");

  return block;
}

function humanizeSectionName(name) {
  return name.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

// -- tipo "text" -----------

function renderTextList(sectionName, entries, ctx) {
  const wrap = h("div", {});
  entries.forEach((value, i) => {
    const ta = h("textarea", { class: "highlight-text" });
    ta.value = value;
    setTimeout(() => autoResize(ta), 0);
    ta.addEventListener("input", () => { entries[i] = ta.value; autoResize(ta); });

    const del = h("button", {
      class: "btn-icon danger", title: "Sacar", "aria-label": "Sacar ítem",
      onclick: () => {
        rememberUndo("Eliminar ítem", () => { entries.splice(i, 0, value); ctx.onRerender(); });
        entries.splice(i, 1);
        ctx.onRerender();
      },
    }, "×");

    wrap.appendChild(h("div", { class: "highlight-row" }, [
      h("span", { class: "bullet-mark" }, "—"),
      ta,
      h("div", { class: "row-controls" }, [del]),
    ]));
  });

  wrap.appendChild(h("button", {
    class: "btn btn-ghost",
    onclick: () => { entries.push(""); ctx.onRerender(); },
  }, "+ Agregar"));
  wrap.appendChild(h("button", {
    class: "btn btn-ghost",
    style: "margin-left:0.45rem",
    onclick: async () => {
      const lines = await openModal((close) => {
        const ta = h("textarea", { rows: "8", placeholder: "Pegá una línea por ítem" });
        return h("div", {}, [
          h("h3", {}, "Agregar varios ítems"),
          h("div", { class: "field" }, [ta]),
          h("div", { class: "modal-actions" }, [
            h("button", { class: "btn btn-ghost", onclick: () => close(null) }, "Cancelar"),
            h("button", {
              class: "btn btn-primary",
              onclick: () => close(ta.value.split(/\r?\n/).map((x) => x.trim()).filter(Boolean)),
            }, "Agregar"),
          ]),
        ]);
      });
      if (!lines || lines.length === 0) return;
      entries.push(...lines);
      ctx.onRerender();
    },
  }, "Pegar varios"));

  return wrap;
}

// -- tipo "label_details" ----------------------------

function renderLabelDetailsList(sectionName, entries, ctx) {
  const wrap = h("div", {});
  entries.forEach((entry, i) => {
    const labelInput = h("input", { type: "text", value: entry.label || "", placeholder: "Categoría" });
    labelInput.addEventListener("input", () => (entry.label = labelInput.value));
    const detailsInput = h("input", { type: "text", value: entry.details || "", placeholder: "Detalle" });
    detailsInput.addEventListener("input", () => (entry.details = detailsInput.value));

    const del = h("button", {
      class: "btn-icon danger", title: "Sacar", "aria-label": "Sacar ítem",
      onclick: () => {
        rememberUndo("Eliminar ítem", () => { entries.splice(i, 0, entry); ctx.onRerender(); });
        entries.splice(i, 1);
        ctx.onRerender();
      },
    }, "×");

    const row = h("div", { class: "entry-card" }, [
      h("div", { class: "entry-fields" }, [
        h("div", { class: "field" }, [h("label", {}, fieldLabel("label")), labelInput]),
        h("div", { class: "field" }, [h("label", {}, fieldLabel("details")), detailsInput]),
      ]),
      h("div", { class: "row-controls" }, [del]),
    ]);
    row.querySelector(".entry-fields").style.display = "grid";
    wrap.appendChild(row);
  });

  wrap.appendChild(h("button", {
    class: "btn btn-ghost",
    onclick: () => { entries.push(blankEntryFor(sectionName, "label_details")); ctx.onRerender(); },
  }, "+ Agregar"));

  return wrap;
}

// -- tipo "entries" -----------

function renderEntriesList(sectionName, entries, ctx) {
  const wrap = h("div", {});

  entries.forEach((entry, i) => {
    wrap.appendChild(renderEntryCard(sectionName, entries, entry, i, ctx));
  });

  const actions = h("div", { class: "save-bar" });
  actions.appendChild(h("button", {
    class: "btn btn-ghost",
    onclick: () => {
      const template = entries.length > 0
        ? Object.fromEntries(Object.keys(entries[0]).filter((k) => !k.startsWith("_"))
            .map((k) => [k, k === "highlights" ? [] : ""]))
        : blankEntryFor(sectionName, "entries");
      entries.push(template);
      ctx.onRerender();
    },
  }, "+ Agregar entrada"));
  actions.appendChild(h("button", {
    class: "btn btn-ghost",
    disabled: entries.length === 0 ? "disabled" : null,
    onclick: () => {
      const last = entries[entries.length - 1];
      if (!last) return;
      const copy = JSON.parse(JSON.stringify(last));
      entries.push(copy);
      ctx.onRerender();
    },
  }, "Duplicar última"));
  wrap.appendChild(actions);

  return wrap;
}

function renderEntryCard(sectionName, entries, entry, index, ctx) {
  const fieldKeys = Object.keys(entry).filter((k) => k !== "highlights" && !k.startsWith("_"));
  const fieldsWrap = h("div", { class: "entry-fields" });
  fieldKeys.forEach((key) => {
    const input = h("input", { type: "text", value: entry[key] ?? "" });
    input.addEventListener("input", () => (entry[key] = input.value));
    fieldsWrap.appendChild(h("div", { class: "field" }, [h("label", {}, fieldLabel(key)), input]));
  });

  const moveUp = h("button", {
    class: "btn-icon", title: "Subir", "aria-label": "Subir entrada", disabled: index === 0 ? "disabled" : null,
    onclick: () => { [entries[index - 1], entries[index]] = [entries[index], entries[index - 1]]; ctx.onRerender(); },
  }, "↑");
  const moveDown = h("button", {
    class: "btn-icon", title: "Bajar", "aria-label": "Bajar entrada", disabled: index === entries.length - 1 ? "disabled" : null,
    onclick: () => { [entries[index + 1], entries[index]] = [entries[index], entries[index + 1]]; ctx.onRerender(); },
  }, "↓");
  const del = h("button", {
    class: "btn-icon danger", title: "Sacar entrada", "aria-label": "Sacar entrada",
    onclick: async () => {
      const confirmed = await confirmAction({
        title: "Eliminar entrada",
        message: "¿Querés eliminar esta entrada?",
        confirmLabel: "Eliminar",
      });
      if (!confirmed) return;
      rememberUndo("Eliminar entrada", () => { entries.splice(index, 0, entry); ctx.onRerender(); });
      entries.splice(index, 1);
      ctx.onRerender();
    },
  }, "×");

  // Heatmap: clase extra según score de la entrada
  const heatClass = ctx.isTarget ? renderEntryHeatBorder(sectionName, entry._src_index) : "";
  const card = h("div", { class: "entry-card" + (heatClass ? " " + heatClass : "") });
  card.appendChild(h("div", { class: "entry-top-row" }, [
    fieldsWrap,
    h("div", { class: "row-controls" }, [moveUp, moveDown, del]),
  ]));

  const matchReason = ctx.isTarget ? getMatchReason(entry, ctx.selection) : null;
  if (matchReason) {
    const reasonEl = h("p", { class: "match-reason" }, "por qué se eligió: " + matchReason);
    // Tooltip con JD snippet
    if (ctx.isTarget && entry._src_section && entry._src_index !== undefined) {
      const firstBulletId = `${entry._src_section}_${entry._src_index}_bullet_0`;
      const snippet = getJDSnippet(firstBulletId);
      if (snippet) {
        reasonEl.tabIndex = 0;
        reasonEl.addEventListener("mouseenter", () => showJDSnippet(snippet, reasonEl));
        reasonEl.addEventListener("mouseleave", hideJDSnippet);
        reasonEl.addEventListener("focus", () => showJDSnippet(snippet, reasonEl));
        reasonEl.addEventListener("blur", hideJDSnippet);
      }
    }
    card.appendChild(reasonEl);
  }

  if ("highlights" in entry) {
    card.appendChild(renderHighlights(entry, ctx, sectionName, index));
  }

  if (ctx.isTarget && entry._src_section && entry._src_index !== undefined) {
    const pb = renderPullback(entry, ctx);
    if (pb) card.appendChild(pb);
  }

  return card;
}

function renderHighlights(entry, ctx, sectionName, entryIndex) {
  const wrap = h("div", { class: "highlights" });
  entry.highlights.forEach((text, i) => {
    const ta = h("textarea", { class: "highlight-text" });
    ta.value = text;
    setTimeout(() => autoResize(ta), 0);
    ta.addEventListener("input", () => { entry.highlights[i] = ta.value; autoResize(ta); });

    // Score de relevancia del bullet
    let scoreEl = null;
    if (ctx.isTarget && entry._src_section !== undefined && entry._src_index !== undefined) {
      const bulletId = `${entry._src_section}_${entry._src_index}_bullet_${i}`;
      scoreEl = renderBulletScore(bulletId);
    }

    const moveUp = h("button", {
      class: "btn-icon", title: "Subir", "aria-label": "Subir bullet", disabled: i === 0 ? "disabled" : null,
      onclick: () => {
        [entry.highlights[i - 1], entry.highlights[i]] = [entry.highlights[i], entry.highlights[i - 1]];
        ctx.onRerender();
      },
    }, "↑");
    const moveDown = h("button", {
      class: "btn-icon", title: "Bajar", "aria-label": "Bajar bullet", disabled: i === entry.highlights.length - 1 ? "disabled" : null,
      onclick: () => {
        [entry.highlights[i + 1], entry.highlights[i]] = [entry.highlights[i], entry.highlights[i + 1]];
        ctx.onRerender();
      },
    }, "↓");
    const del = h("button", {
      class: "btn-icon danger", title: "Sacar bullet", "aria-label": "Sacar bullet",
      onclick: () => {
        rememberUndo("Eliminar bullet", () => { entry.highlights.splice(i, 0, text); ctx.onRerender(); });
        entry.highlights.splice(i, 1);
        ctx.onRerender();
      },
    }, "×");

    const row = h("div", { class: "highlight-row" }, [
      h("span", { class: "bullet-mark" }, "—"),
      ta,
      h("div", { class: "row-controls" }, [moveUp, moveDown, del]),
    ]);
    if (scoreEl) {
      row.appendChild(scoreEl);
      // Tooltip con JD snippet
      const snippet = getJDSnippet(`${entry._src_section}_${entry._src_index}_bullet_${i}`);
      if (snippet) {
        scoreEl.tabIndex = 0;
        scoreEl.addEventListener("mouseenter", () => showJDSnippet(snippet, scoreEl));
        scoreEl.addEventListener("mouseleave", hideJDSnippet);
        scoreEl.addEventListener("focus", () => showJDSnippet(snippet, scoreEl));
        scoreEl.addEventListener("blur", hideJDSnippet);
      }
    }
    wrap.appendChild(row);
  });

  const actions = h("div", { class: "save-bar" });
  actions.appendChild(h("button", {
    class: "btn btn-ghost",
    onclick: () => { entry.highlights.push(""); ctx.onRerender(); },
  }, "+ Agregar bullet"));
  actions.appendChild(h("button", {
    class: "btn btn-ghost",
    onclick: async () => {
      const paste = await openModal((close) => {
        const ta = h("textarea", { rows: "8", placeholder: "Pegá una línea por bullet" });
        return h("div", {}, [
          h("h3", {}, "Agregar varios bullets"),
          h("div", { class: "field" }, [ta]),
          h("div", { class: "modal-actions" }, [
            h("button", { class: "btn btn-ghost", onclick: () => close(null) }, "Cancelar"),
            h("button", {
              class: "btn btn-primary",
              onclick: () => {
                const lines = ta.value.split(/\r?\n/).map((x) => x.trim()).filter(Boolean);
                close(lines);
              },
            }, "Agregar"),
          ]),
        ]);
      });
      if (!paste || paste.length === 0) return;
      entry.highlights.push(...paste);
      ctx.onRerender();
    },
  }, "Pegar varios bullets"));
  wrap.appendChild(actions);

  return wrap;
}

// -- "traer bullet del master" ------------

function getMatchReason(entry, selection) {
  if (!selection || !entry._src_section) return null;
  const list = entry._src_section === "experience" ? selection.selected_experience : selection.selected_projects;
  const match = (list || []).find((x) => x.index === entry._src_index);
  return match ? match.match_reason : null;
}

function renderPullback(entry, ctx) {
  const masterList = ctx.masterDoc?.cv?.sections?.[entry._src_section];
  const original = masterList ? masterList[entry._src_index] : null;
  if (!original) return null;

  const missing = (original.highlights || []).filter((h) => !entry.highlights.includes(h));
  if (missing.length === 0) return null;

  // Ordenar missing por relevancia (score del bullet)
  const scoredMissing = missing.map((text, idx) => {
    const bulletId = `${entry._src_section}_${entry._src_index}_bullet_${idx}`;
    const score = getBulletScore(bulletId) || 0;
    return { text, score, idx };
  });
  scoredMissing.sort((a, b) => b.score - a.score);

  const details = h("details", { class: "pullback" });
  details.appendChild(h("summary", {}, `+ traer bullet del master (${missing.length} sin usar)`));
  scoredMissing.forEach((item) => {
    const scorePct = item.score > 0 ? Math.round(item.score * 100) : null;
    const row = h("div", { class: "pullback-item" }, [
      h("div", { class: "pullback-info" }, [
        h("p", {}, item.text),
        scorePct ? h("span", { class: "pullback-mini-score" }, `relevancia: ${scorePct}%`) : null,
      ]),
      h("button", {
        class: "btn-icon", title: "Agregar", "aria-label": "Agregar este bullet",
        onclick: () => { entry.highlights.push(item.text); ctx.onRerender(); },
      }, "+"),
    ]);
    details.appendChild(row);
  });
  return details;
}

// ------------------------------------------------------------- header

function renderHeader(container, doc, onDirty) {
  container.innerHTML = "";
  const cv = doc.cv;
  const fields = [
    ["name", "Nombre"], ["location", "Ubicación"], ["email", "Email"], ["phone", "Teléfono"],
  ];
  const grid = h("div", { class: "header-fields" });
  fields.forEach(([key, label]) => {
    const input = h("input", { type: "text", value: cv[key] || "" });
    input.addEventListener("input", () => { cv[key] = input.value; onDirty && onDirty(); });
    grid.appendChild(h("div", { class: "field" }, [h("label", {}, label), input]));
  });
  container.appendChild(grid);

  const socialWrap = h("div", { class: "field", style: "margin-top:0.6rem" });
  socialWrap.appendChild(h("label", {}, "Redes"));
  const socials = cv.social_networks || (cv.social_networks = []);
  const listEl = h("div", {});
  function drawSocials() {
    listEl.innerHTML = "";
    socials.forEach((s, i) => {
      const netInput = h("input", { type: "text", value: s.network || "", placeholder: "LinkedIn" });
      netInput.addEventListener("input", () => { s.network = netInput.value; onDirty && onDirty(); });
      const userInput = h("input", { type: "text", value: s.username || "", placeholder: "usuario" });
      userInput.addEventListener("input", () => { s.username = userInput.value; onDirty && onDirty(); });
      const del = h("button", {
        class: "btn-icon danger", title: "Eliminar red social", "aria-label": "Eliminar red social",
        onclick: async () => {
          const confirmed = await confirmAction({
            title: "Eliminar red social",
            message: "¿Eliminar este enlace de redes?",
            confirmLabel: "Eliminar",
          });
          if (!confirmed) return;
          socials.splice(i, 1);
          onDirty && onDirty();
          drawSocials();
        },
      }, "×");
      listEl.appendChild(h("div", { class: "social-row" }, [netInput, userInput, del]));
    });
  }
  drawSocials();
  socialWrap.appendChild(listEl);
  socialWrap.appendChild(h("button", {
    class: "btn btn-ghost",
    onclick: () => { socials.push({ network: "", username: "" }); onDirty && onDirty(); drawSocials(); },
  }, "+ Agregar red"));
  container.appendChild(socialWrap);
}

// --------------------------------------------------------- vista: master

async function loadMasterView() {
  state.masterDoc = await api("/api/master-cv");
  state.masterSectionTypes = deriveSectionTypes(state.masterDoc);
  drawMasterView();
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
    const bullets = [...card.querySelectorAll(".highlight-row")];
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
    await api("/api/master-cv", { method: "POST", body: JSON.stringify(state.masterDoc) });
    dirty.master = false;
    setStatus(statusEl, "Guardado.", "ok");
    toast("CV maestro guardado.");
  } catch (e) {
    setStatus(statusEl, e.message, "error");
    setGlobalStatus("No se pudo guardar el CV maestro: " + e.message, "error");
  } finally {
    btn.disabled = false;
  }
});

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
  setStatus(statusEl, "Consultando al modelo local (puede tardar según tu hardware)…");
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

// ------------------------------------------------------- vista: settings

const SETTINGS_FIELDS = [
  { key: "ollama_model", label: "Modelo de Ollama", type: "text", hint: "ej: llama3:8b, llama3.1:8b" },
  { key: "rendercv_theme", label: "Tema de RenderCV", type: "text", hint: "ej: engineeringresumes, classic, sb2nov" },
  { key: "max_experience_entries", label: "Máx. experiencias", type: "number" },
  { key: "max_project_entries", label: "Máx. proyectos", type: "number" },
  { key: "max_highlights_per_entry", label: "Máx. bullets por entrada", type: "number" },
  { key: "max_skill_categories", label: "Máx. categorías de skills", type: "number" },
  { key: "max_education_extra", label: "Máx. certificaciones extra", type: "number" },
  { key: "max_keywords", label: "Máx. keywords ATS", type: "number" },
  {
    key: "show_keywords_line",
    label: "Mostrar línea \"Palabras clave\" en el CV",
    type: "boolean",
    hint: "Ayuda contra ATS de conteo simple, pero un reclutador humano puede leerla como relleno. Si lo apagás, las keywords siguen influyendo en qué bullets/skills se priorizan — solo se oculta la línea explícita.",
  },
];

function validateConfig(config) {
  const validated = { ...config };
  for (const field of SETTINGS_FIELDS) {
    const value = validated[field.key];
    if (field.type === "number") {
      if (!Number.isInteger(value) || value < 1) {
        throw new Error(`"${field.label}" debe ser un número entero mayor o igual a 1.`);
      }
      continue;
    }
    if (field.type === "boolean") {
      validated[field.key] = Boolean(value);
      continue;
    }
    if (typeof value !== "string" || value.trim() === "") {
      throw new Error(`"${field.label}" no puede estar vacío.`);
    }
    validated[field.key] = value.trim();
  }
  return validated;
}

async function loadSettingsView() {
  state.config = await api("/api/config");
  drawSettingsView();
}

function drawSettingsView() {
  const form = $("#settings-form");
  form.innerHTML = "";
  SETTINGS_FIELDS.forEach((f) => {
    if (f.type === "boolean") {
      const checkbox = h("input", { type: "checkbox" });
      checkbox.checked = Boolean(state.config[f.key]);
      checkbox.addEventListener("change", () => {
        state.config[f.key] = checkbox.checked;
      });
      const fieldEl = h("div", { class: "settings-field settings-field-boolean" }, [
        h("label", { class: "settings-checkbox-label" }, [checkbox, " " + f.label]),
      ]);
      if (f.hint) fieldEl.appendChild(h("span", { class: "hint" }, f.hint));
      form.appendChild(fieldEl);
      return;
    }
    const input = h("input", {
      type: f.type,
      value: state.config[f.key],
      min: f.type === "number" ? 1 : null,
      step: f.type === "number" ? 1 : null,
    });
    input.addEventListener("input", () => {
      if (f.type === "number") {
        state.config[f.key] = input.value === "" ? null : Number.parseInt(input.value, 10);
      } else {
        state.config[f.key] = input.value;
      }
    });
    const fieldEl = h("div", { class: "settings-field" }, [
      h("label", {}, f.label),
      input,
    ]);
    if (f.hint) fieldEl.appendChild(h("span", { class: "hint" }, f.hint));
    form.appendChild(fieldEl);
  });
}

$("#save-settings").addEventListener("click", async () => {
  const statusEl = $("#settings-status");
  setStatus(statusEl, "Guardando…");
  const btn = $("#save-settings");
  btn.disabled = true;
  try {
    const payload = validateConfig(state.config);
    state.config = await api("/api/config", { method: "POST", body: JSON.stringify(payload) });
    dirty.settings = false;
    setStatus(statusEl, "Guardado.", "ok");
    toast("Configuración guardada.");
  } catch (e) {
    setStatus(statusEl, e.message, "error");
    setGlobalStatus("No se pudo guardar la configuración: " + e.message, "error");
  } finally {
    btn.disabled = false;
  }
});

// ------------------------------------------------------------- tabs/init

function viewNameFor(id) {
  return id === "view-master" ? "master" : id === "view-apply" ? "apply" : "settings";
}

async function switchView(btn) {
  const currentView = document.querySelector(".view.is-active");
  const viewName = viewNameFor(currentView.id);
  if (dirty[viewName] && !btn.classList.contains("is-active")) {
    const ok = await confirmAction({
      title: "Cambios sin guardar",
      message: "Tenés cambios sin guardar en esta vista. ¿Salir igual?",
      confirmLabel: "Salir igual",
      cancelLabel: "Quedarme",
    });
    if (!ok) return;
  }
  document.querySelectorAll(".tab").forEach((t) => {
    const active = t === btn;
    t.classList.toggle("is-active", active);
    t.setAttribute("aria-selected", String(active));
  });
  document.querySelectorAll(".view").forEach((v) => {
    v.classList.toggle("is-active", v.id === "view-" + btn.dataset.view);
  });
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
  const [master, settings] = await Promise.allSettled([loadMasterView(), loadSettingsView()]);
  const failures = [master, settings].filter((x) => x.status === "rejected");
  if (failures.length > 0) {
    const detail = failures.map((f) => f.reason && f.reason.message ? f.reason.message : String(f.reason)).join(" | ");
    setGlobalStatus("No se pudo cargar toda la app: " + detail, "error");
    console.error(detail);
  }
})();
