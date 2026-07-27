"use strict";

/* =====================================================================
   cv-adapter — frontend v2.1
   Nuevas features:
   - Relevancia por bullet (score 0-100 con mini barra)
   - Heatmap de entrada (borde colorido según score promedio)
   - JD snippet en hover (tooltip flotante con el fragmento de oferta)
   - Oportunidades críticas (keywords de alta frecuencia missing)
   - Delta de fit al agregar bullets
   - Pullback ordenado por relevancia
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
};

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

// -------------------------------------------------------- chequeo ATS

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

function renderAtsChecklist() {
  const container = $("#ats-checklist");
  if (!container) return;
  const raw = ($("#ats-keywords") && $("#ats-keywords").value) || "";
  const keywords = raw.split(",").map((s) => s.trim()).filter(Boolean);
  container.innerHTML = "";
  if (keywords.length === 0 || !state.targetDoc) return;

  const targetCorpus = buildDocCorpus(state.targetDoc);
  const masterCorpus = buildDocCorpus(state.masterDocSnapshot);

  keywords.forEach((kw) => {
    const low = kw.toLowerCase();
    let cls = "ats-missing", title = "no está en tu CV maestro — no se puede agregar sin inventar";
    if (targetCorpus.includes(low)) { cls = "ats-ok"; title = "está en el CV que vas a generar"; }
    else if (masterCorpus.includes(low)) { cls = "ats-gap"; title = "está en tu master pero no en esta selección — probá 'traer bullet del master'"; }
    container.appendChild(h("span", { class: "ats-item " + cls, title }, kw));
  });
}

// ----------------------------------------------------- keyword report

function renderFitScore() {
  const row = $("#fit-score-row");
  const fill = $("#fit-score-fill");
  const label = $("#fit-score-label");
  if (!state.keywordReport) {
    row.hidden = true;
    return;
  }
  const all = state.keywordReport.all_keywords || [];
  if (all.length === 0) {
    row.hidden = true;
    return;
  }
  // Usar ats_impact_score si está disponible (ponderado por frecuencia)
  const pct = state.keywordReport.ats_impact_score || 0;

  row.hidden = false;
  fill.style.width = pct + "%";
  fill.className = "fit-score-fill" + (pct >= 80 ? " fit-good" : pct >= 50 ? " fit-mid" : " fit-bad");
  label.textContent = `ATS Impact Score: ${pct}%`;
}

function renderKeywordReport() {
  const container = $("#keyword-report");
  if (!container) return;
  container.innerHTML = "";

  if (!state.keywordReport) return;
  const { all_keywords, frequencies, in_master, in_target, missing_in_target, not_in_master } = state.keywordReport;
  if (!all_keywords || all_keywords.length === 0) return;

  const wrap = h("div", { class: "kw-report" });

  const legend = h("div", { class: "kw-legend" }, [
    h("span", { class: "kw-legend-item" }, [h("span", { class: "kw-dot kw-dot-ok" }), " en el CV"]),
    h("span", { class: "kw-legend-item" }, [h("span", { class: "kw-dot kw-dot-missing" }), " en master, no en target"]),
    h("span", { class: "kw-legend-item" }, [h("span", { class: "kw-dot kw-dot-notmaster" }), " no está en master"]),
  ]);
  wrap.appendChild(legend);

  const list = h("div", { class: "keywords-list" });
  all_keywords.forEach((kw) => {
    const freq = frequencies[kw] || 1;
    let cls = "kw-chip";
    let title = "";
    let clickable = false;
    if (in_target[kw]) {
      cls += " kw-chip-ok";
      title = `Presente en el CV generado (aparece ${freq}x en la oferta)`;
    } else if (in_master[kw]) {
      cls += " kw-chip-missing";
      title = `Está en tu CV maestro pero no en esta selección. Aparece ${freq}x en la oferta. Clic para traer bullets.`;
      clickable = true;
    } else {
      cls += " kw-chip-notmaster";
      title = `La oferta la pide (${freq}x) pero no está en tu CV maestro — gap real`;
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

  if (missing_in_target && missing_in_target.length > 0) {
    wrap.appendChild(h("p", { class: "kw-summary" },
      `Faltan en el target: ${missing_in_target.join(", ")}. Clic en una para traer bullets del master.`));
  }
  if (not_in_master && not_in_master.length > 0) {
    wrap.appendChild(h("p", { class: "kw-summary kw-summary-gap" },
      `No tenés en el master: ${not_in_master.join(", ")}.`));
  }

  container.appendChild(wrap);
}

// ----------------------------------------------------- oportunidades

function renderOpportunities() {
  const panel = $("#opportunities-panel");
  const list = $("#opportunities-list");
  if (!panel || !list) return;

  const critical = state.keywordReport?.critical_missing || [];
  if (critical.length === 0) {
    panel.hidden = true;
    return;
  }

  panel.hidden = false;
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
}

// ----------------------------------------------------- bullet scores

function getBulletScore(bulletId) {
  if (!state.selection || !state.selection.bullet_scores) return null;
  return state.selection.bullet_scores[bulletId] || null;
}

function getJDSnippet(bulletId) {
  if (!state.selection || !state.selection.jd_snippets) return null;
  return state.selection.jd_snippets[bulletId] || null;
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
  const bar = h("div", { class: "bullet-score" }, [
    h("div", { class: "bullet-score-bar" }, [
      h("div", { class: "bullet-score-fill", style: `width:${pct}%` }),
    ]),
    h("span", { class: "bullet-score-num" }, `${pct}`),
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
  setGlobalStatus(`Bullet agregado para "${keyword}"${deltaMsg}.`, "ok");
}

function recalcKeywordReport() {
  if (!state.keywordReport || !state.targetDoc) return;
  const jd = $("#job-description").value || "";
  const { all_keywords, frequencies } = state.keywordReport;
  const targetCorpus = buildDocCorpus(state.targetDoc);

  let coveredWeight = 0;
  let totalWeight = 0;
  const newInTarget = {};
  const newMissing = [];
  const newCritical = [];

  for (const kw of all_keywords) {
    const present = targetCorpus.includes(kw.toLowerCase());
    newInTarget[kw] = present;
    const freq = frequencies[kw] || 1;
    const weight = freq;
    totalWeight += weight;
    if (present) coveredWeight += weight;
    else {
      if (state.keywordReport.in_master[kw]) newMissing.push(kw);
      if (freq >= 2 && state.keywordReport.in_master[kw]) newCritical.push(kw);
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
    class: "btn-icon danger", title: "Sacar sección",
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
      delete ctx.doc.cv.sections[name];
      if (ctx.sectionTypes) delete ctx.sectionTypes[name];
      ctx.onRerender();
    },
  }, "×");

  const regeneratable = ["experience", "projects", "skills"];
  let regenBtn = null;
  if (ctx.isTarget && regeneratable.includes(name)) {
    regenBtn = h("button", { class: "btn-icon regen", title: "Regenerar esta sección con la IA" }, "↻");
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
        setGlobalStatus(`Se regeneró "${humanizeSectionName(name)}".`, "ok");
      } catch (e) {
        setGlobalStatus("No se pudo regenerar la sección: " + e.message, "error");
      } finally {
        regenBtn.disabled = false;
        regenBtn.textContent = "↻";
      }
    });
  }

  block.appendChild(h("div", { class: "section-head" }, [
    h("div", { class: "titles" }, [
      h("h2", {}, humanizeSectionName(name)),
      h("span", { class: "eyebrow" }, name),
    ]),
    h("div", { class: "section-actions" }, [regenBtn, removeBtn]),
  ]));

  if (type === "text") block.appendChild(renderTextList(name, entries, ctx));
  else if (type === "label_details") block.appendChild(renderLabelDetailsList(name, entries, ctx));
  else block.appendChild(renderEntriesList(name, entries, ctx));

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
      class: "btn-icon danger", title: "Sacar",
      onclick: () => { entries.splice(i, 1); ctx.onRerender(); },
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
      class: "btn-icon danger", title: "Sacar",
      onclick: () => { entries.splice(i, 1); ctx.onRerender(); },
    }, "×");

    const row = h("div", { class: "entry-card" }, [
      h("div", { class: "entry-fields" }, [
        h("div", { class: "field" }, [h("label", {}, "label"), labelInput]),
        h("div", { class: "field" }, [h("label", {}, "details"), detailsInput]),
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
    fieldsWrap.appendChild(h("div", { class: "field" }, [h("label", {}, key), input]));
  });

  const moveUp = h("button", {
    class: "btn-icon", title: "Subir", disabled: index === 0 ? "disabled" : null,
    onclick: () => { [entries[index - 1], entries[index]] = [entries[index], entries[index - 1]]; ctx.onRerender(); },
  }, "↑");
  const moveDown = h("button", {
    class: "btn-icon", title: "Bajar", disabled: index === entries.length - 1 ? "disabled" : null,
    onclick: () => { [entries[index + 1], entries[index]] = [entries[index], entries[index + 1]]; ctx.onRerender(); },
  }, "↓");
  const del = h("button", {
    class: "btn-icon danger", title: "Sacar entrada",
    onclick: async () => {
      const confirmed = await confirmAction({
        title: "Eliminar entrada",
        message: "¿Querés eliminar esta entrada?",
        confirmLabel: "Eliminar",
      });
      if (!confirmed) return;
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
        reasonEl.addEventListener("mouseenter", () => showJDSnippet(snippet, reasonEl));
        reasonEl.addEventListener("mouseleave", hideJDSnippet);
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
      class: "btn-icon", title: "Subir", disabled: i === 0 ? "disabled" : null,
      onclick: () => {
        [entry.highlights[i - 1], entry.highlights[i]] = [entry.highlights[i], entry.highlights[i - 1]];
        ctx.onRerender();
      },
    }, "↑");
    const moveDown = h("button", {
      class: "btn-icon", title: "Bajar", disabled: i === entry.highlights.length - 1 ? "disabled" : null,
      onclick: () => {
        [entry.highlights[i + 1], entry.highlights[i]] = [entry.highlights[i], entry.highlights[i + 1]];
        ctx.onRerender();
      },
    }, "↓");
    const del = h("button", {
      class: "btn-icon danger", title: "Sacar bullet",
      onclick: () => { entry.highlights.splice(i, 1); ctx.onRerender(); },
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
        scoreEl.addEventListener("mouseenter", () => showJDSnippet(snippet, scoreEl));
        scoreEl.addEventListener("mouseleave", hideJDSnippet);
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
        class: "btn-icon", title: "Agregar",
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
        class: "btn-icon danger",
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
  renderHeader($("#master-header"), state.masterDoc, null);
  renderSectionNav($("#master-nav"), $("#master-sections"), state.masterDoc.cv.sections);
  const ctx = {
    doc: state.masterDoc,
    isTarget: false,
    sectionTypes: state.masterSectionTypes,
    onRerender: drawMasterView,
  };
  renderSections($("#master-sections"), ctx);
}

$("#add-section-master").addEventListener("click", async () => {
  const result = await promptAddSection();
  if (!result) return;
  if (state.masterDoc.cv.sections[result.name]) {
    setStatus($("#master-status"), "Ya existe una sección con ese nombre.", "error");
    return;
  }
  state.masterDoc.cv.sections[result.name] = result.type === "entries" ? [blankEntryFor(result.name, "entries")] : [];
  state.masterSectionTypes[result.name] = result.type;
  drawMasterView();
});

$("#save-master").addEventListener("click", async () => {
  const statusEl = $("#master-status");
  setStatus(statusEl, "Guardando…");
  const btn = $("#save-master");
  btn.disabled = true;
  try {
    await api("/api/master-cv", { method: "POST", body: JSON.stringify(state.masterDoc) });
    setStatus(statusEl, "Guardado.", "ok");
    setGlobalStatus("CV maestro guardado.", "ok");
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
    setStatus(statusEl, "Listo. Revisá la selección abajo.", "ok");
    setGlobalStatus("CV generado. Revisá las secciones y luego exportá PDF.", "ok");
    $("#apply-result").hidden = false;
    $("#download-link").hidden = true;
    drawTargetView();
  } catch (e) {
    setStatus(statusEl, e.message, "error");
    setGlobalStatus("No se pudo generar el CV: " + e.message, "error");
  } finally {
    btn.disabled = false;
  }
});

function drawTargetView() {
  renderHeader($("#target-header"), state.targetDoc, null);

  const kwSection = state.targetDoc.cv.sections.keywords;
  const kwList = $("#keywords-list");
  kwList.innerHTML = "";
  if (kwSection && kwSection[0]) {
    const kws = kwSection[0].replace(/^Palabras clave:\s*/, "").split(",").map((s) => s.trim()).filter(Boolean);
    kws.forEach((kw) => kwList.appendChild(h("span", { class: "kw-chip" }, kw)));
  }

  renderFitScore();
  renderKeywordReport();
  renderOpportunities();

  const ctx = {
    doc: state.targetDoc,
    isTarget: true,
    sectionTypes: state.targetSectionTypes,
    masterDoc: state.masterDocSnapshot,
    selection: state.selection,
    onRerender: drawTargetView,
  };
  renderSectionNav($("#target-nav"), $("#target-sections"), state.targetDoc.cv.sections);
  renderSections($("#target-sections"), ctx);
  renderAtsChecklist();
}

