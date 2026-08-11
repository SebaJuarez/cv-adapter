"""Router del CV maestro (lectura y guardado)."""

from typing import Any, Dict

from fastapi import APIRouter, HTTPException

from src.config import load_config
from src.llm_node import extract_achievement_facts
from src.merge import validate_master_cv_structure
from src.storage import load_master_cv, save_master_cv

from ..deps import MASTER_CV_PATH
from ..schemas import CVDocumentIn, ExtractFactsIn

router = APIRouter(tags=["master-cv"])


def _empty_master() -> Dict[str, Any]:
    return {
        "cv": {
            "name": "",
            "location": "",
            "email": "",
            "phone": "",
            "social_networks": [],
            "sections": {
                "summary": [],
                "experience": [],
                "projects": [],
                "skills": [],
            },
        },
        "design": {"theme": load_config()["rendercv_theme"]},
    }


@router.get("/api/master-cv")
def get_master_cv() -> Dict[str, Any]:
    master = load_master_cv(MASTER_CV_PATH)
    return master if master is not None else _empty_master()


@router.post("/api/master-cv")
def save_master_cv_route(payload: CVDocumentIn) -> Dict[str, Any]:
    data = payload.as_dict()
    errors = validate_master_cv_structure(data)
    if errors:
        raise HTTPException(status_code=400, detail=errors)
    save_master_cv(data, MASTER_CV_PATH)
    return {"ok": True}


@router.post("/api/master/extract-facts")
def extract_facts(payload: ExtractFactsIn) -> Dict[str, Any]:
    """Estructura un bullet legacy en `facts` (botón "enriquecer este
    bullet", F2). El LLM propone y verifica contra el texto fuente; si el
    proveedor falla devuelve facts vacíos (degradación con gracia) y el
    usuario completa los campos a mano.
    """
    text = payload.text.strip()
    if not text:
        raise HTTPException(
            status_code=422,
            detail="El bullet está vacío: no hay nada que estructurar.",
        )
    facts = extract_achievement_facts(text, load_config())
    return {"facts": facts}
