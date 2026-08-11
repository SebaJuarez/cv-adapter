"""Router de importación de CVs viejos (F5, doc §4.2/§6.3).

El pipeline: el frontend sube uno o más CVs (texto pegado, YAML/JSON
RenderCV o PDF) → este router los parsea a bullets, los clusteriza con
embeddings y guarda una sesión de revisión. El usuario resuelve cluster
por cluster en la bandeja y los candidatos se confirman en el master con
el POST /api/master-cv existente — este router NUNCA escribe el master.
"""

from fastapi import APIRouter, HTTPException

from src.config import load_config
from src.importer import (
    ImportSession,
    build_achievement_candidate,
    cluster_bullets,
    consolidate_cluster_facts,
    load_session,
    new_session_id,
    parse_document,
    save_session,
)

from ..deps import IMPORT_SESSIONS_DIR
from ..schemas import (
    ImportClusterizeIn,
    ImportConfirmIn,
    ImportOrphansIn,
    ImportResolveIn,
)

router = APIRouter(tags=["imports"])

_VALID_KINDS = ("text", "yaml", "json", "pdf")
_VALID_ACTIONS = ("merge", "split", "discard")


def _session_payload(session: ImportSession) -> dict:
    return session.to_dict()


def _get_session(session_id: str) -> ImportSession:
    session = load_session(session_id, IMPORT_SESSIONS_DIR)
    if session is None:
        raise HTTPException(status_code=404, detail="Sesión de importación no encontrada.")
    return session


def _require_pending(session: ImportSession, cluster_id: str) -> None:
    if cluster_id not in session.resolutions or not session.cluster(cluster_id):
        raise HTTPException(status_code=404, detail="Cluster no encontrado en la sesión.")
    if session.resolutions[cluster_id]["status"] == "done":
        raise HTTPException(status_code=409, detail="Este cluster ya fue resuelto.")


@router.post("/api/imports/clusterize")
def imports_clusterize(payload: ImportClusterizeIn) -> dict:
    if not payload.files:
        raise HTTPException(status_code=422, detail="No se subió ningún CV.")
    bullets: list[dict] = []
    for file in payload.files:
        if file.kind not in _VALID_KINDS:
            raise HTTPException(status_code=422, detail=f"Formato no soportado: {file.kind!r}.")
        for text in parse_document(file.kind, file.content or ""):
            bullets.append({"text": text, "file": file.name})

    texts = [b["text"] for b in bullets]
    if not texts:
        raise HTTPException(
            status_code=422,
            detail="No se pudo extraer ningún bullet de los archivos subidos.",
        )
    groups = cluster_bullets(texts)
    clusters = [
        {
            "id": f"cl_{idx + 1}",
            "bullet_ids": group,
            "file": bullets[group[0]]["file"],
        }
        for idx, group in enumerate(groups)
        if len(group) > 1
    ]
    orphan_ids = [g[0] for g in groups if len(g) == 1]
    session = ImportSession(new_session_id(), bullets, clusters, orphan_ids)
    save_session(session, IMPORT_SESSIONS_DIR)
    return {"session": _session_payload(session)}


@router.get("/api/imports/session/{session_id}")
def imports_get_session(session_id: str) -> dict:
    return {"session": _session_payload(_get_session(session_id))}


@router.post("/api/imports/session/{session_id}/resolve")
def imports_resolve(session_id: str, payload: ImportResolveIn) -> dict:
    if payload.action not in _VALID_ACTIONS:
        raise HTTPException(status_code=422, detail=f"Acción no válida: {payload.action!r}.")
    session = _get_session(session_id)
    _require_pending(session, payload.cluster_id)
    texts = session.cluster_texts(payload.cluster_id)
    config = load_config()

    if payload.action == "discard":
        session.mark_done(payload.cluster_id)
        save_session(session, IMPORT_SESSIONS_DIR)
        return {"session": _session_payload(session), "candidates": []}

    if payload.action == "merge":
        facts = consolidate_cluster_facts(texts, config)
        candidates = [build_achievement_candidate(texts, facts)]
    else:  # split: cada redacción es un logro distinto
        candidates = [
            build_achievement_candidate([t], consolidate_cluster_facts([t], config))
            for t in texts
        ]
    session.schedule_candidates(payload.cluster_id, candidates)
    save_session(session, IMPORT_SESSIONS_DIR)
    return {"session": _session_payload(session), "candidates": candidates}


@router.post("/api/imports/session/{session_id}/orphans")
def imports_orphans(session_id: str, payload: ImportOrphansIn) -> dict:
    session = _get_session(session_id)
    if session.orphans_done:
        return {"session": _session_payload(session), "candidates": []}
    candidates = []
    for i in session.orphan_ids:
        text = session.bullets[i]["text"]
        candidates.append(
            build_achievement_candidate([text], {"action": text, "tools": [], "scope": "", "outcomes": []})
        )
    session.orphans_done = True
    save_session(session, IMPORT_SESSIONS_DIR)
    return {"session": _session_payload(session), "candidates": candidates}


@router.post("/api/imports/session/{session_id}/confirm")
def imports_confirm(session_id: str, payload: ImportConfirmIn) -> dict:
    session = _get_session(session_id)
    if payload.cluster_id not in session.resolutions:
        raise HTTPException(status_code=404, detail="Cluster no encontrado en la sesión.")
    session.mark_done(payload.cluster_id)
    save_session(session, IMPORT_SESSIONS_DIR)
    return {"session": _session_payload(session)}