$("#ats-keywords").addEventListener("input", renderAtsChecklist);

$("#add-section-target").addEventListener("click", async () => {
  const result = await promptAddSection();
  if (!result) return;
  if (state.targetDoc.cv.sections[result.name]) {
    setStatus($("#render-status"), "Ya existe una sección con ese nombre.", "error");
    return;
  }
  state.targetDoc.cv.sections[result.name] = result.type === "entries" ? [blankEntryFor(result.name, "entries")] : [];
  state.targetSectionTypes[result.name] = result.type;
  drawTargetView();
});

$("#render-btn").addEventListener("click", async () => {
  const statusEl = $("#render-status");
  setStatus(statusEl, "Compilando PDF…");
  $("#download-link").hidden = true;
  const btn = $("#render-btn");
  btn.disabled = true;
  try {
    await api("/api/render", { method: "POST", body: JSON.stringify(state.targetDoc) });
    setStatus(statusEl, "PDF listo.", "ok");
    $("#download-link").hidden = false;
    $("#download-link").href = "/api/download-pdf?t=" + Date.now();
    setGlobalStatus("PDF listo para descargar.", "ok");
  } catch (e) {
    setStatus(statusEl, e.message, "error");
    setGlobalStatus("Error al generar PDF: " + e.message, "error");
  } finally {
    btn.disabled = false;
  }
});

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
    setStatus(statusEl, "Guardado.", "ok");
    setGlobalStatus("Configuración guardada.", "ok");
  } catch (e) {
    setStatus(statusEl, e.message, "error");
    setGlobalStatus("No se pudo guardar la configuración: " + e.message, "error");
  } finally {
    btn.disabled = false;
  }
});

// ------------------------------------------------------------- tabs/init

$("#tabs").addEventListener("click", (e) => {
  const btn = e.target.closest(".tab");
  if (!btn) return;
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("is-active", t === btn));
  document.querySelectorAll(".view").forEach((v) => v.classList.toggle("is-active", v.id === "view-" + btn.dataset.view));
});

(async function init() {
  const [master, settings] = await Promise.allSettled([loadMasterView(), loadSettingsView()]);
  const failures = [master, settings].filter((x) => x.status === "rejected");
  if (failures.length > 0) {
    const detail = failures.map((f) => f.reason && f.reason.message ? f.reason.message : String(f.reason)).join(" | ");
    setGlobalStatus("No se pudo cargar toda la app: " + detail, "error");
    console.error(detail);
  }
})();