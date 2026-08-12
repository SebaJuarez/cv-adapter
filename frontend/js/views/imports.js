//módulo: imports — bandeja de revisión de clusters de CVs importados (F5,
//doc §4.2/§6.3): subida de PDFs/texto/YAML, agrupación automática y
//confirmación explícita cluster por cluster. Nada entra al master sin que
//el usuario lo revise; la sesión queda guardada para retomar después.

import { api } from "../api.js";
import { commitAchDraft, renderAchievementCard } from "../components.js";
import { h, $ } from "../dom.js";
import { blankEntryFor } from "../labels.js";
import { toast } from "../notify.js";
import { markDirty, snapshotView, state } from "../state.js";

const SESSION_KEY = "cvImportSessionId";

let session = null;
let pendingCandidates = null; // { source: "cl_X" | "orphans", entries: [...] }

async function loadImportsView() {
  const saved = localStorage.getItem(SESSION_KEY);
  if (saved) {
    try {
      const res = await api(`/api/imports/session/${saved}`);
      session = res.session;
      drawBandeja();
      return;
    } catch (e) {
      // Sesión vieja o borrada: arrancar de cero.
      localStorage.removeItem(SESSION_KEY);
    }
  }
  drawUpload();
}

// ------------------------------------------------------- pantalla de carga

function readBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",")[1] || "");
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}

function drawUpload() {
  const root = $("#imports-root");
  root.innerHTML = "";
  const fileInput = h("input", {
    type: "file", multiple: true, accept: ".pdf,.yaml,.yml,.json,.txt",
    "aria-label": "Archivos de CV para importar",
  });
  const ta = h("textarea", { class: "highlight-text", placeholder: "…o pegá acá el texto de un CV (un bullet por línea)." });
  const goBtn = h("button", { class: "btn btn-primary" }, "Importar y agrupar");

  const runImport = async () => {
    const files = [...(fileInput.files || [])];
    const pasted = ta.value.trim();
    if (!files.length && !pasted) {
      toast("Subí al menos un archivo o pegá un CV.");
      return;
    }
    goBtn.disabled = true;
    goBtn.textContent = "Agrupando…";
    const list = [];
    for (const f of files) {
      const name = (f.name || "").toLowerCase();
      const kind = name.endsWith(".pdf") ? "pdf"
        : name.endsWith(".yaml") || name.endsWith(".yml") ? "yaml"
        : name.endsWith(".json") ? "json"
        : "text";
      const content = kind === "pdf" ? await readBase64(f) : await f.text();
      list.push({ name: f.name || "archivo", kind, content });
    }
    if (pasted) list.push({ name: "texto pegado.txt", kind: "text", content: pasted });
    try {
      const res = await api("/api/imports/clusterize", { method: "POST", body: JSON.stringify({ files: list }) });
      session = res.session;
      localStorage.setItem(SESSION_KEY, session.id);
      drawBandeja();
    } catch (e) {
      toast(e.message || "No se pudo agrupar la importación.");
    } finally {
      goBtn.disabled = false;
      goBtn.textContent = "Importar y agrupar";
    }
  };
  goBtn.addEventListener("click", runImport);

  root.appendChild(h("div", { class: "imports-upload" }, [
    h("p", { class: "imports-hint" }, "Podés subir varios archivos a la vez (PDF, .yaml, .json o texto plano)."),
    h("label", { class: "imports-file-label" }, [
      "Elegir archivos…",
      fileInput,
    ]),
    ta,
    h("div", { class: "imports-actions" }, [goBtn]),
  ]));
}

// -------------------------------------------------------------- bandeja

function diffMarkup(texts) {
  const tokenSets = texts.map((t) => new Set(t.split(/\s+/)));
  const common = new Set(tokenSets[0]);
  tokenSets.forEach((s) => {
    common.forEach((w) => { if (!s.has(w)) common.delete(w); });
  });
  return texts.map((t) => {
    const span = h("span", {});
    t.split(/\s+/).forEach((w, i) => {
      if (i) span.appendChild(document.createTextNode(" "));
      span.appendChild(common.has(w) ? document.createTextNode(w) : h("b", { class: "imp-diff" }, w));
    });
    return span;
  });
}

function buildEntries(candidates) {
  return (candidates || []).map((c) => {
    const entry = blankEntryFor("experience", "entries");
    delete entry.highlights; // D1: una entrada usa un solo formato
    entry.achievements = [c];
    return entry;
  });
}

