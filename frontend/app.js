"use strict";

/* =====================================================================
   cv-adapter — frontend
   Vanilla JS, sin build step. Un único modelo de datos por vista
   (masterDoc / targetDoc) que se muta in-place; las acciones estructurales
   (agregar/sacar/reordenar) vuelven a dibujar la sección afectada, pero
   escribir texto en un input NUNCA dispara un re-render (se perdería el
   foco/cursor) — solo actualiza el dato en memoria.
   ===================================================================== */

const state = {
  masterDoc: null,
  targetDoc: null,
  selection: null,
  config: null,
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

// -------------------------------------------------------------- modal

function openModal(builder) {
  return new Promise((resolve) => {
    const overlay = $("#modal-overlay");
    const box = $("#modal-box");
    box.innerHTML = "";
    let settled = false;
    const close = (value) => {
      if (settled) return;
      settled = true;
      overlay.hidden = true;
      resolve(value);
    };
    box.appendChild(builder(close));
    overlay.hidden = false;
    overlay.onclick = (e) => { if (e.target === overlay) close(null); };
  });
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

function detectSectionType(entries) {
  if (!entries || entries.length === 0) return null;
  const first = entries[0];
  if (typeof first === "string") return "text";
  if (first && typeof first === "object" && "highlights" in first) return "entries";
  return "label_details";
}

function blankEntryFor(sectionName, type) {
  if (type === "text") return "";
  if (type === "label_details") return { label: "", details: "" };
  // "entries"
  if (sectionName === "experience") {
    return { company: "", position: "", location: "", start_date: "", end_date: "", highlights: [] };
  }
  if (sectionName === "education") {
    return { institution: "", area: "", degree: "", start_date: "", end_date: "", highlights: [] };
  }
  return { name: "", date: "", highlights: [] }; // projects u otras secciones custom
}

// ------------------------------------------------------------ renderer

/**
 * Dibuja el documento completo (todas las secciones) dentro de `container`.
 * ctx = { doc, isTarget, masterDoc, selection, onRerender }
 */
function renderSections(container, ctx) {
  container.innerHTML = "";
  const sections = ctx.doc.cv.sections || {};
  for (const name of Object.keys(sections)) {
    container.appendChild(renderSectionBlock(name, sections[name], ctx));
  }
}

function renderSectionBlock(name, entries, ctx) {
  const type = detectSectionType(entries) || ctx.sectionTypes?.[name] || "entries";
  const block = h("div", { class: "section-block", "data-section": name });

  const removeBtn = h("button", {
    class: "btn-icon danger", title: "Sacar sección",
    onclick: () => {
      if (!confirm(`¿Sacar la sección "${name}" del ${ctx.isTarget ? "CV generado" : "CV maestro"}?`)) return;
      delete ctx.doc.cv.sections[name];
      ctx.onRerender();
    },
  }, "×");

  const regeneratable = ["experience", "projects", "skills"];
  let regenBtn = null;
  if (ctx.isTarget && regeneratable.includes(name)) {
    regenBtn = h("button", { class: "btn-icon regen", title: "Regenerar esta sección con la IA" }, "↻");
    regenBtn.addEventListener("click", async () => {
      const jd = $("#job-description").value;
      if (!jd.trim()) { alert("Necesito el texto de la oferta (pestaña de arriba) para regenerar."); return; }
      regenBtn.disabled = true;
      regenBtn.textContent = "…";
      try {
        const result = await api("/api/regenerate-section", {
          method: "POST",
          body: JSON.stringify({ job_description: jd, section_name: name }),
        });
        ctx.doc.cv.sections[name] = result.entries;
        state.selection = state.selection || {};
        Object.assign(state.selection, result.selection);
        ctx.onRerender();
      } catch (e) {
        alert("No se pudo regenerar la sección: " + e.message);
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

// -- tipo "text": lista de strings (summary, keywords, etc.) -----------

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

  return wrap;
}

// -- tipo "label_details": skills, languages ----------------------------

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

// -- tipo "entries": experience, projects, education, custom -----------

function renderEntriesList(sectionName, entries, ctx) {
  const wrap = h("div", {});

  entries.forEach((entry, i) => {
    wrap.appendChild(renderEntryCard(sectionName, entries, entry, i, ctx));
  });

  wrap.appendChild(h("button", {
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
    onclick: () => { entries.splice(index, 1); ctx.onRerender(); },
  }, "×");

  const card = h("div", { class: "entry-card" });
  card.appendChild(h("div", { class: "entry-top-row" }, [
    fieldsWrap,
    h("div", { class: "row-controls" }, [moveUp, moveDown, del]),
  ]));

  const matchReason = ctx.isTarget ? getMatchReason(entry, ctx.selection) : null;
  if (matchReason) card.appendChild(h("p", { class: "match-reason" }, "por qué se eligió: " + matchReason));

  if ("highlights" in entry) {
    card.appendChild(renderHighlights(entry, ctx));
  }

  if (ctx.isTarget && entry._src_section && entry._src_index !== undefined) {
    const pb = renderPullback(entry, ctx);
    if (pb) card.appendChild(pb);
  }

  return card;
}

function renderHighlights(entry, ctx) {
  const wrap = h("div", { class: "highlights" });
  entry.highlights.forEach((text, i) => {
    const ta = h("textarea", { class: "highlight-text" });
    ta.value = text;
    setTimeout(() => autoResize(ta), 0);
    ta.addEventListener("input", () => { entry.highlights[i] = ta.value; autoResize(ta); });

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

    wrap.appendChild(h("div", { class: "highlight-row" }, [
      h("span", { class: "bullet-mark" }, "—"),
      ta,
      h("div", { class: "row-controls" }, [moveUp, moveDown, del]),
    ]));
  });

  wrap.appendChild(h("button", {
    class: "btn btn-ghost",
    onclick: () => { entry.highlights.push(""); ctx.onRerender(); },
  }, "+ Agregar bullet"));

  return wrap;
}

// -- "traer bullet del master" para entradas del CV generado ------------

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

  const details = h("details", { class: "pullback" });
  details.appendChild(h("summary", {}, `+ traer bullet del master (${missing.length} sin usar)`));
  missing.forEach((text) => {
    details.appendChild(h("div", { class: "pullback-item" }, [
      h("p", {}, text),
      h("button", {
        class: "btn-icon", title: "Agregar",
        onclick: () => { entry.highlights.push(text); ctx.onRerender(); },
      }, "+"),
    ]));
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
      netInput.addEventListener("input", () => (s.network = netInput.value));
      const userInput = h("input", { type: "text", value: s.username || "", placeholder: "usuario" });
      userInput.addEventListener("input", () => (s.username = userInput.value));
      const del = h("button", {
        class: "btn-icon danger",
        onclick: () => { socials.splice(i, 1); drawSocials(); },
      }, "×");
      listEl.appendChild(h("div", { class: "social-row" }, [netInput, userInput, del]));
    });
  }
  drawSocials();
  socialWrap.appendChild(listEl);
  socialWrap.appendChild(h("button", {
    class: "btn btn-ghost",
    onclick: () => { socials.push({ network: "", username: "" }); drawSocials(); },
  }, "+ Agregar red"));
  container.appendChild(socialWrap);
}

// --------------------------------------------------------- vista: master

async function loadMasterView() {
  state.masterDoc = await api("/api/master-cv");
  drawMasterView();
}

function drawMasterView() {
  renderHeader($("#master-header"), state.masterDoc, null);
  const ctx = {
    doc: state.masterDoc,
    isTarget: false,
    onRerender: drawMasterView,
  };
  renderSections($("#master-sections"), ctx);
}

$("#add-section-master").addEventListener("click", async () => {
  const result = await promptAddSection();
  if (!result) return;
  if (state.masterDoc.cv.sections[result.name]) { alert("Ya existe una sección con ese nombre."); return; }
  state.masterDoc.cv.sections[result.name] = result.type === "entries" ? [blankEntryFor(result.name, "entries")] : [];
  drawMasterView();
});

$("#save-master").addEventListener("click", async () => {
  const statusEl = $("#master-status");
  setStatus(statusEl, "Guardando…");
  try {
    await api("/api/master-cv", { method: "POST", body: JSON.stringify(state.masterDoc) });
    setStatus(statusEl, "Guardado.", "ok");
  } catch (e) {
    setStatus(statusEl, e.message, "error");
  }
});

// ---------------------------------------------------------- vista: apply

$("#generate-btn").addEventListener("click", async () => {
  const statusEl = $("#generate-status");
  const jd = $("#job-description").value;
  if (!jd.trim()) { setStatus(statusEl, "Pegá la oferta laboral primero.", "error"); return; }
  if (jd.trim().length < 40) {
    const proceed = confirm(
      "La oferta parece muy corta. Con poco texto el modelo tiene menos para basarse y puede " +
      "traer contenido genérico. ¿Generar igual?"
    );
    if (!proceed) return;
  }

  const manualKeywords = ($("#ats-keywords").value || "").split(",").map((s) => s.trim()).filter(Boolean);

  const btn = $("#generate-btn");
  btn.disabled = true;
  setStatus(statusEl, "Consultando al modelo local (puede tardar según tu hardware)…");
  try {
    const result = await api("/api/generate", {
      method: "POST",
      body: JSON.stringify({ job_description: jd, manual_keywords: manualKeywords }),
    });
    state.targetDoc = { cv: result.target_cv.cv, design: result.target_cv.design };
    state.selection = result.selection;
    state.masterDocSnapshot = result.master_cv;
    setStatus(statusEl, "Listo. Revisá la selección abajo.", "ok");
    $("#apply-result").hidden = false;
    $("#download-link").hidden = true;
    drawTargetView();
  } catch (e) {
    setStatus(statusEl, e.message, "error");
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

  const ctx = {
    doc: state.targetDoc,
    isTarget: true,
    masterDoc: state.masterDocSnapshot,
    selection: state.selection,
    onRerender: drawTargetView,
  };
  renderSections($("#target-sections"), ctx);
  renderAtsChecklist();
}

$("#ats-keywords").addEventListener("input", renderAtsChecklist);

$("#add-section-target").addEventListener("click", async () => {
  const result = await promptAddSection();
  if (!result) return;
  if (state.targetDoc.cv.sections[result.name]) { alert("Ya existe una sección con ese nombre."); return; }
  state.targetDoc.cv.sections[result.name] = result.type === "entries" ? [blankEntryFor(result.name, "entries")] : [];
  drawTargetView();
});

$("#render-btn").addEventListener("click", async () => {
  const statusEl = $("#render-status");
  setStatus(statusEl, "Compilando PDF…");
  $("#download-link").hidden = true;
  try {
    await api("/api/render", { method: "POST", body: JSON.stringify(state.targetDoc) });
    setStatus(statusEl, "PDF listo.", "ok");
    $("#download-link").hidden = false;
    $("#download-link").href = "/api/download-pdf?t=" + Date.now();
  } catch (e) {
    setStatus(statusEl, e.message, "error");
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

async function loadSettingsView() {
  state.config = await api("/api/config");
  drawSettingsView();
}

function drawSettingsView() {
  const form = $("#settings-form");
  form.innerHTML = "";
  SETTINGS_FIELDS.forEach((f) => {
    const input = h("input", { type: f.type, value: state.config[f.key], min: f.type === "number" ? 1 : null });
    input.addEventListener("input", () => {
      state.config[f.key] = f.type === "number" ? Number(input.value) : input.value;
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
  try {
    state.config = await api("/api/config", { method: "POST", body: JSON.stringify(state.config) });
    setStatus(statusEl, "Guardado.", "ok");
  } catch (e) {
    setStatus(statusEl, e.message, "error");
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
  try {
    await Promise.all([loadMasterView(), loadSettingsView()]);
  } catch (e) {
    console.error(e);
  }
})();