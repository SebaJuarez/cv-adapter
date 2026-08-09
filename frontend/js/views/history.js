//módulo: history — vista de historial: corridas registradas, seguimiento de
// la aplicación, keywords que faltan en el CV maestro y previsualización
// de la oferta / CV sin descargar (modal con pestañas).

import { api } from "../api.js";
import { $, h } from "../dom.js";
import { openModal } from "../modals.js";
import { setGlobalStatus, toast } from "../notify.js";

const STATUS_LABELS = {
  pendiente: "Pendiente",
  aplicado: "Aplicado",
  entrevista: "En entrevista",
  oferta: "Oferta",
  rechazado: "Rechazado",
};

const STATUS_ORDER = ["pendiente", "aplicado", "entrevista", "oferta", "rechazado"];

const PAGE_SIZE = 25;

const ATS_TOOLTIP =
  "Impacto ATS: qué porcentaje del peso de las keywords de la oferta cubre tu CV generado (ponderado por cuántas veces aparece cada una).";

function formatDate(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleDateString("es", { day: "2-digit", month: "2-digit", year: "numeric" });
}

function formatAppliedAt(dateStr) {
  return dateStr || "—";
}

// ------------------------------------------------------------ estado local

let filters = { q: "", status: "" };
let page = { runs: [], total: 0, offset: 0, statusCounts: {}, loaded: false };
let loading = false;

// ---------------------------------------------------------- carga inicial

async function loadHistoryView() {
  const [runsRes, statsRes] = await Promise.allSettled([
    fetchPage(true),
    api("/api/history/stats/keywords"),
  ]);
  if (runsRes.status === "rejected") return; // fetchPage ya mostró el error
  renderKeywordStats(statsRes.status === "fulfilled" ? statsRes.value.keywords : []);
}

async function reload() {
  try {
    const { keywords } = await api("/api/history/stats/keywords");
    renderKeywordStats(keywords || []);
  } catch (e) {
    setGlobalStatus("No se pudieron cargar las keywords: " + e.message, "error");
  }
  await fetchPage(true);
}

async function fetchPage(reset) {
  if (loading) return;
  loading = true;
  const offset = reset ? 0 : page.offset + PAGE_SIZE;
  const params = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(offset) });
  if (filters.q) params.set("q", filters.q);
  if (filters.status) params.set("status", filters.status);
  try {
    const body = await api("/api/history/runs?" + params.toString());
    page = {
      runs: reset ? body.runs : page.runs.concat(body.runs),
      total: body.total,
      offset,
      statusCounts: body.status_counts || {},
      loaded: true,
    };
    renderRuns();
    renderStatusChips();
  } catch (e) {
    setGlobalStatus("No se pudo cargar el historial: " + e.message, "error");
    renderListError(e.message);
  } finally {
    loading = false;
  }
}

// --------------------------------------------------------- tabla de runs

function renderRuns() {
  const list = $("#history-list");
  const loadMoreBtn = $("#history-load-more");
  list.innerHTML = "";

  if (!page.loaded) return;

  if (!page.runs.length && !filters.q && !filters.status) {
    list.appendChild(h("p", { class: "history-empty" },
      "Todavía no hay corridas registradas. Generá un CV para una oferta y aparece acá automáticamente."));
    loadMoreBtn.hidden = true;
    updateTotal();
    return;
  }
  if (!page.runs.length) {
    list.appendChild(h("div", { class: "history-empty" }, [
      h("p", { style: "margin:0 0 0.6rem" }, "No hay corridas que coincidan con los filtros."),
      h("button", { class: "btn btn-sm btn-ghost", onclick: clearFilters }, "Limpiar filtros"),
    ]));
    loadMoreBtn.hidden = true;
    updateTotal();
    return;
  }

  const table = h("table", { class: "history-table" }, [
    h("thead", {}, h("tr", {}, [
      h("th", { scope: "col" }, "Fecha"),
      h("th", { scope: "col" }, "Oferta"),
      h("th", { scope: "col", title: ATS_TOOLTIP }, "ATS"),
      h("th", { scope: "col" }, "Faltantes"),
      h("th", { scope: "col" }, "Estado"),
      h("th", { scope: "col" }, "Acciones"),
    ])),
    h("tbody", {}, page.runs.map(buildRow)),
  ]);
  list.appendChild(table);
  loadMoreBtn.hidden = page.runs.length >= page.total;
  updateTotal();
}

