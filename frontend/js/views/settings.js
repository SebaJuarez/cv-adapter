//módulo: settings — vista settings: configuración del pipeline

import { api } from "../api.js";
import { $, h } from "../dom.js";
import { setGlobalStatus, setStatus, toast } from "../notify.js";
import { snapshotView, state } from "../state.js";

// ------------------------------------------------------- vista: settings

// Sugerencias de modelos de OpenRouter (solo ayuda al escribir el ID en el
// campo de texto libre — no hay lista cerrada ni mantenimiento de API).
const OPENROUTER_MODEL_SUGGESTIONS = [
  "nvidia/nemotron-3.5-lightning:free",
  "openai/gpt-4o-mini",
  "openai/gpt-4o",
  "anthropic/claude-3.5-haiku",
  "anthropic/claude-3.5-sonnet",
  "google/gemini-2.0-flash-001",
  "meta-llama/llama-3.3-70b-instruct",
  "deepseek/deepseek-chat-v3.1",
  "mistralai/mistral-small-3.2-24b-instruct",
];

// El valor guardado de "openrouter" es llm_provider=openai + base_url de
// OpenRouter (el despacho _call_llm no cambia). El select lo deriva al dibujar.
function llmProviderSelectValue(config) {
  if (config.llm_provider === "ollama") return "ollama";
  const base = String(config.openai_base_url || "").toLowerCase();
  return base.includes("openrouter.ai") ? "openrouter" : "openai";
}

const LLM_PROVIDER_OPTIONS = [
  { value: "ollama", label: "Ollama (modelo local)" },
  { value: "openai", label: "API remota compatible con OpenAI" },
  { value: "openrouter", label: "OpenRouter (API remota)" },
];