// Confirma candidatos en el master (fuente única: cluster o huérfanos).
async function confirmEntries(source, entries) {
  entries.forEach((entry) => {
    commitAchDraft(entry, 0, { onRerender: () => {} }); // aplica borradores si hay
    state.masterDoc.cv.sections.experience.push(entry);
  });
  markDirty("master");
  try {
    await api("/api/master-cv", { method: "POST", body: JSON.stringify(state.masterDoc) });
    snapshotView("master");
    if (source !== "orphans") {
      await api(`/api/imports/session/${session.id}/confirm`, {
        method: "POST",
        body: JSON.stringify({ cluster_id: source }),
      });
      session = (await api(`/api/imports/session/${session.id}`)).session;
    }
    toast(`${entries.length} logro${entries.length === 1 ? "" : "s"} importado${entries.length === 1 ? "" : "s"} al CV maestro.`);
    pendingCandidates = null;
    drawBandeja();
  } catch (e) {
    toast("Los logros quedaron en el editor de master, pero no se pudo persistir: " + (e.message || "error"));
  }
}

async function resolveCluster(clusterId, action, btn) {
  btn.disabled = true;
  btn.textContent = "…";
  try {
    const res = await api(`/api/imports/session/${session.id}/resolve`, {
      method: "POST",
      body: JSON.stringify({ cluster_id: clusterId, action }),
    });
    session = res.session;
    pendingCandidates = res.candidates.length ? { source: clusterId, entries: buildEntries(res.candidates) } : null;
    drawBandeja();
    if (!res.candidates.length) toast("Grupo descartado: ninguna redacción entra al CV.");
  } catch (e) {
    toast(e.message || "No se pudo resolver el grupo.");
  }
}

function clusterCard(cluster) {
  const texts = cluster.bullet_ids.map((i) => session.bullets[i].text);
  const marks = diffMarkup(texts);
  const rows = texts.map((t, i) => h("div", { class: "imp-cluster-row" }, [
    h("span", { class: "imp-file" }, session.bullets[cluster.bullet_ids[i]].file),
    h("div", { class: "imp-cluster-text" }, marks[i]),
  ]));
  const rec = session.resolutions[cluster.id] || { status: "pending", candidates: [] };
  const candidates = rec.candidates || [];
  const nodes = [
    h("div", { class: "imp-cluster-head" }, [
      h("strong", {}, `${texts.length} redacciones parecidas`),
      h("span", { class: "imp-cluster-hint" }, "en negrita: lo que difiere entre ellas"),
    ]),
    h("div", { class: "imp-cluster-rows" }, rows),
  ];
  if (rec.status === "awaiting" && candidates.length) {
    // Retomando sesión: los candidatos ya fueron generados, faltan confirmar.
    const entries = buildEntries(candidates);
    const ctx = { doc: state.masterDoc, isTarget: false, onRerender: drawBandeja };
    const cards = h("div", { class: "imp-awaiting-cards" });
    entries.forEach((entry) => cards.appendChild(renderAchievementCard(entry, entry.achievements[0], 0, ctx)));
    nodes.push(h("div", { class: "imp-awaiting" }, [
      h("p", { class: "imp-awaiting-hint" }, `Candidatos ya generados (${candidates.length}): editá si hace falta y confirmá.`),
      cards,
      h("div", { class: "imp-cluster-actions" }, [
        h("button", { class: "btn btn-primary btn-sm", onclick: () => confirmEntries(cluster.id, entries) },
          `Confirmar ${candidates.length} logro${candidates.length === 1 ? "" : "s"} en el CV maestro`),
        h("button", { class: "btn btn-ghost btn-sm", onclick: (e) => resolveCluster(cluster.id, "discard", e.currentTarget) }, "Descartar"),
        h("button", { class: "btn btn-ghost btn-sm", onclick: (e) => resolveCluster(cluster.id, "merge", e.currentTarget) }, "Regenerar (unir)"),
        h("button", { class: "btn btn-ghost btn-sm", onclick: (e) => resolveCluster(cluster.id, "split", e.currentTarget) }, "Regenerar (separar)"),
      ]),
    ]));
  } else {
    nodes.push(h("div", { class: "imp-cluster-actions" }, [
      h("button", { class: "btn btn-primary btn-sm", onclick: (e) => resolveCluster(cluster.id, "merge", e.currentTarget) },
        "Es el mismo logro"),
      h("button", { class: "btn btn-ghost btn-sm", onclick: (e) => resolveCluster(cluster.id, "split", e.currentTarget) },
        "Son logros distintos"),
      h("button", { class: "btn btn-ghost btn-sm", onclick: (e) => resolveCluster(cluster.id, "discard", e.currentTarget) },
        "Descartar"),
    ]));
  }
  return h("div", { class: "imp-cluster card" }, nodes);
}