function renderListError(message) {
  const list = $("#history-list");
  list.innerHTML = "";
  list.appendChild(h("div", { class: "history-empty" }, [
    h("p", { style: "margin:0 0 0.6rem" }, "No se pudo cargar la lista de corridas: " + message),
    h("button", { class: "btn btn-sm btn-ghost", onclick: () => fetchPage(true) }, "Reintentar"),
  ]));
  $("#history-load-more").hidden = true;
}

function updateTotal() {
  const el = $("#history-total");
  if (!page.loaded || page.total === 0) {
    el.hidden = true;
    return;
  }
  el.textContent = page.total === 1 ? "1 corrida" : `${page.total} corridas`;
  el.hidden = false;
}

function clearFilters() {
  filters.q = "";
  filters.status = "";
  $("#history-search").value = "";
  renderStatusChips();
  fetchPage(true);
}

function buildRow(run) {
  const title = h("span", { class: "history-offer-title" }, run.offer_title || "—");
  const titleCell = [title];
  if (run.offer_link) {
    titleCell.push(h("a", {
      class: "history-offer-link",
      href: run.offer_link,
      rel: "noopener noreferrer",
    }, "Ver oferta"));
  }

  const missing = [];
  const notInMaster = (run.not_in_master || []).length;
  const missingInTarget = (run.missing_in_target || []).length;
  if (notInMaster > 0) {
    missing.push(h("button", {
      class: "history-missing notmaster",
      title: "No están en tu CV maestro. Ver detalle.",
      onclick: () => openDetailModal(run, "analysis"),
    }, `${notInMaster} sin master`));
  }
  if (missingInTarget > 0) {
    missing.push(h("button", {
      class: "history-missing missing",
      title: "Están en el master pero no entraron al CV generado. Ver detalle.",
      onclick: () => openDetailModal(run, "analysis"),
    }, `${missingInTarget} recortadas`));
  }

  const app = run.application || {};
  const statusSelect = h("select", {
    class: "history-status-select",
    "aria-label": "Estado de la aplicación",
    onchange: async (e) => {
      try {
        await api(`/api/history/runs/${run.run_id}`, {
          method: "PATCH",
          body: JSON.stringify({ application: { status: e.target.value } }),
        });
        toast("Estado actualizado.");
        reload();
      } catch (err) {
        setGlobalStatus("No se pudo actualizar el estado: " + err.message, "error");
        reload();
      }
    },
  }, STATUS_ORDER.map((s) => h("option", { value: s, selected: s === app.status ? "selected" : null },
    STATUS_LABELS[s])));

  const statusCell = [statusSelect, h("span", { class: "history-applied" },
    "Aplicado: " + formatAppliedAt(app.applied_at))];

  const actions = [];
  actions.push(h("button", {
    class: "btn btn-sm btn-ghost",
    onclick: () => openDetailModal(run),
  }, "Ver"));
  actions.push(h("button", {
    class: "btn btn-sm btn-ghost",
    onclick: () => openEditModal(run),
  }, "Editar"));
  if (run.pdf_path) {
    actions.push(h("a", {
      class: "btn btn-sm btn-ghost",
      href: pdfUrl(run),
      onclick: (e) => downloadPdf(run, e),
    }, "PDF"));
  }
  actions.push(h("button", {
    class: "btn btn-sm btn-ghost btn-danger-text",
    onclick: () => confirmDelete(run),
  }, "Borrar"));

  return h("tr", {}, [
    h("td", { class: "history-date" }, formatDate(run.created_at)),
    h("td", {}, titleCell),
    h("td", { class: "history-num", title: ATS_TOOLTIP }, String(run.ats_score)),
    h("td", { class: "history-missing-cell" }, missing),
    h("td", { class: "history-status-cell" }, statusCell),
    h("td", {}, h("div", { class: "history-actions" }, actions)),
  ]);
}

// ------------------------------------------------------------- PDF/borrado

function pdfUrl(run) {
  return "/api/download-pdf?path=" + encodeURIComponent(run.pdf_path);
}

