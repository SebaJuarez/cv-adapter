//módulo: state — estado global, dirty state y undo

import { $ } from "./dom.js";
import { setStatus, toast } from "./notify.js";

const state = {
  masterDoc: null,
  targetDoc: null,
  selection: null,
  config: null,
  masterDocSnapshot: null,
  masterSectionTypes: {},
  targetSectionTypes: {},
  keywordReport: null,
  pageEstimate: null,
  currentRunId: null,
  masterFilter: "",
  collapsedMaster: {},
  lastUndo: null,
};

const dirty = { master: false, apply: false, settings: false };

// Solo estas vistas tienen estado editable (y por lo tanto dirty state).
// Cualquier otra (historial, futuras) devuelve false siempre.
const EDITABLE_VIEWS = ["master", "apply", "settings"];

// Snapshot por vista: fingerprint del documento en su último estado
// cargado/guardado. La fuente de verdad del "cambios sin guardar" es la
// comparación contra este snapshot, no los eventos de input.
const snapshots = { master: null, apply: null, settings: null };

function docFor(view) {
  if (view === "master") return state.masterDoc;
  if (view === "apply") return state.targetDoc;
  if (view === "settings") return state.config;
  return undefined;
}

// Serialización con claves ordenadas: inmune al orden de inserción de
// propiedades (p.ej. agregar una sección no reordena el resto).
function fingerprint(obj) {
  const sortKeys = (v) => {
    if (Array.isArray(v)) return v.map(sortKeys);
    if (v && typeof v === "object") {
      const out = {};
      Object.keys(v).sort().forEach((k) => { out[k] = sortKeys(v[k]); });
      return out;
    }
    return v;
  };
  return JSON.stringify(sortKeys(obj));
}

// Guarda el estado "persistido" de la vista (carga o guardado exitoso).
function snapshotView(view) {
  const doc = docFor(view);
  snapshots[view] = doc ? fingerprint(doc) : null;
  dirty[view] = false;
}

function hasUnsavedChanges(view) {
  if (!EDITABLE_VIEWS.includes(view)) return false;
  const doc = docFor(view);
  if (!doc) return false;
  const snap = snapshots[view];
  if (snap === null) return true; // doc cargado sin snapshot conocido: avisar
  return fingerprint(doc) !== snap;
}

// -------------------------------------------------------- dirty state

function markDirty(view) {
  if (!EDITABLE_VIEWS.includes(view)) return;
  // No marcar si el documento en realidad no cambió (collapse de secciones,
  // escribir en un modal y cancelar, escribir y borrar, autofill idéntico…).
  const doc = docFor(view);
  if (!doc) return;
  if (snapshots[view] !== null && fingerprint(doc) === snapshots[view]) return;
  dirty[view] = true;
  const el = view === "master" ? $("#master-status")
    : view === "apply" ? $("#render-status")
    : $("#settings-status");
  if (el) setStatus(el, "Hay cambios sin guardar.", "dirty");
  if (view === "apply") document.dispatchEvent(new CustomEvent("cv:apply-dirty"));
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


export { dirty, hasUnsavedChanges, markDirty, rememberUndo, snapshotView, state, undoLast };
