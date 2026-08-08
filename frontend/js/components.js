//módulo: components — renderers compartidos master/target (ctx)

import { api } from "./api.js";
import { $, autoResize, h } from "./dom.js";
import { blankEntryFor, defaultSectionType, detectSectionType, fieldLabel } from "./labels.js";
import { confirmAction, openModal, showMessageModal } from "./modals.js";
import { hideJDSnippet, setGlobalStatus, showJDSnippet, toast } from "./notify.js";
import { rememberUndo, state } from "./state.js";
import { getBulletScore, getJDSnippet, renderBulletScore, renderEntryHeatBorder } from "./widgets.js";

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


export { getMatchReason, humanizeSectionName, renderEntriesList, renderEntryCard, renderHeader, renderHighlights, renderLabelDetailsList, renderPullback, renderSectionBlock, renderSectionNav, renderSections, renderTextList };
