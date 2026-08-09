"""Router de historial: corridas registradas y estadísticas de keywords.

Las corridas se crean automáticamente en cada generación (`/api/generate`) y
se actualizan al renderizar el PDF (`/api/render` con `run_id`). Este router
expone la consulta, edición del seguimiento de la aplicación y la agregación
de keywords faltantes del master a través de todas las ofertas.
"""

from typing import Any, Dict

from fastapi import APIRouter, HTTPException

from src import history as history_mod

from ..deps import RUNS_PATH
from ..schemas import RunUpdateIn

router = APIRouter(tags=["history"])


@router.get("/api/history/runs")
def list_runs() -> Dict[str, Any]:
    runs = history_mod.load_runs(RUNS_PATH)
    runs = sorted(runs, key=lambda r: r.get("created_at", ""), reverse=True)
    return {"runs": runs}


@router.patch("/api/history/runs/{run_id}")
def update_run_route(run_id: str, payload: RunUpdateIn) -> Dict[str, Any]:
    fields = payload.model_dump(exclude_none=True)
    try:
        run = history_mod.update_run(run_id, fields, path=RUNS_PATH)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if run is None:
        raise HTTPException(status_code=404, detail="Corrida no encontrada.")
    return {"run": run}


@router.delete("/api/history/runs/{run_id}")
def delete_run_route(run_id: str) -> Dict[str, Any]:
    if not history_mod.delete_run(run_id, path=RUNS_PATH):
        raise HTTPException(status_code=404, detail="Corrida no encontrada.")
    return {"ok": True}


@router.get("/api/history/stats/keywords")
def keyword_stats() -> Dict[str, Any]:
    runs = history_mod.load_runs(RUNS_PATH)
    return {"keywords": history_mod.aggregate_missing_keywords(runs)}
