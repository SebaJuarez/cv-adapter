"""Router de historial: corridas registradas y estadísticas de keywords.

Las corridas se crean automáticamente en cada generación (`/api/generate`) y
se actualizan al renderizar el PDF (`/api/render` con `run_id`). Este router
expone la consulta (con filtros y paginación), el detalle de una corrida (con
el texto de la oferta), el CV guardado para previsualizar, la edición del
seguimiento de la aplicación y la agregación de keywords faltantes del master.
"""

from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Response

from src import history as history_mod

from ..deps import RUNS_PATH
from ..schemas import RunUpdateIn

router = APIRouter(tags=["history"])

# Tamaño de página por defecto para la lista de corridas.
DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 100


def _load_sorted_runs() -> list[Dict[str, Any]]:
    runs = history_mod.load_runs(RUNS_PATH)
    return sorted(runs, key=lambda r: r.get("created_at", ""), reverse=True)


def _match_query(run: Dict[str, Any], q: str) -> bool:
    ql = q.lower()
    haystack = " ".join(
        (
            str(run.get("offer_title") or "").lower(),
            str(run.get("offer_link") or "").lower(),
        )
    )
    return ql in haystack


def _summarize(run: Dict[str, Any]) -> Dict[str, Any]:
    """Versión liviana del run para la lista (el texto de la oferta se pide
    por detalle: `GET /api/history/runs/{id}`)."""
    return {k: v for k, v in run.items() if k != "job_description"}


@router.get("/api/history/runs")
def list_runs(
    q: str = "",
    status: str = "",
    min_score: Optional[int] = None,
    max_score: Optional[int] = None,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
) -> Dict[str, Any]:
    """Lista de corridas con filtros (`q` por texto, `status`, rango de
    `ats_score` con `min_score`/`max_score`) y paginación.

    `status_counts` cuenta las corridas por estado de aplicación sobre el
    resultado filtrado por `q` (ignora los filtros `status` y de score) para
    que el frontend pueda mostrar chips con conteos.
    """
    runs = _load_sorted_runs()
    if q:
        runs = [r for r in runs if _match_query(r, q)]

    status_counts: Dict[str, int] = {}
    for r in runs:
        st = (r.get("application") or {}).get("status") or "pendiente"
        status_counts[st] = status_counts.get(st, 0) + 1

    if min_score is not None:
        runs = [r for r in runs if int(r.get("ats_score") or 0) >= min_score]
    if max_score is not None:
        runs = [r for r in runs if int(r.get("ats_score") or 0) <= max_score]
    if status:
        runs = [r for r in runs if ((r.get("application") or {}).get("status") or "pendiente") == status]

    total = len(runs)
    limit = max(1, min(limit, MAX_PAGE_SIZE))
    offset = max(0, offset)
    return {
        "runs": [_summarize(r) for r in runs[offset:offset + limit]],
        "total": total,
        "limit": limit,
        "offset": offset,
        "status_counts": status_counts,
    }


@router.get("/api/history/runs/{run_id}")
def get_run(run_id: str) -> Dict[str, Any]:
    """Detalle completo de una corrida (incluye el texto de la oferta)."""
    for run in _load_sorted_runs():
        if run.get("run_id") == run_id:
            return {"run": run}
    raise HTTPException(status_code=404, detail="Corrida no encontrada.")


@router.get("/api/history/runs/{run_id}/cv")
def get_run_cv(run_id: str) -> Response:
    """Texto del CV guardado de una corrida (para previsualizar sin PDF)."""
    cv_yaml = history_mod.load_run_cv(run_id)
    if cv_yaml is None:
        raise HTTPException(status_code=404, detail="No hay CV guardado para esta corrida.")
    return Response(content=cv_yaml, media_type="text/plain; charset=utf-8")


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
def delete_run_route(run_id: str, delete_files: bool = False) -> Dict[str, Any]:
    """Borra la corrida. Con `delete_files=1` borra también el CV guardado y
    el PDF asociado (opt-in; por defecto solo se pierde la metadata)."""
    if not history_mod.delete_run(
        run_id, path=RUNS_PATH, delete_files=delete_files
    ):
        raise HTTPException(status_code=404, detail="Corrida no encontrada.")
    return {"ok": True}


@router.get("/api/history/stats/keywords")
def keyword_stats() -> Dict[str, Any]:
    runs = history_mod.load_runs(RUNS_PATH)
    return {"keywords": history_mod.aggregate_missing_keywords(runs)}
