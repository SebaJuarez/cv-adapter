# TODO — Mejora UX/UI del historial + preview + gestión de CVs

## Fase 1: Datos (`src/history.py`)
- [x] Task 1: campo `job_description` en `add_run`
- [x] Task 2: `extract_offer_title` mejorado (prefijos + segmento de título)
- [x] Task 3: helpers de guardado/lectura de CV por run (`data/run_cvs/`)
- [x] Task 4: `delete_run(run_id, delete_files=False)`
- [x] Checkpoint: `pytest tests/test_history.py` pasa (34 tests)

## Fase 2: API
- [x] Task 5: filtros + paginación en `GET /api/history/runs` (q, status, limit, offset, total, status_counts)
- [x] Task 6: `GET /api/history/runs/{id}` (detalle con JD; la lista no lo manda)
- [x] Task 7: `GET /api/history/runs/{id}/cv` (texto del YAML)
- [x] Task 8: `inline=1` en `GET /api/download-pdf` + soporte HEAD (fix: FastAPI no agrega HEAD solo)
- [x] Task 9: `delete_files` en `DELETE /api/history/runs/{id}`
- [x] Checkpoint: `pytest tests/test_history_api.py` pasa

## Fase 3: Hooks de guardado del CV por corrida
- [x] Task 10: `/api/render` guarda el YAML del CV (`dump_yaml` en `render_node.py`)
- [x] Task 11: `main.py` (CLI) guarda el YAML del CV
- [x] Checkpoint: `pytest` completo pasa (113 tests)

## Fase 4: Frontend
- [x] Task 12: toolbar con buscador (debounce), chips de estado con conteo, total de corridas
- [x] Task 13: "Cargar más" (paginación incremental, 25 por página)
- [x] Task 14: modal de detalle con pestañas Oferta / CV (iframe PDF, fallback YAML) / Análisis
- [x] Task 15: tooltips de ATS y chips de faltantes (los chips abren el detalle)
- [x] Task 16: borrado con checkbox "Borrar también el PDF y el CV guardado"
- [x] Task 17: casos esquina (PDF roto con HEAD-check, corridas viejas sin JD/CV, sin resultados con "Limpiar filtros", error con "Reintentar", chips ocultos sin corridas)
- [x] Checkpoint: verificación manual (server real: endpoints + HEAD + frontend servido OK)

## Definición de done
- [x] `pytest` completo pasa (113 tests)
- [x] Verificación manual: endpoints con datos reales OK (listado/filtros/detalle/cv 404/inline/HEAD)
