"""Llamada a Ollama (modelo local) con salida estructurada para seleccionar
qué contenido del CV maestro matchea con la oferta.

Clave anti-alucinación: el LLM NUNCA genera el YAML final. Solo devuelve
índices que apuntan a texto que ya existe en master_cv.yaml. El texto en sí
es copiado por código Python determinístico en merge.py.

`generate_selection()` es la función "pelada" (sin LangGraph), reutilizada
tanto por el nodo del grafo (CLI) como por el endpoint /api/generate de la
app web — así la lógica de llamar a Ollama vive en un solo lugar.
"""
import json
from typing import Any, Dict, Optional

import ollama

from .config import load_config
from .prompts import build_selection_schema, build_system_prompt
from .state import CVState


def generate_selection(
    master_cv: Dict[str, Any],
    job_description: str,
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Llama a Ollama y devuelve el dict de selección ya parseado.
    Levanta RuntimeError con un mensaje claro si algo falla (Ollama caído,
    modelo no encontrado, JSON inválido, etc.) — quien la llama decide qué
    hacer con el error (el nodo lo guarda en el state, la API lo devuelve
    como HTTP 502).
    """
    config = config or load_config()
    system_prompt = build_system_prompt(config)
    schema = build_selection_schema(config)

    user_prompt = (
        "### master_cv (YAML parseado a JSON) ###\n"
        f"{json.dumps(master_cv, ensure_ascii=False, indent=2)}\n\n"
        "### job_description ###\n"
        f"{job_description}\n\n"
        "Devolvé SOLO el JSON de selección según el schema indicado en el system prompt."
    )

    raw_content = ""
    try:
        response = ollama.chat(
            model=config["ollama_model"],
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            format=schema,  # Structured Outputs (Ollama >= 0.5)
            options={
                "temperature": 0,  # determinismo: nada de creatividad acá
                "num_ctx": 8192,   # master_cv + JD pueden ser largos
            },
        )
        raw_content = response["message"]["content"]
        return json.loads(raw_content)

    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"El LLM no devolvió JSON válido: {e}\nContenido crudo:\n{raw_content}"
        ) from e
    except Exception as e:
        raise RuntimeError(f"Error llamando a Ollama ({config['ollama_model']}): {e}") from e


def generate_selection_node(state: CVState) -> CVState:
    """Wrapper para el grafo LangGraph (usado por main.py / CLI)."""
    if state.get("error"):
        return state
    try:
        state["llm_selection"] = generate_selection(
            state["master_cv_raw"], state["job_description"]
        )
        state["error"] = None
    except RuntimeError as e:
        state["error"] = str(e)
        state["llm_selection"] = {}
    return state