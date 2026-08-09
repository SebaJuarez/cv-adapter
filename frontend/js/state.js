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
  masterFilter: "",
  collapsedMaster: {},
  lastUndo: null,
};

const dirty = { master: false, apply: false, settings: false };

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


export { dirty, markDirty, rememberUndo, state, undoLast };
