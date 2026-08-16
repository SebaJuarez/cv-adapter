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
    optional: true,
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
  // ------------------------------------------------------- knobs avanzados
  // Knobs del motor de retrieval: viven en config.json y afectan el ranking.
  // La validación espeja las reglas de src/config.py (mismos rangos).
  {
    key: "rrf_k",
    label: "k de RRF (fusión de canales)",
    type: "number",
    min: 1,
    group: "advanced",
    hint: "Constante de Reciprocal Rank Fusion. Con ~10-50 bullets por sección conviene k=10-20 (k=60 es para corpus grandes tipo TREC).",
  },
  {
    key: "sparse_weight",
    label: "Peso del canal sparse (BM25)",
    type: "float",
    min: 0,
    step: 0.1,
    group: "advanced",
    hint: "Escala la contribución del canal léxico en la fusión. 0 = canal ignorado.",
  },
  {
    key: "dense_weight",
    label: "Peso del canal dense (embeddings)",
    type: "float",
    min: 0,
    step: 0.1,
    group: "advanced",
    hint: "Escala la contribución del canal semántico. 0 = canal ignorado (más rápido, sin modelos densos).",
  },
  {
    key: "keyword_boost_weight",
    label: "Peso del boost de keywords ATS",
    type: "float",
    min: 0,
    step: 0.1,
    group: "advanced",
    hint: "Cuánto sube el ranking de los bullets que contienen keywords del JD. 0 = desactivado.",
  },
  {
    key: "diversity_lambda",
    label: "Diversidad entre bullets (0–1)",
    type: "float",
    min: 0,
    max: 1,
    step: 0.1,
    group: "advanced",
    hint: "Penaliza bullets redundantes dentro de una entrada. 1.0 = máxima diversidad.",
  },
  {
    key: "negation_penalty",
    label: "Penalización de términos negados",
    type: "float",
    min: 0,
    max: 1,
    step: 0.1,
    group: "advanced",
    hint: "Multiplicador de score para bullets que matchean algo que el JD excluye (\"no se requiere X\"). 1.0 = desactivada.",
  },
  {
    key: "use_reranker",
    label: "Reranker (cross-encoder)",
    type: "boolean",
    group: "advanced",
    hint: "Paso final de re-ranking con un cross-encoder. Apagarlo acelera la selección y evita descargar ese modelo.",
  },
  {
    key: "use_stemming",
    label: "Stemming Snowball (ES/EN)",
    type: "boolean",
    group: "advanced",
    hint: "Reduce palabras a su raíz en el tokenizador BM25. Apagarlo cambia el índice y requiere reconstruirlo.",
  },
  {
    key: "use_hyde",
    label: "HyDE (CV hipotético)",
    type: "boolean",
    group: "advanced",
    hint: "Experimental y opt-in estricto: el LLM redacta un CV ideal para la oferta y se antepone al JD en el canal denso. Solo activalo si el eval harness muestra mejora.",
  },
  {
    key: "max_global_coverage_swaps",
    label: "Máx. swaps de cobertura global",
    type: "number",
    min: 0,
    group: "advanced",
    hint: "Intercambios máximos entre entradas para cubrir keywords críticas del JD (frecuencia ≥ 2). 0 = pasada desactivada.",
  },
  {
    key: "selection_cache_ttl_hours",
    label: "TTL del cache de selección (horas)",
    type: "number",
    min: 0,
    group: "advanced",
    hint: "Horas que un resultado de selección queda cacheado para la misma (oferta, master, config). 0 = sin cache.",
  },
  {
    key: "lines_per_page",
    label: "Líneas estimadas por página",
    type: "number",
    min: 1,
    group: "advanced",
    hint: "Presupuesto de la heurística de una página (aviso no bloqueante; el layout real lo decide Typst según el tema).",
  },
];

function validateConfig(config) {
  const validated = { ...config };
  for (const field of SETTINGS_FIELDS) {
    const value = validated[field.key];
    if (field.type === "number") {
      if (!Number.isInteger(value) || value < (field.min ?? 1)) {
        throw new Error(`"${field.label}" debe ser un número entero mayor o igual a ${field.min ?? 1}.`);
      }
      continue;
    }
    if (field.type === "float") {
      if (typeof value !== "number" || !Number.isFinite(value) || value < (field.min ?? 0) || value > (field.max ?? Infinity)) {
        throw new Error(`"${field.label}" debe ser un número entre ${field.min ?? 0} y ${field.max ?? "∞"}.`);
      }
      continue;
    }
    if (field.type === "boolean") {
      if (typeof value !== "boolean") {
        throw new Error(`"${field.label}" debe ser un booleano (true/false).`);
      }
      validated[field.key] = value;
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
    if (field.optional) {
      validated[field.key] = typeof value === "string" ? value.trim() : "";
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
  const advanced = h("details", { class: "settings-advanced" }, [
    h("summary", {}, "Avanzado — knobs de retrieval"),
  ]);
  const advancedBody = h("div", { class: "settings-advanced-body" });
  advanced.appendChild(advancedBody);
  SETTINGS_FIELDS.forEach((f) => {
    const fieldEl = buildSettingsField(f);
    if (f.group === "advanced") {
      advancedBody.appendChild(fieldEl);
    } else {
      form.appendChild(fieldEl);
    }
  });
  form.appendChild(advanced);
  applyLlmVisibility();
}

function buildSettingsField(f) {
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
    return fieldEl;
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
          const urlInput = document.querySelector('input[data-cfg-key="openai_base_url"]');
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
    return fieldEl;
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
    return fieldEl;
  }
  const input = h("input", {
    type: f.type,
    value: state.config[f.key],
    min: f.min ?? (f.type === "number" ? 1 : null),
    max: f.max ?? null,
    step: f.step ?? (f.type === "number" ? 1 : null),
    "data-cfg-key": f.key,
    ...(f.key === "openai_model" ? { list: "openrouter-model-suggestions" } : {}),
  });
  input.addEventListener("input", () => {
    if (f.type === "float") {
      state.config[f.key] = input.value === "" ? null : Number.parseFloat(input.value);
    } else if (f.type === "number") {
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
  return fieldEl;
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
