"""Nodo LangGraph: llama a Ollama (modelo local) con salida estructurada
para seleccionar qué contenido del CV maestro matchea con la oferta.

Clave anti-alucinación: el LLM NUNCA genera el YAML final. Solo devuelve
índices que apuntan a texto que ya existe en master_cv.yaml. El texto en sí
es copiado por código Python determinístico en merge.py.
"""
import json

import ollama

from .prompts import SELECTION_JSON_SCHEMA, SYSTEM_PROMPT
from .state import CVState

# Cambiá esto si usás otro tag local, ej "llama3.1:8b" o "llama3.1:8b-instruct-q4_K_M"
OLLAMA_MODEL = "llama3:8b"


def generate_selection_node(state: CVState) -> CVState:
    if state.get("error"):
        return state

    master_cv = state["master_cv_raw"]
    job_description = state["job_description"]

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
            model=OLLAMA_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            format=SELECTION_JSON_SCHEMA,  # Structured Outputs (Ollama >= 0.5)
            options={
                "temperature": 0,  # determinismo: nada de creatividad acá
                "num_ctx": 8192,   # master_cv + JD pueden ser largos
            },
        )
        raw_content = response["message"]["content"]
        selection = json.loads(raw_content)

    except json.JSONDecodeError as e:
        state["error"] = (
            f"El LLM no devolvió JSON válido: {e}\nContenido crudo:\n{raw_content}"
        )
        state["llm_selection"] = {}
        return state
    except Exception as e:  # errores de conexión con Ollama, modelo no encontrado, etc.
        state["error"] = f"Error llamando a Ollama ({OLLAMA_MODEL}): {e}"
        state["llm_selection"] = {}
        return state

    state["llm_selection"] = selection
    state["error"] = None
    return state
