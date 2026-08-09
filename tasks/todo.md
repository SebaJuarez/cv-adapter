# Todo: Historial de aplicaciones + keywords faltantes recurrentes

- [x] Tarea 1: Núcleo `src/history.py` + `tests/test_history.py`
  - Acceptance: `add_run` crea registro completo; `update_run` valida estados; agregación
    cuenta/ordena; archivo ausente/corrupto tolerado; título autoextraído; sin red ni LLM.
  - Verify: `pytest tests/test_history.py`
- [x] Tarea 2: API historial (schemas, router, hooks generate/render, deps)
  - Acceptance: GET/PATCH/DELETE runs; GET stats; generate crea run y devuelve `run_id`;
    render actualiza `pdf_path` con `run_id`; 404 en run inexistente.
  - Verify: `pytest` + curl manual
- [x] Checkpoint 1: pytest verde, endpoints OK, flujo generate → render → run con pdf_path
- [x] Tarea 3: Hook CLI en `main.py`
  - Acceptance: corrida CLI crea/actualiza run en `data/run_history.json`.
  - Verify: `python main.py --master data/master_cv.yaml --job data/job_description.txt`
- [x] Tarea 4a: Frontend pestaña "Historial" (tabla + edición + borrado + descarga)
  - Acceptance: tabla con fecha/título/ATS/faltantes/estado; editar título, link, estado,
    notas, fecha; borrar; descargar PDF si existe.
  - Verify: flujo manual en la web
- [x] Tarea 4b: Estadísticas keywords faltantes + wiring `run_id`
  - Acceptance: stats visibles con count, primera/última vez, ofertas, copiar; run_id
    fluye de generate a render.
  - Verify: flujo manual en la web
- [x] Tarea 5: README + verificación final (`pytest` completo + `/api/health`)
