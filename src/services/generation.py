"""Servicios de generación: orquestan el pipeline completo (IR + LLM + merge).

Estas funciones son la capa de aplicación: validan y encadenan los pasos del
pipeline sin saber nada de HTTP. Los routers de api/ solo traducen requests
en llamadas a estos servicios (y excepciones en HTTP errors).

Reusadas por la web (api/routers/generate.py) para que el comportamiento sea
idéntico al del CLI (main.py), que arma su propio grafo con las mismas
funciones de src/.
"""

from typing import Any, Dict, List, Optional

from ..config import load_config
from ..llm_node import generate_section_selection, generate_selection
from ..merge import build_section_entries, build_target_cv
from ..retrieval.keywords import build_keyword_report


def generate_cv(
    master_cv: Dict[str, Any],
    job_description: str,
    manual_keywords: Optional[List[str]] = None,
    config: Optional[Dict[str, Any]] = None,
):
    """Genera el CV target completo para una oferta.

    Encadena: selección (IR + LLM estratégico) -> merge determinístico ->
    keyword report ATS. Devuelve (target_cv, selection, keyword_report).
    """
    config = config or load_config()
    selection = generate_selection(master_cv, job_description, config)
    target_cv = build_target_cv(
        master_cv,
        selection,
        config,
        job_description=job_description,
        manual_keywords=manual_keywords or [],
    )
    keyword_report = build_keyword_report(master_cv, target_cv, job_description)
    return target_cv, selection, keyword_report


def regenerate_section(
    master_cv: Dict[str, Any],
    job_description: str,
    section_name: str,
    config: Optional[Dict[str, Any]] = None,
):
    """Regenera UNA sección del target (experience/projects/skills).

    Devuelve (entries, section_selection).
    """
    config = config or load_config()
    section_selection = generate_section_selection(
        master_cv, job_description, section_name, config
    )
    entries = build_section_entries(master_cv, section_name, section_selection, config)
    return entries, section_selection
