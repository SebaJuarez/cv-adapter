"""Router de generación: crear el CV target para una oferta y regenerar secciones."""

from typing import Any, Dict

from fastapi import APIRouter, HTTPException

from src.config import load_config
from src.history import add_run
from src.merge import estimate_page_overflow, extract_bullet_variants
from src.retrieval.keywords import _corpus_text, extract_keywords
from src.retrieval.sparse import keyword_in_text
from src.services.generation import generate_cv, regenerate_section
from src.storage import load_master_cv

from ..deps import MASTER_CV_PATH, RUNS_PATH
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
        target_cv, selection, keyword_report, variant_usage = generate_cv(
            master_cv,
            payload.job_description,
            manual_keywords=payload.manual_keywords,
            config=config,
            force=payload.force,
        )
    except Exception as e:
        # Exception (no solo RuntimeError): fallos de descarga de modelos,
        # errores de torch, etc. deben llegar al usuario como 502 legible.
        raise HTTPException(status_code=502, detail=str(e))

    # Registro automático de la corrida en el historial (sin PDF todavía).
    # La traza de variante por bullet se persiste con la corrida.
    run = add_run(
        payload.job_description,
        keyword_report,
        selection=selection,
        manual_keywords=payload.manual_keywords,
        variant_usage=variant_usage,
        bullet_variants=extract_bullet_variants(target_cv),
        path=RUNS_PATH,
    )

    return {
        "target_cv": target_cv,
        "selection": selection,
        "master_cv": master_cv,
        "keyword_report": keyword_report,
        "page_estimate": estimate_page_overflow(target_cv, config),
        "run_id": run["run_id"],
    }


@router.post("/api/preview-keywords")
def preview_keywords(payload: JobDescriptionIn) -> Dict[str, Any]:
    """Preview en vivo: detecta keywords del JD sin instanciar el
    pipeline completo — solo extract_keywords (diccionario + abiertas + 
    manuales), sin modelos, sin LLM, sin cache ni historial."""
    master_cv = _require_master()
    config = load_config()
    corpus = _corpus_text(master_cv)
    # Mismas fuentes que la corrida real (selection.py + merge.py): las fijas
    # de Configuración (config.custom_keywords) y las manuales del payload.
    # extract_keywords normaliza y deduplica, así que concatenar es seguro.
    custom_keywords = list(config.get("custom_keywords") or []) + list(
        payload.manual_keywords or []
    )
    keywords, _ = extract_keywords(
        payload.job_description,
        master_corpus=corpus,
        custom_keywords=custom_keywords,
    )
    # Flag por keyword: si existe (o su sinónimo) en el master. Misma fuente
    # única de sinónimos que el resto del pipeline (SYNONYMS en sparse.py).
    in_master = {kw: keyword_in_text(kw, corpus) for kw in keywords}
    return {"keywords_detected": keywords, "in_master": in_master}


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
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))

    return {"entries": entries, "selection": section_selection}