function candidatesZone() {
  const zone = h("div", { class: "imp-candidates" });
  const ctx = { doc: state.masterDoc, isTarget: false, onRerender: redraw };
  function redraw() {
    zone.innerHTML = "";
    zone.appendChild(h("h2", { class: "imports-h2" }, "Revisá los logros propuestos"));
    zone.appendChild(h("p", { class: "imports-hint" },
      pendingCandidates.source === "orphans"
        ? `${pendingCandidates.entries.length} redacción${pendingCandidates.entries.length === 1 ? "" : "es"} únicas. Editá lo que quieras antes de confirmar.`
        : "Un logro con todas las redacciones del grupo como variantes. Si algo no cierra, editá los hechos o las redacciones antes de confirmar."));
    pendingCandidates.entries.forEach((entry) => {
      zone.appendChild(renderAchievementCard(entry, entry.achievements[0], 0, ctx));
    });
    const actions = h("div", { class: "imp-candidate-actions" }, [
      h("button", { class: "btn btn-ghost", onclick: () => { pendingCandidates = null; drawBandeja(); } }, "Rehacer"),
      h("button", { class: "btn btn-primary",
        onclick: (e) => {
          e.currentTarget.disabled = true;
          confirmEntries(pendingCandidates.source, pendingCandidates.entries);
        } },
      `Confirmar ${pendingCandidates.entries.length} logro${pendingCandidates.entries.length === 1 ? "" : "s"} en el CV maestro`),
    ]);
    zone.appendChild(actions);
  }
  redraw();
  return zone;
}

function closeSession() {
  localStorage.removeItem(SESSION_KEY);
  session = null;
  pendingCandidates = null;
  drawUpload();
}

function drawBandeja() {
  const root = $("#imports-root");
  root.innerHTML = "";
  const doneClusters = Object.values(session.resolutions).filter((r) => r.status === "done").length;
  const reviewed = doneClusters + (session.orphans_done ? 1 : 0);
  const total = session.clusters.length + (session.orphans_done ? 0 : 1);
  root.appendChild(h("div", { class: "imports-top" }, [
    h("p", { class: "imports-progress" }, `Revisados: ${reviewed} de ${total} grupos`),
    h("button", { class: "btn btn-ghost btn-sm", onclick: closeSession }, "Cerrar esta importación"),
  ]));

  if (pendingCandidates) root.appendChild(candidatesZone());

  const stillPending = session.clusters.filter((c) =>
    ["pending", "awaiting"].includes(session.resolutions[c.id]?.status));
  const orphansPending = session.orphan_ids.length > 0 && !session.orphans_done;
  if (stillPending.length || orphansPending) {
    if (stillPending.length) {
      root.appendChild(h("h2", { class: "imports-h2" }, "Grupos por revisar"));
      stillPending.forEach((c) => root.appendChild(clusterCard(c)));
    }
    if (orphansPending && !stillPending.length) {
      root.appendChild(h("p", { class: "imports-hint" },
        "No quedan grupos duplicados: lo que falta son los logros sin duplicados de abajo."));
    }
  } else {
    root.appendChild(h("p", { class: "imports-done" }, "Todos los grupos fueron revisados."));
  }

  if (orphansPending) {
    const n = session.orphan_ids.length;
    const plural = n === 1 ? "redacción" : "redacciones";
    root.appendChild(h("div", { class: "imp-orphans" }, [
      h("h2", { class: "imports-h2" }, "Logros sin duplicados"),
      h("p", { class: "imports-hint" },
        `${n} ${plural} que aparecen en un solo CV. Aceptalas todas como están, descartalas, o cerrá la importación y cargalas desde el editor.`),
      h("div", { class: "imp-cluster-actions" }, [
        h("button", { class: "btn btn-primary btn-sm", onclick: async (e) => {
          try {
            const res = await api(`/api/imports/session/${session.id}/orphans`, {
              method: "POST", body: JSON.stringify({ accept: true }),
            });
            session = res.session;
            pendingCandidates = { source: "orphans", entries: buildEntries(res.candidates) };
            drawBandeja();
          } catch (err) {
            toast(err.message || "No se pudo aceptar el grupo.");
          }
        } }, "Aceptar todos como están"),
        h("button", { class: "btn btn-ghost btn-sm", onclick: async (e) => {
          e.currentTarget.disabled = true;
          try {
            const res = await api(`/api/imports/session/${session.id}/orphans`, {
              method: "POST", body: JSON.stringify({ accept: false }),
            });
            session = res.session;
            pendingCandidates = null;
            drawBandeja();
            toast("Redacciones descartadas: no entran al CV.");
          } catch (err) {
            toast(err.message || "No se pudo descartar el grupo.");
          }
        } }, "Descartar todas"),
      ]),
    ]));
  }
}

export { loadImportsView };