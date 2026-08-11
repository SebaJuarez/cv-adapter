# Spec: Fase 3 — Selector de variante en "Nueva aplicación" (doc §6.5)

## Objective

Cerrar el ciclo manual de logros con variantes: durante la vista "Nueva
aplicación", el usuario puede cambiar la redacción de cualquier bullet del CV
generado eligiendo otra variante `approved` del mismo logro, con un gesto
discreto (ícono + popover de un clic) — sin salir de la revisión del target.

El match automático por ángulo (hecho en F2, `preferred_angles`) sigue siendo
el camino principal; este selector es solo el override manual. **Nunca es
bloqueante** (principio 6.1.1): si no hay variantes disponibles, no aparece
ningún ícono.

User stories:
- Como usuario que revisa un CV generado, quiero ver un ícono discreto junto a
  un bullet que tiene más de una redacción aprobada, para poder cambiar la
  redacción en un clic si la elegida automáticamente no me convence.
- Como usuario, quiero ver qué ángulo tiene cada redacción en el popover y
  cuál está usando el CV en ese momento.

## Tech Stack

- Backend: Python/FastAPI (sin cambios de API — solo metadata en memoria en
  `src/merge.py`).
- Frontend: JS plano sin build step (mismo patrón de `components.js`).

## Commands

```
# Servidor
uvicorn app:app --reload

# Tests (suite completa ~2 min)
python -m pytest -q

# Tests del backend afectado (rápidos, sin LLM)
python -m pytest tests/test_merge.py tests/test_achievements.py -q

# Sintaxis JS (no hay test runner de JS en el proyecto)
node --check frontend/js/components.js
```

## Project Structure

```
src/merge.py        → _apply_entry_selection: agrega metadata _src_* por bullet
frontend/js/components.js → renderHighlights: ícono de cambio + popover
frontend/style.css  → estilos del popover y el ícono
tests/test_merge.py → tests de la metadata _src_*
docs/specs/f3_selector_variante.md → esta spec
```

## Code Style

Sin comentarios de código; funciones peladas; ES modules; `h()` para DOM
(mismo patrón que `renderHighlights`). Ejemplo del patrón de ícono/popover:

```js
// components.js — dentro de renderHighlights, solo si ctx.isTarget
const variantBtn = h("button", {
  class: "btn-icon ach-switch", title: "Cambiar redacción",
  "aria-label": "Cambiar redacción", onclick: () => toggleVariantPopover(row, entry, i, ctx),
}, "⇄");
```

## Design (deriva del doc §6.5)

1. **Backend — metadata por bullet en memoria** (`src/merge.py`,
   `_apply_entry_selection`): el merge ya resuelve `(slot, variant)` por slot.
   Agregar al entry del target, SOLO en memoria (los `_src_*` se strip al
   guardar):
   - `_src_slot_map`: `[s_idx, ...]` — el orden efectivo de slots del target
     (el `order` filtrado por `_safe_get`), para mapear bullet i → slot real
     aunque `highlight_order` haya reordenado.
   - `_src_variant_map`: `{str(s_idx): {ach_id, variant_id}}` — solo para
     slots de achievement que emitieron una variante con `id`.
   - No cambia ninguna API, no cambia el YAML guardado, no cambia RenderCV
     (strip_internal_keys ya cubre las claves `_src_*`).
2. **Frontend — mapeo bullet → logro** (en `renderHighlights`): para el
   bullet `i` de una entrada target con `_src_section`/`_src_index`:
   - `slot = entry._src_slot_map?.[i] ?? i`
   - `meta = entry._src_variant_map?.[String(slot)]`
   - entrada origen = `ctx.masterDoc.cv.sections[entry._src_section][entry._src_index]`
   - logro = `entrada.achievements?.find(a => a.id === meta.ach_id)`
   - variantes = logro.variants filter `status === "approved"`
   - Mostrar ícono ⇄ solo si `variantes.length > 1`.
3. **Popover**: div posicionado absoluto sobre la `highlight-row`
   (`position: relative` en el row). Cada opción: chip con `angle` (label
   humanizado) + texto corto de la variante + check si es la actual
   (`variant_id === meta.variant_id`). Un solo popover abierto por vez
   (se cierra el anterior); clic fuera o Escape cierra; al elegir:
   `entry.highlights[i] = variante.text` y se actualiza
   `entry._src_variant_map[String(slot)].variant_id = variante.id`, luego
   `ctx.onRerender()`.
4. **Scope del override**: solo afecta el target en memoria (como editar el
   texto a mano hoy). NO incrementa `used_count` de la variante elegida
   (el `variant_usage` del pipeline ya registró la variante automática; el
   seguimiento del override por corrida queda para Fase 7) y NO reescribe el
   master. Documentado como decisión de scope, no como limitación.
5. **Degradación**: entrada legacy sin achievements, bullet sin metadata, o
   logro sin variantes → sin ícono. `strip_internal_keys` garantiza que el
   YAML final no contamina (invariante existente).

## Testing Strategy

- `tests/test_merge.py` (nuevos): `build_target_cv` con una entrada de
  achievements devuelve `_src_slot_map` y `_src_variant_map` correctos
  (incluyendo orden reordenado por `highlight_order`), y con entrada legacy
  los mapas quedan vacíos/ausentes.
- `tests/test_merge.py`: `strip_internal_keys` elimina las claves nuevas.
- Frontend: sin test runner (realidad del repo) — verificación manual +
  `node --check`. Checklist manual en el plan.

## Boundaries

- Always: correr suite completa antes de commit; mantener invariantes D1/D4
  y el guardarail "el LLM nunca decide, el usuario sí".
- Ask first: cambiar el schema del target guardado, tocar el render,
  agregar dependencias, cambiar API.
- Never: emitir variantes `pending`/`deprecated` en el popover; escribir en
  el master desde el target; romper el flujo de regenerar sección.

## Success Criteria

1. En el target, un bullet cuyo logro tiene ≥2 variantes approved muestra el
   ícono ⇄; legacy/1-variante/sin-metadata no muestran nada.
2. El popover lista SOLO variantes approved (nunca pending/deprecated), con
   ángulo visible y check en la usada.
3. Elegir una variante reemplaza el texto del bullet y el estado se mantiene
   al re-renderizar.
4. `highlight_order` reordenado mapea bullet→logro correctamente (el ícono
   aparece en el bullet correcto).
5. El YAML final guardado/rendereado no contiene claves `_src_*` nuevas.
6. Suite completa en verde + `node --check` sin errores.

## Open Questions / Decisiones

- (Decidido) El override manual no incrementa `used_count` ni persiste
  `variant_id` por corrida → queda para Fase 7 (loop de feedback).
- (Decidido) El ícono aparece solo con >1 variante approved (doc 6.5).
- (Pendiente de validación visual) Posición del popover y humanización de
  los labels de ángulo: se validan en el checklist manual.