async function pdfExists(run) {
  try {
    const res = await fetch(pdfUrl(run), { method: "HEAD" });
    return res.ok;
  } catch {
    return false;
  }
}

async function downloadPdf(run, e) {
  e.preventDefault();
  if (await pdfExists(run)) {
    window.location.href = pdfUrl(run);
    return;
  }
  toast("PDF no encontrado en disco (fue movido o borrado).", "error");
}

function confirmDelete(run) {
  return openModal((close) => {
    const filesBox = h("input", { type: "checkbox", id: "delete-files-input" });
    const doDelete = async () => {
      try {
        const q = filesBox.checked ? "?delete_files=1" : "";
        await api(`/api/history/runs/${run.run_id}${q}`, { method: "DELETE" });
        close(true);
        toast(filesBox.checked ? "Corrida y archivos borrados." : "Corrida borrada.");
        reload();
      } catch (e) {
        setGlobalStatus("No se pudo borrar la corrida: " + e.message, "error");
      }
    };
    return h("div", {}, [
      h("h3", {}, "Borrar corrida"),
      h("p", {}, `¿Borrar la corrida "${run.offer_title}"? Se pierden el registro y su seguimiento de aplicación.`),
      h("label", { class: "history-delete-files" }, [
        filesBox,
        h("span", {}, "Borrar también el PDF y el CV guardado en disco"),
      ]),
      h("div", { class: "modal-actions" }, [
        h("button", { class: "btn btn-ghost", onclick: () => close(false) }, "Cancelar"),
        h("button", { class: "btn btn-primary", onclick: doDelete }, "Borrar"),
      ]),
    ]);
  });
}

// ------------------------------------------------------- modal de edición

function openEditModal(run) {
  openModal((close) => {
    const titleInput = h("input", { type: "text", value: run.offer_title || "" });
    const linkInput = h("input", { type: "text", value: run.offer_link || "", placeholder: "https://…" });
    const app = run.application || {};
    const statusSelect = h("select", {},
      STATUS_ORDER.map((s) => h("option", { value: s, selected: s === app.status ? "selected" : null },
        STATUS_LABELS[s])));
    const appliedAtInput = h("input", { type: "date", value: app.applied_at || "" });
    const notesInput = h("textarea", { rows: "3", placeholder: "Notas: canal, contacto, fecha de entrevista…" },
      app.notes || "");

    const save = async () => {
      try {
        await api(`/api/history/runs/${run.run_id}`, {
          method: "PATCH",
          body: JSON.stringify({
            offer_title: titleInput.value.trim() || null,
            offer_link: linkInput.value.trim() || null,
            application: {
              status: statusSelect.value,
              applied_at: appliedAtInput.value || null,
              notes: notesInput.value,
            },
          }),
        });
        close(true);
        toast("Corrida actualizada.");
        reload();
      } catch (e) {
        setGlobalStatus("No se pudo guardar: " + e.message, "error");
      }
    };

    return h("div", {}, [
      h("h3", {}, "Editar corrida"),
      h("div", { class: "field" }, [
        h("label", {}, "Título de la oferta"),
        titleInput,
      ]),
      h("div", { class: "field" }, [
        h("label", {}, "Link a la oferta"),
        linkInput,
      ]),
      h("div", { class: "field" }, [
        h("label", {}, "Estado de la aplicación"),
        statusSelect,
      ]),
      h("div", { class: "field" }, [
        h("label", {}, "Fecha de aplicación"),
        appliedAtInput,
      ]),
      h("div", { class: "field" }, [
        h("label", {}, "Notas"),
        notesInput,
      ]),
      h("div", { class: "modal-actions" }, [
        h("button", { class: "btn btn-ghost", onclick: () => close(false) }, "Cancelar"),
        h("button", { class: "btn btn-primary", onclick: save }, "Guardar"),
      ]),
    ]);
  });
}

// ------------------------------------------- modal de detalle (pestañas)

