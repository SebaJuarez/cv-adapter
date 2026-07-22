"""Estado compartido entre los nodos del grafo LangGraph.

Usamos un TypedDict simple (en vez de Pydantic) porque LangGraph lo soporta
nativamente y alcanza para este pipeline lineal.
"""
from typing import Any, Dict, Optional, TypedDict


class CVState(TypedDict, total=False):
    # --- Inputs (paths) ---
    master_cv_path: str
    job_description_path: str

    # --- Contenido cargado del disco ---
    master_cv_raw: Dict[str, Any]   # master_cv.yaml ya parseado a dict
    job_description: str            # texto plano de la oferta laboral

    # --- Salida del LLM: SOLO índices/orden, nunca texto libre nuevo ---
    llm_selection: Dict[str, Any]

    # --- CV final fusionado (texto 100% proveniente del master) ---
    target_cv_dict: Dict[str, Any]
    target_cv_path: str

    # --- Control humano-en-el-loop ---
    approved: bool

    # --- Resultado final ---
    output_pdf_path: Optional[str]
    error: Optional[str]