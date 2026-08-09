"""Router de generación: crear el CV target para una oferta y regenerar secciones."""

from typing import Any, Dict

from fastapi import APIRouter, HTTPException

from src.config import load_config
from src.services.generation import generate_cv, regenerate_section
from src.storage import load_master_cv

from ..deps import MASTER_CV_PATH
from ..schemas import JobDescriptionIn, RegenerateSectionIn

router = APIRouter(tags=["generate"])


def _require_master() -> Dict[str, Any]:
    master = load_master_cv(MASTER_CV_PATH)
    if master is None:
        raise HTTPException(
            status_code=404,
            detail="Todavía no guardaste tu CV maestro. Completá la sección 'CV maestro' primero.",
        )
    return master


@router.post("/api/generate")
def generate(payload: JobDescriptionIn) -> Dict[str, Any]:
    if not payload.job_description.strip():
        raise HTTPException(status_code=400, detail="Pegá el texto de la oferta laboral.")

    master_cv = _require_master()
    config = load_config()
    try:
        target_cv, selection, keyword_report = generate_cv(
            master_cv,
            payload.job_description,
            manual_keywords=payload.manual_keywords,
            config=config,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))

    return {
        "target_cv": target_cv,
        "selection": selection,
        "master_cv": master_cv,
        "keyword_report": keyword_report,
    }


@router.post("/api/regenerate-section")
def regenerate_section_route(payload: RegenerateSectionIn) -> Dict[str, Any]:
    if payload.section_name not in ("experience", "projects", "skills"):
        raise HTTPException(
            status_code=400, detail="Sección no soportada para regenerar."
        )
    master_cv = _require_master()
    config = load_config()
    try:
        entries, section_selection = regenerate_section(
            master_cv, payload.job_description, payload.section_name, config
        )
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))

    return {"entries": entries, "selection": section_selection}