function openDetailModal(run, initialTab = "jd") {
  openModal((close) => {
    const tabs = [
      { id: "jd", label: "Oferta" },
      { id: "cv", label: "CV" },
      { id: "analysis", label: "Análisis" },
    ];
    const panelHost = h("div", { class: "detail-panels" });
    const tabRow = h("div", { class: "detail-tabs", role: "tablist", "aria-label": "Detalle de la corrida" },
      tabs.map((t) => h("button", {
        class: "detail-tab",
        role: "tab",
        "aria-selected": t.id === initialTab ? "true" : "false",
        "aria-controls": "detail-panel-" + t.id,
        onclick: () => showTab(t.id),
      }, t.label)));

    const showTab = (id) => {
      tabRow.querySelectorAll(".detail-tab").forEach((b) => {
        const active = b.getAttribute("aria-controls") === "detail-panel-" + id;
        b.classList.toggle("is-active", active);
        b.setAttribute("aria-selected", active ? "true" : "false");
      });
      panelHost.innerHTML = "";
      panelHost.appendChild(buildPanel(id));
    };

    const buildPanel = (id) => {
      const panel = h("div", { class: "detail-panel", role: "tabpanel", id: "detail-panel-" + id });
      if (id === "jd") fillJdPanel(panel);
      if (id === "cv") fillCvPanel(panel);
      if (id === "analysis") fillAnalysisPanel(panel);
      return panel;
    };

    const fillJdPanel = async (panel) => {
      let runDetail = run;
      if (run.job_description === undefined) {
        try {
          const res = await api(`/api/history/runs/${run.run_id}`);
          runDetail = res.run;
        } catch {
          // sin detalle: queda el estado "no disponible"
        }
      }
      if (!runDetail.job_description) {
        panel.appendChild(h("p", { class: "history-empty" },
          "No hay texto de la oferta guardado para esta corrida (las corridas anteriores a esta versión no lo incluyen)."));
        return;
      }
      panel.appendChild(h("pre", { class: "detail-pre" }, runDetail.job_description));
    };

    const fillCvPanel = async (panel) => {
      panel.appendChild(h("p", { class: "detail-loading" }, "Cargando vista previa…"));
      if (run.pdf_path && await pdfExists(run)) {
        panel.innerHTML = "";
        panel.appendChild(h("iframe", {
          class: "pdf-preview",
          src: pdfUrl(run) + "&inline=1",
          title: "Vista previa del PDF",
        }));
        return;
      }
      try {
        const res = await fetch(`/api/history/runs/${run.run_id}/cv`);
        if (res.ok) {
          const text = await res.text();
          panel.innerHTML = "";
          panel.appendChild(h("pre", { class: "detail-pre" }, text));
          panel.appendChild(h("p", { class: "detail-hint" },
            "Vista previa del CV guardado (YAML). El PDF no está disponible para esta corrida."));
          return;
        }
      } catch {
        // caemos al estado "no disponible"
      }
      panel.innerHTML = "";
      panel.appendChild(h("p", { class: "history-empty" },
        "No hay PDF ni CV guardado para esta corrida."));
    };

    const fillAnalysisPanel = (panel) => {
      panel.appendChild(h("p", { class: "detail-hint" }, ATS_TOOLTIP));
      panel.appendChild(h("div", { class: "detail-score" }, [
        h("span", { class: "detail-score-value" }, String(run.ats_score)),
        h("span", { class: "detail-score-caption" }, "ATS Impact Score"),
      ]));

      const detected = run.keywords_detected || [];
      const notInMaster = run.not_in_master || [];
      const missingInTarget = run.missing_in_target || [];
      const manual = run.manual_keywords || [];
      const critical = new Set(run.critical_missing || []);
      const freqs = run.not_in_master_frequencies || {};

      if (!detected.length && !notInMaster.length && !missingInTarget.length && !manual.length) {
        panel.appendChild(h("p", { class: "history-empty" }, "Sin datos de análisis para esta corrida."));
        return;
      }

      if (notInMaster.length) {
        panel.appendChild(h("h4", { class: "detail-h4" }, "Pedidas por la oferta y ausentes en tu CV maestro"));
        panel.appendChild(h("div", { class: "detail-kws" }, notInMaster.map((kw) =>
          h("span", { class: "detail-kw danger" }, [
            kw,
            (freqs[kw] || 1) > 1 ? h("span", { class: "detail-kw-freq" }, `×${freqs[kw]}`) : null,
            critical.has(kw) ? h("span", { class: "detail-kw-critical" }, "crítica") : null,
          ]))));
      }
      if (missingInTarget.length) {
        panel.appendChild(h("h4", { class: "detail-h4" }, "En el master pero recortadas del CV generado"));
        panel.appendChild(h("div", { class: "detail-kws" }, missingInTarget.map((kw) =>
          h("span", { class: "detail-kw warn" }, kw))));
      }
      if (detected.length) {
        panel.appendChild(h("h4", { class: "detail-h4" }, "Keywords detectadas en la oferta"));
        panel.appendChild(h("div", { class: "detail-kws" }, detected.map((kw) =>
          h("span", { class: "detail-kw" }, kw))));
      }
      if (manual.length) {
        panel.appendChild(h("h4", { class: "detail-h4" }, "Keywords manuales que sumaste"));
        panel.appendChild(h("div", { class: "detail-kws" }, manual.map((kw) =>
          h("span", { class: "detail-kw" }, kw))));
      }
    };

    showTab(initialTab);

    return h("div", {}, [
      h("h3", {}, "Detalle de la corrida"),
      h("p", { class: "detail-subtitle" }, run.offer_title || "—"),
      tabRow,
      panelHost,
      h("div", { class: "modal-actions" }, [
        h("button", { class: "btn btn-ghost", onclick: () => close(false) }, "Cerrar"),
      ]),
    ]);
  }, { boxClass: "modal-wide" });
}

