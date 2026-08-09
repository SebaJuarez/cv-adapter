# Plan de implementación: mejora UX/UI del historial + preview + gestión de CVs

## Resumen

Rediseñar la vista de historial para que escale con muchas corridas (filtros,
búsqueda, carga incremental), aclarar la info que se muestra (título de oferta,
score ATS, chips de faltantes), permitir previsualizar la oferta y el CV sin
descargar (modal con pestañas: Oferta / CV / Análisis), guardar el YAML del CV
generado por corrida y poder borrarlo junto con el PDF de forma opt-in.

## Decisiones de arquitectura

- El JD completo se guarda dentro de `run_history.json` (campo `job_description`).
  Simple y atómico con el run; ~KB por corrida. Límite futuro: SQLite si hay miles.
- El YAML del CV generado se guarda por corrida en `data/run_cvs/{run_id}.yaml`
  reusando `save_yaml` de `render_node.py` (ya hace `strip_internal_keys`, respeta
  el gotcha de RenderCV). Hooks: `/api/render` (web) y `main.py` (CLI).
- `extract_offer_title` mejora con heurística determinística (sin LLM): prefijos de
  reclutamiento + selección de segmento más "de título" entre separadores comunes.
- API aditiva: `GET /api/history/runs` gana `q`/`status`/`limit`/`offset` y devuelve
  `total`; nuevos `GET /api/history/runs/{id}`, `GET /api/history/runs/{id}/cv`;
  `GET /api/download-pdf?inline=1`; `DELETE /api/history/runs/{id}?delete_files=1`.
- Borrado de archivos es opt-in (checkbox en el diálogo), default = solo metadata.

## Lista de tareas

### Fase 1: Datos (src/history.py)
- [x] Task 1: campo `job_description` en `add_run`
- [x] Task 2: `extract_offer_title` mejorado
- [x] Task 3: helpers de guardado/lectura de CV por run (`data/run_cvs/`)
- [x] Task 4: `delete_run(run_id, delete_files=False)`

### Checkpoint: Fase 1
- [x] Tests de `src/history.py` pasan

### Fase 2: API
- [x] Task 5: filtros + paginación en `GET /api/history/runs`
- [x] Task 6: `GET /api/history/runs/{id}` (detalle con JD)
- [x] Task 7: `GET /api/history/runs/{id}/cv` (texto del YAML)
- [x] Task 8: `inline=1` en `GET /api/download-pdf`
- [x] Task 9: `delete_files` en `DELETE /api/history/runs/{id}`

### Fase 3: Hooks de guardado del CV por corrida
- [x] Task 10: `/api/render` guarda el YAML del CV
- [x] Task 11: `main.py` (CLI) guarda el YAML del CV

### Checkpoint: Fases 2-3
- [x] `pytest` completo pasa

### Fase 4: Frontend
- [x] Task 12: toolbar con buscador, chips de estado con conteo, total
- [x] Task 13: "Cargar más" (paginación incremental)
- [x] Task 14: modal de detalle con pestañas Oferta / CV / Análisis
- [x] Task 15: tooltips de ATS y chips de faltantes
- [x] Task 16: borrado con checkbox de archivos
- [x] Task 17: casos esquina (PDF roto, corridas viejas, sin resultados, error con reintento)

### Checkpoint: Fase 4
- [x] Verificación manual en navegador (web + `/api/health`)

## Riesgos y mitigaciones

| Riesgo | Impacto | Mitigación |
|--------|---------|------------|
| `run_history.json` crece con JDs largos | Med | Aceptable para uso personal; anotado como futuro SQLite |
| Corridas viejas sin `job_description`/CV | Bajo | Estados "No disponible" en el modal |
| PDF movido/borrado en disco | Bajo | Botón PDF deshabilitado + mensaje claro |
| Romper shape de `/api/history/runs` | Alto | Cambio aditivo (`total` extra), tests actualizados |

## Dudas abiertas

- Ninguna (JD dentro del JSON aprobado; paginación "Cargar más" aprobada).
