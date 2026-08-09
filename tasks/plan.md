# Plan de implementación: Historial de aplicaciones + keywords faltantes recurrentes

## Resumen

Cada corrida del pipeline (web o CLI) queda registrada en `data/run_history.json`:
fecha, oferta (título autoextraído y editable, link), ATS score, keywords detectadas,
faltantes del master y del target, manuales, path del PDF, y seguimiento de la
aplicación (estado, fecha, notas). Una vista de estadísticas agrega las keywords
que faltan en el master recurrentemente (cuántas ofertas, primera/última vez,
ofertas donde apareció) para decidir qué agregar al master manualmente. La UI es
una pestaña nueva "Historial" en el frontend.

## Decisiones de arquitectura

- **Persistencia**: JSON en `data/run_history.json` (gitignored). Sin dependencias nuevas.
- **Módulo núcleo `src/history.py`**: funciones peladas compartidas por web y CLI
  (invariante AGENTS.md: no duplicar lógica entre `app.py` y `main.py`). Determinístico,
  el LLM no participa.
- **Registro automático**: `/api/generate` crea el run (sin `pdf_path`) y devuelve
  `run_id`; `/api/render` recibe `run_id` opcional y actualiza `pdf_path`. En el CLI,
  hook post-`invoke` en `main()` con los datos del `final_state` (sin tocar el grafo).
  Si el pipeline falla, no se registra.
- **`run_id`**: `{epoch_ms}-{sha1(jd)[:8]}`.
- **No tocar invarianzas**: el historial es solo metadata (JSON), nunca YAML del CV;
  no se agrega nada al master automáticamente.

## Estructura de datos (`data/run_history.json`)

```json
{
  "runs": [
    {
      "run_id": "1754600000000-a1b2c3d4",
      "created_at": "2026-08-09T14:30:00Z",
      "offer_title": "Backend Engineer (Java)",
      "offer_link": null,
      "jd_hash": "a1b2c3d4",
      "ats_score": 72,
      "keywords_detected": ["java", "docker"],
      "missing_in_target": ["kubernetes"],
      "not_in_master": ["terraform", "aws"],
      "not_in_master_frequencies": {"terraform": 3},
      "critical_missing": ["kubernetes"],
      "manual_keywords": ["scrum"],
      "pdf_path": null,
      "application": {
        "status": "pendiente",
        "applied_at": null,
        "notes": ""
      }
    }
  ]
}
```

## API nueva

| Ruta | Método | Qué hace |
|---|---|---|
| `/api/history/runs` | GET | Lista de corridas (últimas primero) |
| `/api/history/runs/{run_id}` | PATCH | Editar `offer_title`, `offer_link`, `application` (status validado, `applied_at`, `notes`) |
| `/api/history/runs/{run_id}` | DELETE | Borrar corrida |
| `/api/history/stats/keywords` | GET | Agregación de keywords faltantes del master |

## Tareas

### Tarea 1: Núcleo `src/history.py` + tests
- `load_runs`/`save_runs` (archivo ausente → `[]`; corrupto → backup `.bak` y `[]`),
  `add_run`, `update_run` (valida estados), `delete_run`, `aggregate_missing_keywords`,
  `extract_offer_title` (primera línea no vacía, truncada a 80 chars).
- Verify: `tests/test_history.py` nuevo; `pytest tests/test_history.py`.
- Archivos: `src/history.py`, `tests/test_history.py`.

### Tarea 2: API + hooks web
- `RunUpdateIn` en `api/schemas.py`, `api/routers/history.py`, registro en `api/main.py`,
  `RUNS_PATH` en `api/deps.py`, `add_run` en `/api/generate`, update de `pdf_path` en
  `/api/render`.
- Verify: `pytest` + curl de los endpoints.
- Archivos: `api/schemas.py`, `api/routers/history.py`, `api/main.py`, `api/deps.py`,
  `api/routers/generate.py`, `api/routers/render.py`.

### Checkpoint 1
- `pytest` verde, endpoints probados con curl, flujo generate → render actualiza `pdf_path`.

### Tarea 3: Hook CLI
- En `main.py`, post-`invoke`: sin error → `add_run(...)` con `final_state`.
- Verify: corrida manual del CLI + inspección del JSON.
- Archivos: `main.py`.

### Tarea 4a: Frontend pestaña "Historial"
- Tab en `index.html` + `js/views/history.js` (tabla, edición, borrado, descarga PDF),
  registro en `js/main.js`.
- Archivos: `frontend/index.html`, `frontend/js/main.js`, `frontend/js/views/history.js` (nuevo),
  `frontend/js/api.js`, `frontend/style.css`.

### Tarea 4b: Estadísticas + wiring `run_id`
- Sección de estadísticas de keywords faltantes + `run_id` en `state.js` y `views/apply.js`.
- Archivos: `frontend/js/views/history.js`, `frontend/js/state.js`, `frontend/js/views/apply.js`.

### Tarea 5: README + verificación final
- Documentar la feature; `pytest` completo + `/api/health`.
- Archivos: `README.md`.

## Riesgos

| Riesgo | Impacto | Mitigación |
|---|---|---|
| JSON corrupto rompe la app | Med | `load_runs` tolerante: backup `.bak` y continúa |
| `run_id` perdido entre generate y render | Bajo | Opcional en `/api/render`; sin él no rompe |
| Títulos autoextraídos feos | Bajo | Editables desde la UI |
| Crecimiento del JSON | Bajo | Uso personal; `delete_run` disponible |

## Orden de commits (conventional, en español)

1. `feat(history): registro de corridas y agregación de keywords faltantes`
2. `feat(api): endpoints de historial y hooks en generate/render`
3. `feat(cli): registrar corrida al final del pipeline`
4. `feat(ui): pestaña de historial con seguimiento de aplicaciones`
5. `feat(ui): estadísticas de keywords faltantes recurrentes`
6. `docs: historial de aplicaciones en README`
