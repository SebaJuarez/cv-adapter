# Spec: F6 — Generación asistida inline (variante nueva bajo aprobación)

Especifica la fase 6 del doc funcional (`docs/funcional_logros_variantes.md` §6.6).
Desvía una parte del doc funcional: **el tema de API key queda resuelto con la
decisión tomada el 2026-08-12 — la generación funciona con el proveedor activo**
(Ollama local o API remota), por lo que no se exige API key ni se redirige a
Configuración por "falta de key". Actualizar AGENTS.md y el §6.6 en consecuencia.

## Objective

Cuando el target no tiene una variante `approved` para el ángulo detectado por la
selección (o el usuario quiere probar una redacción nueva desde el selector F3),
un botón en la misma tarjeta del bullet genera una redacción nueva **sin salir de
la vista de aplicación**. El resultado se muestra lado a lado con la redacción
actual, los términos técnicos no verificados contra los `facts` del logro se
resaltan, y el usuario elige entre **Usar y guardar como variante nueva**,
**Usar solo esta vez**, o **Descartar**.

Criterios de éxito (testeables):

1. Un bullet cuyo slot es un achievement permite el botón de generar **solo** si
   la selección tiene ángulo preferido para ese slot (`preferred_angles`) y el
   achievement no tiene ninguna variante `approved` con ese ángulo (o ninguno
   aprobado en absoluto). Sin ángulo preferido → sin botón.
2. El popover F3 (selector de variantes) agrega al final "Generar otra
   redacción..." que abre el mismo flujo con elección de ángulo (los 9 de
   `VALID_ANGLES`), aun cuando ya existan variantes aprobadas.
3. Generación exitosa → comparación lado a lado (texto actual vs. propuesta) con
   términos no verificados resaltados (chips estilo keyword report, color ámbar).
4. "Usar y guardar como variante nueva": reemplaza el texto del bullet en el
   target, agrega la variante (`status: approved`, `source: generated`) al
   achievement en el master en memoria y marca el master como sucio para que el
   POST `/api/master-cv` existente la persista. Persistido → el próximo merge la
   puede volver a emitir (representativa o por ángulo).
5. "Usar solo esta vez": reemplaza el texto del bullet en el target sin tocar el
   master. No contamina el banco de variantes.
6. "Descartar": no cambia nada.
7. Fallo del proveedor (Ollama caído / key inválida / timeout): el botón muestra
   toast con el error del proveedor y un enlace a Configuración para cambiarlo.
   El resto del target queda intacto (degradación con gracia, nunca rompe el
   pipeline).
8. Todos los tests existentes siguen pasando; hay tests nuevos para la
   generación y verificación de términos.

## Tech Stack

- Backend: FastAPI + `src/llm_node.py` (`_call_llm` + `_verify_facts`), `src/achievements.py` (`facts_corpus_parts`, `normalize_angles`, `variant_status`).
- Frontend: JS plano (`components.js`, `state.js`, `api.js`, `notify.js`), sin build step.
- Sin dependencias nuevas (openai/httpx ya están).

## Commands

- Tests: `pytest`
- Web: `uvicorn app:app --reload` → http://127.0.0.1:8000

## Project Structure

- `src/llm_node.py` → `generate_variant_text()` (función pelada, reutilizable por tests).
- `api/routers/variants.py` → `POST /api/variants/generate` (router nuevo, registro en `api/main.py`).
- `api/schemas.py` → modelos del payload.
- `frontend/js/components.js` → botón en `highlight-row` (línea ~396), opción en `toggleVariantPopover` (~749), modal de comparación.
- `frontend/js/api.js` / `notify.js` → llamada + toast de error.
- `docs/funcional_logros_variantes.md` + `AGENTS.md` → actualizar §6.6 y roadmap al terminar.

## Code Style

- Español en prompts, UI, docstrings, commits y mensajes.
- Mismo patrón defensivo que `_verify_facts` / `_verify_match_reason`: el LLM propone, el código verifica; fallo → degradación con gracia.
- Estructura de variante (compatible con `validate_achievements_structure`):

```yaml
- id: ach_...
  facts: { action: "...", tools: [python], scope: "...", outcomes: [...] }
  variants:
    - id: v_...
      text: "..."
      angle: [velocidad_entrega]
      status: approved
      source: generated   # "manual" | "imported" | "generated"
      used_count: 0
      created_at: "2026-08-12T..."
```

## Testing Strategy

- `tests/test_generate_variant.py` (backend nuevo): mock de `_call_llm`.
  - Términos: uno verificado contra corpus del logro → no aparece en `unverified_terms`; uno ajeno → aparece.
  - Fallo de proveedor → error claro propagable a 502 (nunca excepción cruda).
  - Texto vacío del LLM → tratado como fallo.
  - Búsqueda del achievement por id (no existe → 422).