const SETTINGS_FIELDS = [
  {
    key: "llm_provider",
    label: "Proveedor del LLM",
    type: "select",
    options: LLM_PROVIDER_OPTIONS,
    hint: "Local: requiere Ollama corriendo. Remoto: usa una API key (OpenAI, OpenRouter, Groq…).",
  },
  {
    key: "ollama_model",
    label: "Modelo de Ollama",
    type: "text",
    hint: "ej: llama3:8b, llama3.1:8b",
    visibleWhen: (c) => c.llm_provider === "ollama",
  },
  {
    key: "openai_api_key",
    label: "API key del proveedor remoto",
    type: "password",
    hint: "Se guarda en config.json (gitignored, texto plano). También podés inyectarla con la variable de entorno OPENAI_API_KEY (tiene prioridad sobre el archivo). Solo necesaria con proveedor remoto.",
    visibleWhen: (c) => c.llm_provider !== "ollama",
  },
  {
    key: "openai_model",
    label: "Modelo remoto",
    type: "text",
    hint: "ej: gpt-4o-mini, nvidia/nemotron-3.5-lightning:free. Con OpenRouter usás el ID completo del modelo (sugerencias abajo).",
    visibleWhen: (c) => c.llm_provider !== "ollama",
  },
  {
    key: "openai_base_url",
    label: "URL base remota (opcional)",
    type: "text",
    hint: "Se completa sola al elegir OpenRouter. Para Groq, LM Studio… usá su URL. Vacío = endpoint oficial de OpenAI.",
    visibleWhen: (c) => c.llm_provider !== "ollama",
  },
  { key: "rendercv_theme", label: "Tema de RenderCV", type: "text", hint: "ej: engineeringresumes, classic, sb2nov" },
  { key: "max_experience_entries", label: "Máx. experiencias", type: "number" },
  { key: "max_project_entries", label: "Máx. proyectos", type: "number" },
  { key: "max_highlights_per_entry", label: "Máx. bullets por entrada", type: "number" },
  { key: "max_skill_categories", label: "Máx. categorías de skills", type: "number" },
  { key: "max_education_extra", label: "Máx. certificaciones extra", type: "number" },
  { key: "max_keywords", label: "Máx. keywords ATS", type: "number" },
  {
    key: "custom_keywords",
    label: "Keywords ATS fijas (separadas por coma)",
    type: "list",
    hint: "Palabras clave que SIEMPRE entran al CV, aunque no estén en la oferta. Se agregan a las detectadas del JD (afectan el ranking de bullets y el reporte ATS).",
  },
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
    if (field.type === "select") {
      if (!field.options.some((o) => o.value === value)) {
        throw new Error(`"${field.label}" tiene un valor inválido.`);
      }
      continue;
    }
    if (field.type === "list") {
      const list = Array.isArray(value) ? value : [];
      validated[field.key] = list
        .map((item) => String(item).trim())
        .filter((item) => item !== "");
      continue;
    }
    if (field.type === "password") {
      validated[field.key] = typeof value === "string" ? value : "";
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
  snapshotView("settings");
  drawSettingsView();
}

function drawSettingsView() {
  const form = $("#settings-form");
  form.innerHTML = "";
  form.appendChild(buildModelSuggestions());
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
    if (f.type === "select") {
      const select = h("select", {});
      const selectedValue = f.key === "llm_provider" ? llmProviderSelectValue(state.config) : String(state.config[f.key]);
      f.options.forEach((o) => {
        const opt = h("option", { value: o.value }, o.label);
        if (selectedValue === o.value) opt.selected = true;
        select.appendChild(opt);
      });
      select.addEventListener("change", () => {
        if (f.key === "llm_provider") {
          const v = select.value;
          if (v === "ollama") {
            state.config.llm_provider = "ollama";
          } else {
            state.config.llm_provider = "openai";
            state.config.openai_base_url = v === "openrouter" ? "https://openrouter.ai/api/v1" : "";
            const urlInput = form.querySelector('input[data-cfg-key="openai_base_url"]');
            if (urlInput) urlInput.value = state.config.openai_base_url;
          }
          applyLlmVisibility();
        } else {
          state.config[f.key] = select.value;
        }
      });
      const fieldEl = h("div", { class: "settings-field" }, [
        h("label", {}, f.label),
        select,
      ]);
      if (f.hint) fieldEl.appendChild(h("span", { class: "hint" }, f.hint));
      form.appendChild(fieldEl);
      return;
    }
    if (f.type === "list") {
      const input = h("input", {
        type: "text",
        value: (Array.isArray(state.config[f.key]) ? state.config[f.key] : []).join(", "),
      });
      input.addEventListener("input", () => {
        state.config[f.key] = input.value
          .split(",")
          .map((item) => item.trim())
          .filter((item) => item !== "");
      });
      const fieldEl = h("div", { class: "settings-field" }, [
        h("label", {}, f.label),
        input,
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
      "data-cfg-key": f.key,
      ...(f.key === "openai_model" ? { list: "openrouter-model-suggestions" } : {}),
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
    if (f.visibleWhen) fieldEl._visibleWhen = f.visibleWhen;
    form.appendChild(fieldEl);
  });
  applyLlmVisibility();
}

// Muestra/oculta los campos dependientes del proveedor (los valores nunca se
// pierden: solo cambia la visibilidad).
function applyLlmVisibility() {
  const form = $("#settings-form");
  for (const el of form.querySelectorAll(".settings-field")) {
    if (typeof el._visibleWhen === "function") {
      el.style.display = el._visibleWhen(state.config) ? "" : "none";
    }
  }
}

function buildModelSuggestions() {
  const dl = h("datalist", { id: "openrouter-model-suggestions" });
  OPENROUTER_MODEL_SUGGESTIONS.forEach((m) => {
    dl.appendChild(h("option", { value: m }));
  });
  return dl;
}

$("#save-settings").addEventListener("click", async () => {
  const statusEl = $("#settings-status");
  setStatus(statusEl, "Guardando…");
  const btn = $("#save-settings");
  btn.disabled = true;
  try {
    const payload = validateConfig(state.config);
    state.config = await api("/api/config", { method: "POST", body: JSON.stringify(payload) });
    snapshotView("settings");
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
