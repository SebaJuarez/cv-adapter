"""Llamada a Ollama (modelo local) con salida estructurada.

Fase 5: El LLM ya NO hace retrieval, NO elige summary, NO detecta keywords.
Su única tarea es redactar match_reasons en lenguaje natural fluido sobre
bullets YA seleccionados por IR. Un verificador liviano descarta cualquier
match_reason que mencione algo no presente en el bullet ni en el JD.

Clave anti-alucinación: el LLM NUNCA genera el YAML final. Solo devuelve
match_reasons anclados a contenido que YA existe en master_cv.yaml.
"""

import json
import re
from typing import Any, Dict, Optional

import ollama

from .config import load_config
from .prompts import (
    build_section_schema,
    build_section_system_prompt,
    build_selection_schema,
    build_system_prompt,
)
from .selection import get_selection_engine
from .state import CVState


def _call_ollama(system_prompt: str, user_prompt: str, schema: Dict[str, Any], config: Dict[str, Any]) -> Dict[str, Any]:
    raw_content = ""
    try:
        response = ollama.chat(
            model=config["ollama_model"],
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            format=schema,
            options={"temperature": 0, "num_ctx": 8192},
        )
        raw_content = response["message"]["content"]
        return json.loads(raw_content)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"El LLM no devolvió JSON válido: {e}\nContenido crudo:\n{raw_content}") from e
    except Exception as e:
        raise RuntimeError(f"Error llamando a Ollama ({config['ollama_model']}): {e}") from e


def _build_strategic_prompt(
    master_cv: Dict[str, Any],
    job_description: str,
    ir_selection: Dict[str, Any],
) -> str:
    """Construye el user prompt para la fase estratégica del LLM.

    El LLM solo recibe JD + bullets ya seleccionados por IR.
    Su única tarea: redactar match_reasons.
    """
    sections = master_cv.get("cv", {}).get("sections", {})

    selected_experience = []
    for item in ir_selection.get("selected_experience", []):
        idx = item.get("index")
        if idx is not None and 0 <= idx < len(sections.get("experience", [])):
            entry = sections["experience"][idx]
            highlights = entry.get("highlights", [])
            h_text = "\n    - ".join(h for h in highlights if isinstance(h, str))
            selected_experience.append(
                f"  [{idx}] {entry.get('company', '')} - {entry.get('position', '')}\n    - {h_text}"
            )

    selected_projects = []
    for item in ir_selection.get("selected_projects", []):
        idx = item.get("index")
        if idx is not None and 0 <= idx < len(sections.get("projects", [])):
            entry = sections["projects"][idx]
            highlights = entry.get("highlights", [])
            h_text = "\n    - ".join(h for h in highlights if isinstance(h, str))
            selected_projects.append(
                f"  [{idx}] {entry.get('name', '')}\n    - {h_text}"
            )

    return (
        "### job_description ###\n"
        f"{job_description}\n\n"
        "### experiencias seleccionadas por el motor de búsqueda ###\n"
        f"{'\n'.join(selected_experience)}\n\n"
        "### proyectos seleccionados por el motor de búsqueda ###\n"
        f"{'\n'.join(selected_projects)}\n\n"
        "Devolvé SOLO el JSON de match_reasons según el schema."
    )


def _verify_match_reason(
    match_reason: str,
    bullet_text: str,
    job_description: str,
) -> bool:
    """Verificador liviano anti-alucinación para match_reasons del LLM.

    Extrae palabras sustantivas (longitud >= 4, no stopwords comunes) del
    match_reason y verifica que cada una aparezca en el bullet_text o en
    el job_description. Si alguna palabra no aparece en ninguno de los dos,
    el match_reason se considera alucinado y se descarta.
    """
    if not match_reason or not isinstance(match_reason, str):
        return False

    # Stopwords mínimas para el verificador (evita descartar por preposiciones)
    stopwords = {
        "para", "con", "desde", "hasta", "entre", "sobre", "bajo", "ante",
        "tras", "durante", "según", "mediante", "excepto", "salvo", "contra",
        "mientras", "aunque", "porque", "pues", "como", "cuando", "donde",
        "por", "para", "sin", "sobre", "tras", "ante", "bajo", "desde",
        "hacia", "hasta", "entre", "con", "para", "por", "sin", "sobre",
        "the", "and", "for", "with", "from", "into", "through", "during",
        "before", "after", "above", "below", "between", "under", "over",
        "about", "than", "then", "them", "these", "those", "being", "having",
        "doing", "this", "that", "they", "been", "their", "what", "when",
        "where", "why", "how", "all", "any", "both", "each", "few", "more",
        "most", "other", "some", "such", "only", "own", "same", "so", "too",
        "very", "can", "just", "should", "now", "also", "well", "very",
        "will", "would", "could", "should", "may", "might", "must", "shall",
        "que", "cual", "quien", "cuyo", "donde", "cuando", "como", "porque",
        "aunque", "mientras", "ademas", "entonces", "asi", "tambien", "tampoco",
        "sino", "pero", "mas", "luego", "después", "antes", "siempre", "nunca",
        "solo", "mismo", "tal", "cada", "todo", "toda", "todos", "todas",
        "alguno", "alguna", "algunos", "algunas", "ninguno", "ninguna",
        "mucho", "mucha", "muchos", "muchas", "poco", "poca", "pocos", "pocas",
        "otro", "otra", "otros", "otras", "mismo", "misma", "mismos", "mismas",
        "tan", "tanto", "tanta", "tantos", "tantas", "cómo", "dónde", "cuándo",
        "cuál", "quién", "porqué", "mas", "más", "menos", "muy", "bastante",
        "demasiado", "casi", "aproximadamente", "alrededor", "cerca", "lejos",
        "aquí", "allí", "ahí", "acá", "allá", "arriba", "abajo", "dentro",
        "fuera", "encima", "debajo", "delante", "detrás", "junto", "mediante",
        "excepto", "salvo", "menos", "exceptuando", "incluyendo", "según",
    }

    # Extraer palabras sustantivas candidatas (>= 4 caracteres, alfabéticas)
    words = set(re.findall(r"\b[a-záéíóúñ]{4,}\b", match_reason.lower()))
    if not words:
        return True  # Frase muy corta, aceptamos por defecto

    combined = (bullet_text + " " + job_description).lower()

    for w in words:
        if w in stopwords:
            continue
        if w not in combined:
            return False
    return True