- Frontend: sin framework → checklist manual en navegador (como F5), no automatizable hoy.
- Regresión: `pytest` completo (267 tests actuales).

## Boundaries

- Always: invariantes del repo — el LLM nunca escribe el YAML final por su cuenta (la variante entra al master SOLO con clic "Usar y guardar" y el POST `/api/master-cv` existente); verificación de términos contra la fuente; `strip_internal_keys` antes de guardar; página de límites por código.
- Ask first: nuevas dependencias, cambios de schema de achievements, cambios en `merge.py`/`selection.py`.
- Never: inventar `facts`/métricas en la redacción generada; escribir en el master (o en `master_cv.yaml` en disco) sin aprobación humana explícita; bloquear el pipeline si el proveedor falla.

## Open Questions

- Ícono visual del botón de generar: decisión de implementación (se reusa la línea visual de `btn-icon`).
- "Usar y guardar" con términos no verificados: se permiten (la aprobación es humana y el usuario ve el resaltado). Registrado como comportamiento, no como pregunta.
- Hallazgo de QA (2026-08-12, corrida real con gemini-3.6-flash): la fase estratégica no produjo `preferred_angles` en el master real del usuario → el botón ✏ no aparece hasta que el modelo proponga ángulos (comportamiento correcto por diseño, decisión cerrada el 2026-08-12).

## Detalle técnico del diseño

### Backend — `generate_variant_text()` en `src/llm_node.py`

```
entradas: achievement (facts + variantes existentes), ángulo objetivo, texto actual del slot, contexto JD (snippet), config
1. corpus verificado = facts_corpus_parts(achievement) + textos de variantes existentes + texto actual
2. schema de salida: { text: str, tech_terms: [str] }
3. prompt: instruye a reescribir A PARTIR de los facts (jamás inventar
   métricas/tools), orientado al ángulo, apegado al contexto del JD si se dio
4. por cada término de tech_terms: verificado = keyword_in_text(term, corpus)
   (mismo verificador que usa _verify_facts)
5. devuelve { text, unverified_terms: [term, ...] }  # no verificado → resaltado, no descartado
fallo del proveedor / texto vacío → raise LLMError con mensaje legible
```

Verificación de términos: para que "una variante sinónima" valga igual que en
keywords ATS, usar `keyword_in_text` (ya resuelve variantes de `SYNONYMS`).

### Router nuevo — `api/routers/variants.py`

`POST /api/variants/generate` — payload: `{ angle, facts, variant_texts, current_text, jd_snippet }`
- El frontend manda los hechos y redacciones actuales del logro (mismo
  patrón que `/api/master/extract-facts`: el master del disco puede
  diferir de la edición en memoria sin guardar). El servidor NO replica
  el master ni busca por `ach_id` — desviación de diseño aprobada en el
  plan, elimina el 404 de la primera versión de esta spec.
- `jd_snippet` opcional (el frontend reusa `getJDSnippet`); si falta, se
  genera igual (el prompt solo con facts).
- 422 si faltan datos mínimos (ángulo vacío o logro sin contenido);
  200 → `{ text, unverified_terms }`; fallo de proveedor → 502 con
  `detail` legible.

### Frontend — `components.js`

- Detección: para cada bullet del target, `slotIdx = entry._src_slot_map[i]`;
  ángulo preferido = `ctx.selection.selected_experience[idx].preferred_angles[slotIdx]`
  (o projects); achievement del master via `_src_variant_map`. Condición del
  botón: existe preferred_angle Y no hay variante `approved` con ese ángulo
  (o ninguna variante approved). Sin preferred_angle → oculto.
- Botón: `btn-icon` junto al `⇄` existente en `highlight-row`.
- Popover F3: al final del menú, opción separadora "Generar otra redacción..."
  → mini-menú con los 9 ángulos (`ANGLE_LABELS`), siempre disponible (aunque
  haya variantes).
- Modal comparación: sección izquierda "Actual" (texto del slot), derecha
  "Propuesta" (texto generado) con chips ámbar por término no verificado
  (reusa estética del keyword report). Botones: "Usar y guardar como variante
  nueva" (primario), "Usar solo esta vez", "Descartar" (ghost).
  - Ambos "Usar...": `entry.highlights[i] = texto`; `_src_variant_map[slotIdx].variant_id`
    = id de la variante (nueva o la misma generada). "Usar y guardar" además:
    agrega variante al achievement del master (id nuevo via `uid("v")`,
    `created_at` ISO, `status: approved`, `source: generated`) y marca master
    sucio (para que el guardado global lo persista con el POST existente).
- Estado intermedio del botón: "Generando..." deshabilitado mientras corre la
  petición (evita doble envío).