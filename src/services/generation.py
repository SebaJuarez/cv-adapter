"""Servicios de generación: orquestan el pipeline completo (IR + LLM + merge).

Estas funciones son la capa de aplicación: validan y encadenan los pasos del
pipeline sin saber nada de HTTP. Los routers de api/ solo traducen requests
en llamadas a estos servicios (y excepciones en HTTP errors).

Reusadas por la web (api/routers/generate.py) para que el comportamiento sea
idéntico en todos los endpoints (generar, regenerar sección, renderizar).
"""

from typing import Any, Dict, List, Optional

from ..config import load_config
from ..llm_node import generate_section_selection, generate_selection
from ..merge import build_section_entries, build_target_cv
from ..retrieval.keywords import _corpus_text, build_keyword_report


def generate_cv(
    master_cv: Dict[str, Any],
    job_description: str,
    manual_keywords: Optional[List[str]] = None,
    config: Optional[Dict[str, Any]] = None,
    force: bool = False,
):
    """Genera el CV target completo para una oferta.

    Encadena: selección (IR + LLM estratégico) -> merge determinístico ->
    keyword report ATS. Devuelve (target_cv, selection, keyword_report,
    variant_usage) — `variant_usage` mapea `id` de variante a cantidad de
    veces que merge la emitió en el target (F2, para used_count).

    Con `force=True` se saltea el cache de selección (P0.1) y se
    recalcula la fase IR completa.
    """
    config = config or load_config()
    variant_usage: Dict[str, int] = {}
    selection = generate_selection(master_cv, job_description, config, force=force)
    target_cv = build_target_cv(
        master_cv,
        selection,
        config,
        job_description=job_description,
        manual_keywords=manual_keywords or [],
        variant_usage=variant_usage,
    )
    keyword_report = build_keyword_report(
        master_cv,
        target_cv,
        job_description,
        custom_keywords=config.get("custom_keywords"),
        master_corpus=_corpus_text(master_cv),
    )
    return target_cv, selection, keyword_report, variant_usage


def regenerate_section(
    master_cv: Dict[str, Any],
    job_description: str,
    section_name: str,
    config: Optional[Dict[str, Any]] = None,
    force: bool = False,
):
    """Regenera UNA sección del target (experience/projects/skills).

    Devuelve (entries, section_selection).
    """
    config = config or load_config()
    section_selection = generate_section_selection(
        master_cv, job_description, section_name, config, force=force
    )
    entries = build_section_entries(master_cv, section_name, section_selection, config)
    return entries, section_selection
