//módulo: modals — sistema de modales (openModal, confirmAction, promptAddSection)

import { $, h } from "./dom.js";

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


export { confirmAction, openModal, promptAddSection, showMessageModal };
