"""Router del CV maestro (lectura y guardado)."""

from typing import Any, Dict

from fastapi import APIRouter, HTTPException

from src.config import load_config
from src.merge import validate_master_cv_structure
from src.storage import load_master_cv, save_master_cv

from ..deps import MASTER_CV_PATH
from ..schemas import CVDocumentIn

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
