# Spec: Iteración post-QA F6 + proveedor OpenRouter en Configuración

## Objective

Atacar los hallazgos pendientes del QA F6 (`docs/qa_f6_hallazgos.md`) y agregar
una feature nueva: elegir OpenRouter como proveedor desde la UI de Configuración,
para darle al cliente más opciones.

Usuarios: quien genera CVs con cv-adapter y configura el LLM en la UI.

Criterios de éxito:
1. Los botones ✏ (generar versión) y ⇄ (cambiar redacción) aparecen SIEMPRE en
   los bullets del target con logro. Sin ángulo preferido → la generación es
   "genérica" (variante sin ángulo, `angle: ""`), no elige un pseudo-ángulo.
2. El ✏ explica su regla en el tooltip (deja de ser opaco).
3. El error "ángulo desconocido" (no vacío y fuera de `VALID_ANGLES`) responde
   422; el ángulo vacío es válido y representa "genérica".
4. En Configuración: "Proveedor del LLM" incluye OpenRouter como opción
   (guarda `openai` + base_url de OpenRouter automática); el campo de modelo
   de Ollama solo se muestra con proveedor local; los campos remotos solo con
   proveedor remoto. Sin listas de modelos (el ID se escribe, con sugerencias
   vía datalist).

## Alcance

- [x] Hallazgo F6 #5: timeout 30→90s — YA RESUELTO en QA anterior (llm_node.py:407).
- [x] Menor: ángulo inválido no vacío → 422 (hoy 502); ángulo "" = genérica válida.
- [x] UX (decisión usuario 12-ago): ✏ siempre visible; sin ángulo preferido →
      genera "genérica". ⇄ siempre con ≥1 variante approved (incluye
      "Generar otra redacción…").
- [x] UX: tooltip del ✏ explica la regla.
- [x] FEATURE: opción OpenRouter en el selector de proveedor + campos
      condicionales por proveedor en Configuración.

QA navegador (12-ago-2026, completado): vista Configuración con el JS nuevo —
3 opciones de proveedor; con proveedor remoto `ollama_model` queda oculto y los
campos remotos visibles (valores preservados al alternar); al elegir
OpenRouter la URL base se completa sola en el input (`https://openrouter.ai/api/v1`,
fix aplicado en el mismo QA: el change handler ahora escribe el value del input);
campo de modelo con datalist conectado (combobox). No se guardó la config del
usuario durante el QA (persistir con su config real queda a elección del usuario;
el endpoint `/api/config` ya estaba verificado).

## Tech Stack

- Backend: FastAPI. Frontend: JS plano sin build (patrón settings.js / components.js).
- Tests: pytest (backend). Frontend sin test runner (verificación manual).

## Commands

- Tests: `pytest` (suite completa); rápido: `pytest tests/test_variants_api.py tests/test_generate_variant.py`
- Server: `uvicorn app:app --reload` → http://127.0.0.1:8000

## Project Structure

- `api/routers/variants.py` → 422 de ángulo inválido no vacío; permite ""
- `src/llm_node.py` → `generate_variant_text` acepta `angle=""` (prompt genérico)
- `frontend/js/components.js` → ✏/⇄ siempre + títulos + modal "genérica"
- `frontend/js/views/settings.js` → provider OpenRouter + campos condicionales + datalist
- `docs/funcional_logros_variantes.md` §6.5/§6.6 → regla del botón actualizada
- `docs/qa_f6_hallazgos.md` → marcar resueltos
- `AGENTS.md` → sincronizar estado
- `tests/test_variants_api.py` → ajustar/cubrir 422 y genérica

## Design

### 1) 422 ángulo + genérica (backend)

`variants.py`: `angle = payload.angle.strip()`; si `angle and angle not in VALID_ANGLES`
→ 422 con la lista de válidos. `""` pasa (proveedor recibe `""`).
`llm_node.py:426`: `if angle and angle not in VALID_ANGLES` para no romper prompt;
prompt: con `angle=""` → "redacción sin ángulo específico (genérica)" y no cita
`'<vacío>'`. El esquema de salida no cambia.

### 2) ✏ y ⇄ siempre (components.js)

- `variantGenInfo`: ya no retorna `null` por falta de ángulo ni por "covers":
  devuelve `{...info, angle: preferred || ""}`. El botón ✏ (línea 407) se
  renderiza para todo bullet con logro (genInfo no null). Título:
  "Generar versión para [Ángulo]" o "Generar versión genérica" (sin ángulo
  preferido; variante resultante `angle: ""`, etiquetada "genérica").
- `variantSwitchOptions`: `variants.length < 1` (≥1 approved).
- Modal F6: el pane y el título usan "genérica" cuando `angle` es falsy.
- "Usar y guardar": ya guarda `angle: p.genInfo.angle` — con "" queda genérica.

### 3) FEATURE: provider OpenRouter en Configuración (settings.js)

- Select "Proveedor del LLM": ollama / openai / openrouter. El valor guardado
  de "openrouter" es derivado: al elegirlo se setea `llm_provider=openai` +
  `openai_base_url=https://openrouter.ai/api/v1` (persistencia existente, sin
  tocar el despacho `_call_llm`). Al elegir "openai" → base_url vacía (oficial).
  Al dibujar, el select marca "openrouter" si provider=openai y base_url
  contiene "openrouter.ai".
- Campos condicionales (ocultar/mostrar al cambiar provider):
  - ollama → solo `ollama_model` (+ hint).
  - remoto → `openai_api_key`, `openai_base_url` (texto, editable siempre) y
    `openai_model` con `<datalist>` de modelos OpenRouter conocidos (sugerencia,
    texto libre — sin mantenimiento de API).
- El resto de los campos queda igual.

## Testing Strategy

- pytest: 422 ángulo inválido no vacío; ángulo "" pasa a `generate_variant_text`
  (fake recibe ""); se ajusta `test_angulo_vacio_422` (ahora válido).
- Manual: Configuración con OpenRouter → guardar → `/api/config` correcto;
  target con logro de 1 variante → ⇄ y ✏ visibles; ✏ sin ángulo preferido →
  modal "genérica".

## Boundaries

- Always: invariantes del pipeline; textos en español; validar antes de persistir.
- Ask first: dependencias nuevas (NO), claves nuevas de config (NO — la feature
  reusa `llm_provider`/`openai_base_url`), cambios de schema.
- Never: escribir keys fuera de config.json (gitignored); romper configs viejas.

## Success Criteria

1. `angle="escala"` ok; `angle="cualquiera"` → 422; `angle=""` → genera genérica (tests).
2. Bullets del target con logro muestran ✏ y ⇄ siempre; sin ángulo preferido el
   ✏ dice "genérica" y la variante guardada queda `angle: ""` (manual).
3. Configuración: opción OpenRouter con campos condicionales; guardar persiste
   (manual + `/api/config`).
4. `pytest` verde completo.

## Decisiones revisadas (usuario, 2026-08-12)

- Los botones siempre visibles: sin ángulo → "genérica" (no inventar ángulo).
- El ángulo para redactar sale del match del bullet con la oferta (preferred_angles
  cuando el LLM lo detecta; si no, generación genérica).
- Sin lista de modelos vía API: OpenRouter es solo un seleccionable más en el
  proveedor; `ollama_model` solo visible con proveedor local.