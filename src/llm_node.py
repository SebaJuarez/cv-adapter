"""Llamada a Ollama (modelo local) con salida estructurada.

Ahora el pipeline tiene DOS fases:
1. Fase IR (Information Retrieval): SelectionEngine selecciona bullets/experiencias
   usando BM25 + embeddings + cross-encoder. Es rápido, determinístico, y corre local.
2. Fase LLM Estratégica: el LLM solo recibe el JD + bullets ya seleccionados +
   summaries disponibles. Decide summary_index, keywords implícitas, y mejora
   match_reasons. El contexto se reduce de ~15K tokens a ~2K tokens.

Clave anti-alucinación: el LLM NUNCA genera el YAML final. Solo devuelve
índices que apuntan a contenido que YA existe en master_cv.yaml.
"""
import json
from typing import Any, Dict, Optional

import ollama

from .config import load_config
from .prompts import (
    build_section_schema,
    build_section_system_prompt,
    build_selection_schema,
    build_system_prompt,
)
from .retrieval.keywords import _count_keyword_occurrences, _normalize_text, extract_keywords
from .retrieval.sparse import get_synonym_variants
from .selection import get_selection_engine
from .state import CVState


def _verify_match_reason(llm_reason: str, bullet_text: str, jd_text: str) -> bool:
    """Guardarail anti-alucinación para el match_reason que redacta el LLM.

    A diferencia de las keywords ATS (que ya se verifican contra el master_cv
    en merge.py vía _build_verified_keywords), el texto libre de
    `match_reason` no pasaba por ningún chequeo — era la única superficie
    donde el LLM podía generar texto visible sin verificación, algo
    inconsistente con el resto del pipeline.

    Chequeo deliberadamente acotado: si el LLM menciona una tecnología/
    keyword técnica que NO está ni en el bullet ni en el JD (ni en alguna
    variante sinónima), se rechaza el texto completo y se usa el
    match_reason determinístico de IR en su lugar. No intenta validar
    matices de redacción, solo el riesgo real: que el LLM invente una
    tecnología o herramienta que el candidato nunca mencionó.
    """
    mentioned_keywords, _ = extract_keywords(llm_reason)
    if not mentioned_keywords:
        return True  # No menciona ninguna tecnología puntual, no hay nada que verificar

    context = _normalize_text(bullet_text) + " " + _normalize_text(jd_text)
    for kw in mentioned_keywords:
        variants = get_synonym_variants(kw)
        if not any(_count_keyword_occurrences(context, v) > 0 for v in variants):
            return False
    return True


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
    config: Dict[str, Any],
) -> str:
    """Construye el user prompt para la fase estratégica del LLM.

    El LLM ya no recibe TODO el CV. Solo recibe:
    - El JD completo.
    - Los bullets ya seleccionados por IR (resumen).
    - Las variantes de summary disponibles.
    """
    # Extraer bullets seleccionados para mostrar al LLM
    sections = master_cv.get("cv", {}).get("sections", {})
    selected_summary = ""
    summaries = sections.get("summary", [])
    if summaries:
        selected_summary = "\n".join(f"  [{i}] {s}" for i, s in enumerate(summaries))

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

    selected_skills = []
    for idx in ir_selection.get("selected_skills_indices", []):
        if 0 <= idx < len(sections.get("skills", [])):
            s = sections["skills"][idx]
            selected_skills.append(f"  [{idx}] {s.get('label', '')}: {s.get('details', '')}")

    return (
        "### job_description ###\n"
        f"{job_description}\n\n"
        "### summary variants disponibles ###\n"
        f"{selected_summary}\n\n"
        "### experiencias seleccionadas por el motor de búsqueda ###\n"
        f"{'\n'.join(selected_experience)}\n\n"
        "### proyectos seleccionados por el motor de búsqueda ###\n"
        f"{'\n'.join(selected_projects)}\n\n"
        "### skills seleccionadas por el motor de búsqueda ###\n"
        f"{'\n'.join(selected_skills)}\n\n"
        "Devolvé SOLO el JSON de ajustes estratégicos según el schema."
    )