// -------------------------------------------------- chips de estado (filtro)

function renderStatusChips() {
  const host = $("#history-status-chips");
  if (!host) return;
  host.innerHTML = "";
  const counts = page.statusCounts || {};
  const totalAll = Object.values(counts).reduce((a, b) => a + b, 0);
  if (!totalAll) {
    host.hidden = true;
    return;
  }
  host.hidden = false;
  const makeChip = (label, value, count) =>
    h("button", {
      class: "chip" + (filters.status === value ? " is-active" : ""),
      "aria-pressed": filters.status === value ? "true" : "false",
      onclick: () => {
        filters.status = value;
        renderStatusChips();
        fetchPage(true);
      },
    }, `${label} (${count})`);
  const chips = [makeChip("Todas", "", totalAll)];
  for (const st of STATUS_ORDER) {
    if (counts[st]) chips.push(makeChip(STATUS_LABELS[st], st, counts[st]));
  }
  host.append(...chips);
}

// --------------------------------------- stats: keywords faltantes del master

function renderKeywordStats(keywords) {
  const el = $("#history-stats");
  el.innerHTML = "";
  if (!keywords.length) {
    el.appendChild(h("p", { class: "history-empty" },
      "Todavía no hay keywords faltantes registradas. Las ofertas que proceses se van sumando acá."));
    return;
  }
  const list = h("div", { class: "history-stats-list" }, keywords.map((k) => {
    const titles = k.offer_titles && k.offer_titles.length
      ? h("span", { class: "history-stat-titles" }, "En: " + [...new Set(k.offer_titles)].join(" · "))
      : null;
    const copy = async () => {
      try {
        await navigator.clipboard.writeText(k.keyword);
        toast(`"${k.keyword}" copiada.`);
      } catch (e) {
        setGlobalStatus("No se pudo copiar: " + e.message, "error");
      }
    };
    return h("div", { class: "history-stat" }, [
      h("span", { class: "history-stat-keyword" }, k.keyword),
      h("div", { class: "history-stat-body" }, [
        h("div", {}, [
          h("span", { class: "history-stat-count" }, `${k.count} oferta${k.count === 1 ? "" : "s"}`),
          k.ever_critical ? h("span", { class: "history-stat-critical" }, "crítica") : null,
        ]),
        h("div", { class: "history-stat-meta" },
          `Primera vez: ${formatDate(k.first_seen)} · Última vez: ${formatDate(k.last_seen)}`),
        titles,
      ]),
      h("button", { class: "btn btn-sm btn-ghost history-copy-btn", onclick: copy }, "Copiar"),
    ]);
  }));
  el.appendChild(list);
}

// --------------------------------------------------------------- listeners

let searchTimer = null;
$("#history-search").addEventListener("input", (e) => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => {
    filters.q = e.target.value.trim();
    fetchPage(true);
  }, 250);
});

$("#history-load-more").addEventListener("click", () => fetchPage(false));


export { loadHistoryView };
