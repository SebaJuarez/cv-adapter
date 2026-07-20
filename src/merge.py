"""Fusión determinística.

Toma el master_cv completo + la selección del LLM (que es SOLO índices y
orden) y arma el target_cv. Ningún string nuevo se genera acá: todo texto
proviene, byte a byte, de master_cv. Esta función es la barrera técnica
real contra alucinaciones (más fuerte que cualquier instrucción de prompt).
"""
from copy import deepcopy
from typing import Any, Dict, List, Optional


def _safe_get(lst: List[Any], idx: Optional[int]) -> Any:
    if idx is None or not isinstance(idx, int):
        return None
    return lst[idx] if 0 <= idx < len(lst) else None


def build_target_cv(master_cv: Dict[str, Any], selection: Dict[str, Any]) -> Dict[str, Any]:
    target = deepcopy(master_cv)
    sections = target.setdefault("cv", {}).setdefault("sections", {})

    master_sections = master_cv.get("cv", {}).get("sections", {})

    # --- Experiencia: filtrar entradas + reordenar/filtrar highlights ---
    master_experience = master_sections.get("experience", [])
    new_experience = []
    for item in selection.get("selected_experience", []):
        original = _safe_get(master_experience, item.get("index"))
        if original is None:
            continue  # índice inválido -> se ignora, jamás se inventa una entrada

        entry = deepcopy(original)
        original_highlights = original.get("highlights", [])
        order = item.get("highlight_order") or list(range(len(original_highlights)))

        filtered_highlights = []
        for h_idx in order:
            h = _safe_get(original_highlights, h_idx)
            if h is not None and h not in filtered_highlights:
                filtered_highlights.append(h)

        # Si el LLM no devolvió nada usable, conservamos el orden original
        entry["highlights"] = filtered_highlights or original_highlights
        new_experience.append(entry)

    if new_experience:
        sections["experience"] = new_experience

    # --- Skills ---
    master_skills = master_sections.get("skills", [])
    skill_indices = set(selection.get("selected_skills_indices", []))
    new_skills = [s for i, s in enumerate(master_skills) if i in skill_indices]
    if new_skills:
        sections["skills"] = new_skills

    # --- Projects (sección opcional) ---
    master_projects = master_sections.get("projects", [])
    if master_projects:
        project_indices = set(selection.get("selected_projects_indices", []))
        new_projects = [p for i, p in enumerate(master_projects) if i in project_indices]
        if new_projects:
            sections["projects"] = new_projects
        elif "projects" in sections:
            del sections["projects"]

    # --- Summary: elegimos UNA variante existente, no se redacta una nueva ---
    master_summary = master_sections.get("summary")
    summary_idx = selection.get("summary_index")
    if master_summary:
        s = _safe_get(master_summary, summary_idx)
        if s is not None:
            sections["summary"] = [s]

    target["cv"]["sections"] = sections
    return target
