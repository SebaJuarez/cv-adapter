//módulo: history — vista de historial: corridas registradas, seguimiento de
// la aplicación y keywords que faltan en el CV maestro (recurrentes)

import { api } from "../api.js";
import { $, h } from "../dom.js";
import { confirmAction, openModal } from "../modals.js";
import { setGlobalStatus, toast } from "../notify.js";

const STATUS_LABELS = {
  pendiente: "Pendiente",
  aplicado: "Aplicado",
  entrevista: "En entrevista",
  oferta: "Oferta",
  rechazado: "Rechazado",
};

const STATUS_ORDER = ["pendiente", "aplicado", "entrevista", "oferta", "rechazado"];

function formatDate(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleDateString("es", { day: "2-digit", month: "2-digit", year: "numeric" });
}

function formatAppliedAt(dateStr) {
  return dateStr || "—";
}

// ---------------------------------------------------------- carga inicial

async function loadHistoryView() {
  const [runsRes, statsRes] = await Promise.allSettled([
    api("/api/history/runs"),
    api("/api/history/stats/keywords"),
  ]);
  if (runsRes.status === "rejected") {
    setGlobalStatus("No se pudo cargar el historial: " + runsRes.reason.message, "error");
    return;
  }
  renderRuns(runsRes.value.runs || []);
  renderKeywordStats(statsRes.status === "fulfilled" ? statsRes.value.keywords : []);
}

async function reload() {
  try {
    const { runs } = await api("/api/history/runs");
    renderRuns(runs || []);
    const { keywords } = await api("/api/history/stats/keywords");
    renderKeywordStats(keywords || []);
  } catch (e) {
    setGlobalStatus("No se pudo refrescar el historial: " + e.message, "error");
  }
}

// --------------------------------------------------------- tabla de runs

function renderRuns(runs) {
  const list = $("#history-list");
  list.innerHTML = "";
  if (!runs.length) {
    list.appendChild(h("p", { class: "history-empty" },
      "Todavía no hay corridas registradas. Generá un CV para una oferta y aparece acá automáticamente."));
    return;
  }
  const table = h("table", { class: "history-table" }, [
    h("thead", {}, h("tr", {}, [
      h("th", { scope: "col" }, "Fecha"),
      h("th", { scope: "col" }, "Oferta"),
      h("th", { scope: "col" }, "ATS"),
      h("th", { scope: "col" }, "Faltantes"),
      h("th", { scope: "col" }, "Estado"),
      h("th", { scope: "col" }, "Acciones"),
    ])),
    h("tbody", {}, runs.map(buildRow)),
  ]);
  list.appendChild(table);
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
    missing.push(h("span", { class: "history-missing notmaster", title: "No están en tu CV maestro" },
      `${notInMaster} sin master`));
  }
  if (missingInTarget > 0) {
    missing.push(h("span", { class: "history-missing missing", title: "Están en el master pero no entraron al CV generado" },
      `${missingInTarget} recortadas`));
  }

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
      } catch (err) {
        setGlobalStatus("No se pudo actualizar el estado: " + err.message, "error");
        reload();
      }
    },
  }, STATUS_ORDER.map((s) => h("option", { value: s, selected: s === run.application.status ? "selected" : null },
    STATUS_LABELS[s])));

  const statusCell = [statusSelect, h("span", { class: "history-applied" },
    "Aplicado: " + formatAppliedAt(run.application && run.application.applied_at))];

  const actions = [];
  actions.push(h("button", {
    class: "btn btn-sm btn-ghost",
    onclick: () => openEditModal(run),
  }, "Editar"));
  if (run.pdf_path) {
    actions.push(h("a", {
      class: "btn btn-sm btn-ghost",
      href: "/api/download-pdf?path=" + encodeURIComponent(run.pdf_path),
    }, "PDF"));
  }
  actions.push(h("button", {
    class: "btn btn-sm btn-ghost btn-danger-text",
    onclick: () => confirmDelete(run),
  }, "Borrar"));

  return h("tr", {}, [
    h("td", { class: "history-date" }, formatDate(run.created_at)),
    h("td", {}, titleCell),
    h("td", { class: "history-num" }, String(run.ats_score)),
    h("td", { class: "history-missing-cell" }, missing),
    h("td", { class: "history-status-cell" }, statusCell),
    h("td", {}, h("div", { class: "history-actions" }, actions)),
  ]);
}

function confirmDelete(run) {
  return confirmAction({
    title: "Borrar corrida",
    message: `¿Borrar la corrida "${run.offer_title}"? El historial y su seguimiento se pierden (los PDFs en output/ no se borran).`,
    confirmLabel: "Borrar",
    cancelLabel: "Cancelar",
  }).then(async (ok) => {
    if (!ok) return;
    try {
      await api(`/api/history/runs/${run.run_id}`, { method: "DELETE" });
      toast("Corrida borrada.");
      reload();
    } catch (e) {
      setGlobalStatus("No se pudo borrar la corrida: " + e.message, "error");
    }
  });
}

// ------------------------------------------------------- modal de edición

function openEditModal(run) {
  openModal((close) => {
    const titleInput = h("input", { type: "text", value: run.offer_title || "" });
    const linkInput = h("input", { type: "text", value: run.offer_link || "", placeholder: "https://…" });
    const statusSelect = h("select", {},
      STATUS_ORDER.map((s) => h("option", { value: s, selected: s === run.application.status ? "selected" : null },
        STATUS_LABELS[s])));
    const appliedAtInput = h("input", { type: "date", value: run.application.applied_at || "" });
    const notesInput = h("textarea", { rows: "3", placeholder: "Notas: canal, contacto, fecha de entrevista…" },
      run.application.notes || "");

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


export { loadHistoryView };