def generate_selection(
    master_cv: Dict[str, Any],
    job_description: str,
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Pipeline completo: IR + LLM estratégico.

    1. SelectionEngine hace retrieval híbrido (rápido, determinístico).
    2. LLM estratégico ajusta summary, keywords implícitas, match_reasons.
    3. Merge de ambas salidas.
    """
    config = config or load_config()

    # --- Fase 1: IR (rápido, determinístico) ---
    engine = get_selection_engine(config)
    ir_selection = engine.select(master_cv, job_description)

    # --- Fase 2: LLM Estratégico (liviano) ---
    system_prompt = build_system_prompt(config)
    schema = build_selection_schema(config)
    user_prompt = _build_strategic_prompt(master_cv, job_description, ir_selection, config)

    try:
        llm_output = _call_ollama(system_prompt, user_prompt, schema, config)
    except RuntimeError:
        # Si el LLM falla, usamos solo la selección IR (graceful degradation)
        llm_output = {}

    # --- Merge: IR + LLM ---
    # El LLM puede ajustar: summary_index, keywords_detected, match_reasons
    # Pero NUNCA puede sobreescribir los índices de experiencia/proyectos/skills
    # (eso lo determinó IR y es inmutable).
    final_selection = dict(ir_selection)

    if "summary_index" in llm_output and llm_output["summary_index"] is not None:
        summaries = master_cv.get("cv", {}).get("sections", {}).get("summary", [])
        idx = llm_output["summary_index"]
        if isinstance(idx, int) and 0 <= idx < len(summaries):
            final_selection["summary_index"] = idx

    if "keywords_detected" in llm_output:
        # Mergear keywords del IR + del LLM, sin duplicados
        existing = set(k.lower() for k in final_selection.get("keywords_detected", []))
        new_keywords = []
        for kw in llm_output["keywords_detected"]:
            if isinstance(kw, str) and kw.strip() and kw.strip().lower() not in existing:
                new_keywords.append(kw.strip())
        final_selection["keywords_detected"] = (
            final_selection.get("keywords_detected", []) + new_keywords
        )[: config["max_keywords"]]

    # Match reasons: el LLM puede mejorar los que ya tiene IR, pero solo si
    # pasan el guardarail anti-alucinación (ver _verify_match_reason). Si
    # el LLM inventa una tecnología no presente ni en el bullet ni en el
    # JD, se descarta silenciosamente y queda el match_reason de IR.
    sections_by_key = master_cv.get("cv", {}).get("sections", {})
    for section_key, entries_key in [
        ("selected_experience", "experience"),
        ("selected_projects", "projects"),
    ]:
        llm_reasons = {item["index"]: item.get("match_reason", "")
                       for item in llm_output.get(section_key, [])
                       if "index" in item}
        entries = sections_by_key.get(entries_key, [])
        for item in final_selection.get(section_key, []):
            idx = item["index"]
            if idx not in llm_reasons or not llm_reasons[idx]:
                continue
            highlights = entries[idx].get("highlights", []) if 0 <= idx < len(entries) else []
            bullet_text = " ".join(h for h in highlights if isinstance(h, str))
            if _verify_match_reason(llm_reasons[idx], bullet_text, job_description):
                item["match_reason"] = llm_reasons[idx]
            # si no pasa el guardarail, se deja el match_reason de IR intacto

    return final_selection


def generate_section_selection(
    master_cv: Dict[str, Any],
    job_description: str,
    section_name: str,
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Igual que generate_selection, pero acotado a UNA sola sección.

    Usado por el botón 'Regenerar esta sección' de la UI.
    Ahora usa SelectionEngine.select_section() en vez del LLM para retrieval.
    """
    config = config or load_config()

    # Fase IR para una sola sección (singleton, reutiliza modelos en memoria)
    engine = get_selection_engine(config)
    return engine.select_section(master_cv, job_description, section_name)


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