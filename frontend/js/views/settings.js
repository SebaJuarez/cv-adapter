//módulo: settings — vista settings: configuración del pipeline

import { api } from "../api.js";
import { $, h } from "../dom.js";
import { setGlobalStatus, setStatus, toast } from "../notify.js";
import { dirty, state } from "../state.js";

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
  {
    key: "show_keywords_line",
    label: "Mostrar línea \"Palabras clave\" en el CV",
    type: "boolean",
    hint: "Ayuda contra ATS de conteo simple, pero un reclutador humano puede leerla como relleno. Si lo apagás, las keywords siguen influyendo en qué bullets/skills se priorizan — solo se oculta la línea explícita.",
  },
];

function validateConfig(config) {
  const validated = { ...config };
  for (const field of SETTINGS_FIELDS) {
    const value = validated[field.key];
    if (field.type === "number") {
      if (!Number.isInteger(value) || value < 1) {
        throw new Error(`"${field.label}" debe ser un número entero mayor o igual a 1.`);
      }
      continue;
    }
    if (field.type === "boolean") {
      validated[field.key] = Boolean(value);
      continue;
    }
    if (typeof value !== "string" || value.trim() === "") {
      throw new Error(`"${field.label}" no puede estar vacío.`);
    }
    validated[field.key] = value.trim();
  }
  return validated;
}

async function loadSettingsView() {
  state.config = await api("/api/config");
  drawSettingsView();
}

function drawSettingsView() {
  const form = $("#settings-form");
  form.innerHTML = "";
  SETTINGS_FIELDS.forEach((f) => {
    if (f.type === "boolean") {
      const checkbox = h("input", { type: "checkbox" });
      checkbox.checked = Boolean(state.config[f.key]);
      checkbox.addEventListener("change", () => {
        state.config[f.key] = checkbox.checked;
      });
      const fieldEl = h("div", { class: "settings-field settings-field-boolean" }, [
        h("label", { class: "settings-checkbox-label" }, [checkbox, " " + f.label]),
      ]);
      if (f.hint) fieldEl.appendChild(h("span", { class: "hint" }, f.hint));
      form.appendChild(fieldEl);
      return;
    }
    const input = h("input", {
      type: f.type,
      value: state.config[f.key],
      min: f.type === "number" ? 1 : null,
      step: f.type === "number" ? 1 : null,
    });
    input.addEventListener("input", () => {
      if (f.type === "number") {
        state.config[f.key] = input.value === "" ? null : Number.parseInt(input.value, 10);
      } else {
        state.config[f.key] = input.value;
      }
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
  const btn = $("#save-settings");
  btn.disabled = true;
  try {
    const payload = validateConfig(state.config);
    state.config = await api("/api/config", { method: "POST", body: JSON.stringify(payload) });
    dirty.settings = false;
    setStatus(statusEl, "Guardado.", "ok");
    toast("Configuración guardada.");
  } catch (e) {
    setStatus(statusEl, e.message, "error");
    setGlobalStatus("No se pudo guardar la configuración: " + e.message, "error");
  } finally {
    btn.disabled = false;
  }
});


export { SETTINGS_FIELDS, drawSettingsView, loadSettingsView, validateConfig };