def generate_selection(
    master_cv: Dict[str, Any],
    job_description: str,
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Pipeline completo: IR + LLM estratégico (solo match_reasons).

    1. SelectionEngine hace retrieval híbrido (rápido, determinístico).
       Resuelve summary_index, keywords_detected, y match_reasons determinísticos.
    2. LLM estratégico redacta match_reasons en lenguaje natural.
    3. Verificador liviano descarta alucinaciones; fallback al match_reason IR.
    """
    config = config or load_config()

    # --- Fase 1: IR (rápido, determinístico) ---
    engine = get_selection_engine(config)
    ir_selection = engine.select(master_cv, job_description)

    # --- Fase 2: LLM Estratégico (solo match_reasons) ---
    system_prompt = build_system_prompt(config)
    schema = build_selection_schema(config)
    user_prompt = _build_strategic_prompt(master_cv, job_description, ir_selection)

    try:
        llm_output = _call_ollama(system_prompt, user_prompt, schema, config)
    except RuntimeError:
        # Si el LLM falla, usamos solo la selección IR (graceful degradation)
        llm_output = {}

    # --- Merge: IR + LLM ---
    final_selection = dict(ir_selection)

    # Match reasons: el LLM puede mejorar los que ya tiene IR
    for section_key in ["selected_experience", "selected_projects"]:
        llm_reasons = {item["index"]: item.get("match_reason", "")
                       for item in llm_output.get(section_key, [])
                       if "index" in item}
        for item in final_selection.get(section_key, []):
            idx = item["index"]
            if idx in llm_reasons and llm_reasons[idx]:
                # Verificador anti-alucinación
                bullet_text = ""
                sections = master_cv.get("cv", {}).get("sections", {})
                if section_key == "selected_experience":
                    entries = sections.get("experience", [])
                    if 0 <= idx < len(entries):
                        bullet_text = " ".join(str(h) for h in entries[idx].get("highlights", []))
                elif section_key == "selected_projects":
                    entries = sections.get("projects", [])
                    if 0 <= idx < len(entries):
                        bullet_text = " ".join(str(h) for h in entries[idx].get("highlights", []))

                if _verify_match_reason(llm_reasons[idx], bullet_text, job_description):
                    item["match_reason"] = llm_reasons[idx]
                # Si falla la verificación, se conserva el match_reason determinístico de IR

    return final_selection


def generate_section_selection(
    master_cv: Dict[str, Any],
    job_description: str,
    section_name: str,
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Igual que generate_selection, pero acotado a UNA sola sección.

    Usado por el botón 'Regenerar esta sección' de la UI.
    """
    config = config or load_config()

    # Fase IR para una sola sección (singleton, reutiliza modelos en memoria)
    engine = get_selection_engine(config)
    ir_selection = engine.select_section(master_cv, job_description, section_name)

    # Para skills/education no hay match_reasons que mejorar con LLM
    if section_name not in ("experience", "projects"):
        return ir_selection

    # Fase LLM: solo match_reasons para la sección regenerada
    system_prompt = build_section_system_prompt(config, section_name)
    schema = build_section_schema(config, section_name)

    sections = master_cv.get("cv", {}).get("sections", {})
    selected_items = []
    for item in ir_selection.get(f"selected_{section_name}", []):
        idx = item.get("index")
        if idx is not None and 0 <= idx < len(sections.get(section_name, [])):
            entry = sections[section_name][idx]
            highlights = entry.get("highlights", [])
            h_text = "\n    - ".join(h for h in highlights if isinstance(h, str))
            label = entry.get("company", "") or entry.get("name", "")
            selected_items.append(
                f"  [{idx}] {label}\n    - {h_text}"
            )

    user_prompt = (
        "### job_description ###\n"
        f"{job_description}\n\n"
        f"### {section_name} seleccionados por el motor de búsqueda ###\n"
        f"{'\n'.join(selected_items)}\n\n"
        "Devolvé SOLO el JSON de match_reasons según el schema."
    )

    try:
        llm_output = _call_ollama(system_prompt, user_prompt, schema, config)
    except RuntimeError:
        return ir_selection

    # Merge match_reasons con verificación
    llm_reasons = {item["index"]: item.get("match_reason", "")
                     for item in llm_output.get(f"selected_{section_name}", [])
                     if "index" in item}
    for item in ir_selection.get(f"selected_{section_name}", []):
        idx = item["index"]
        if idx in llm_reasons and llm_reasons[idx]:
            entries = sections.get(section_name, [])
            bullet_text = ""
            if 0 <= idx < len(entries):
                bullet_text = " ".join(str(h) for h in entries[idx].get("highlights", []))
            if _verify_match_reason(llm_reasons[idx], bullet_text, job_description):
                item["match_reason"] = llm_reasons[idx]

    return ir_selection


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