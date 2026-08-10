//módulo: widgets — widgets de keywords: report, oportunidades, excluidos, pullback, recalc

import { drawTargetView } from "./views/apply.js";
import { $, h } from "./dom.js";
import { openModal, showMessageModal } from "./modals.js";
import { toast } from "./notify.js";
import { state } from "./state.js";

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

// Matching con límites de palabra + variantes sinónimas, espejo del
// keyword_in_text del backend: "js" NO matchea "jsp", pero sí "node.js".
// Las variantes vienen del keyword_report (fuente única: SYNONYMS en Python).
function keywordPresentIn(corpus, kw, variants) {
  const list = (variants && variants[kw]) || [String(kw).toLowerCase()];
  return list.some((v) => {
    const esc = v.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    return new RegExp(`(^|[^a-z0-9])${esc}([^a-z0-9]|$)`).test(corpus);
  });
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
    const freq = frequencies[kw] || 1;
    const inT = in_target[kw] !== undefined ? in_target[kw] : keywordPresentIn(targetCorpus, kw, state.keywordReport.keyword_variants);
    const inM = in_master[kw] !== undefined ? in_master[kw] : keywordPresentIn(masterCorpus, kw, state.keywordReport.keyword_variants);
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
          const bScoreLabel = bScore != null ? `${Math.round(bScore * 100)}%` : "";

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
  const report = state.keywordReport || {};
  const locs = (report.locations && report.locations[keyword]) || [];

  if (locs.length === 0) {
    // El chip dijo que está en el master, pero no hay ubicación: el snapshot
    // quedó viejo (master editado después de generar). Mensaje honesto en
    // vez de un falso "no existe".
    await showMessageModal(
      "Sin coincidencias",
      `No se encontró "${keyword}" en el CV maestro actual. Si editaste el master después de generar, regenerá la selección para actualizar.`
    );
    return;
  }

  const masterSections = state.masterDocSnapshot.cv?.sections || {};
  const bulletMatches = [];
  const nonBullet = [];

  locs.forEach((loc) => {
    if (loc.bullet_idx !== null && loc.bullet_idx !== undefined && loc.field === "highlights") {
      const bulletId = `${loc.section}_${loc.entry_idx}_bullet_${loc.bullet_idx}`;
      const score = getBulletScore(bulletId) || 0;
      const entry = masterSections[loc.section]?.[loc.entry_idx] || null;
      bulletMatches.push({
        sectionName: loc.section,
        entryIdx: loc.entry_idx,
        bulletIdx: loc.bullet_idx,
        text: loc.text,
        entry,
        score,
      });
    } else {
      nonBullet.push(loc);
    }
  });

  // Ordenar por relevancia (score descendente)
  bulletMatches.sort((a, b) => b.score - a.score);

  const chosen = await openModal((close) => {
    const hasBullets = bulletMatches.length > 0;
    const body = [];

    if (hasBullets) {
      const list = h("div", { class: "pullback-list" });
      bulletMatches.forEach((m) => {
        const label = m.entry
          ? (m.entry.company || m.entry.name || m.entry.institution || `Entrada ${m.entryIdx}`)
          : `Entrada ${m.entryIdx}`;
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
      body.push(list);
    }

    if (nonBullet.length > 0) {
      if (hasBullets) body.push(h("h4", {}, "También aparece (sin bullets)"));
      const refs = h("div", { class: "pullback-list" });
      nonBullet.forEach((loc) => {
        const where = loc.field ? `${loc.section} → ${loc.field}` : loc.section;
        refs.appendChild(h("div", { class: "pullback-item" }, [
          h("div", { class: "pullback-info" }, [
            h("div", { class: "pullback-header" }, [h("strong", {}, where)]),
            h("p", { class: "pullback-text" }, loc.text),
          ]),
        ]));
      });
      body.push(refs);
    }

    return h("div", {}, [
      h("h3", {}, hasBullets ? `Bullets con "${keyword}"` : `Dónde aparece "${keyword}"`),
      h("p", { class: "hint" }, hasBullets
        ? "Ordenados por relevancia para esta oferta:"
        : "Está en tu CV maestro, pero fuera de los bullets: no hay nada que traer desde acá."),
      ...body,
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
    const present = keywordPresentIn(targetCorpus, kw, state.keywordReport.keyword_variants);
    newInTarget[kw] = present;
    const freq = frequencies[kw] || 1;
    const inM = in_master[kw] !== undefined ? in_master[kw] : keywordPresentIn(masterCorpus, kw, state.keywordReport.keyword_variants);
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


// --------------------------------------------------- estimación de página (P1.4)

// Aviso NO bloqueante: la estimación del backend (merge.estimate_page_overflow)
// es una heurística a ojo; el layout real lo decide Typst según el tema.
function renderPageEstimate() {
  const el = $("#page-estimate-banner");
  if (!el) return;
  const est = state.pageEstimate;
  if (!est) {
    el.hidden = true;
    el.textContent = "";
    return;
  }
  const budget = est.page_budget_lines || 0;
  const used = est.estimated_lines || 0;
  el.classList.toggle("overflow", !!est.overflow);
  el.hidden = false;
  if (est.overflow) {
    const extra = est.overflow_lines || 0;
    el.textContent = `Aviso: la estimación da ${extra} línea(s) de más para una página (${used} de ${budget} presupuestadas). Es solo una estimación: el render final lo decide Typst.`;
  } else {
    el.textContent = `Estimación: ${used} líneas de ${budget} — alcanza para una página.`;
  }
}


export { addBulletToTarget, addEntryToTarget, buildDocCorpus, countExcluded, effectiveKeywordList, getBulletScore, getEntryScore, getJDSnippet, getManualKeywords, getScoreMode, handleMissingKeywordClick, recalcKeywordReport, refreshKeywordWidgets, renderBulletScore, renderEntryHeatBorder, renderExcludedPanel, renderKeywordReport, renderOpportunities, renderPageEstimate, renderResultSummary, updateNotIncludedPanel };
