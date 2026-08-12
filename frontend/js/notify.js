//módulo: notify — toasts, status, progreso y tooltip del JD

import { $, h } from "./dom.js";

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

function toast(message, kind, action) {
  const container = $("#toasts");
  if (!container) return;
  const content = typeof message === "string" ? [message] : [...(message || [])];
  if (action && action.label) {
    content.push(h("button", { class: "toast-action", onclick: action.onclick }, action.label));
  }
  const el = h("div", { class: "toast" + (kind ? " toast-" + kind : "") }, content);
  container.appendChild(el);
  setTimeout(() => {
    el.classList.add("toast-out");
    setTimeout(() => el.remove(), 320);
  }, 4000);
}

// ---------------------------------------------------------------- progreso

function showProgress(id) { const el = $(id); if (el) el.hidden = false; }
function hideProgress(id) { const el = $(id); if (el) el.hidden = true; }

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


export { hideJDSnippet, hideProgress, setGlobalStatus, setStatus, showJDSnippet, showProgress, toast };
