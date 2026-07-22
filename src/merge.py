"""Fusión determinística.

Toma el master_cv completo + la selección del LLM (que es SOLO índices y
orden) y arma el target_cv. Ningún string nuevo se genera acá: todo texto
proviene, byte a byte, de master_cv. Esta función es la barrera técnica
real contra alucinaciones (más fuerte que cualquier instrucción de prompt).

El presupuesto de "una sola página" se fuerza ACÁ con código (no solo con
el prompt): un modelo de 8B local puede ignorar instrucciones de brevedad,
así que los límites vienen de config.json (ver src/config.py) y se aplican
siempre, sin importar cuánto contenido pida devolver el LLM.
"""
from copy import deepcopy
from typing import Any, Dict, List, Optional

from .config import load_config


def validate_master_cv_structure(master_cv: Dict[str, Any]) -> List[str]:
    """Chequeo defensivo post-carga: detecta el error más común al editar
    master_cv.yaml a mano — un bullet SIN comillas que contiene ': ' (dos
    puntos + espacio). YAML interpreta eso como un mapeo anidado en vez de
    texto, y el 'highlight' termina siendo un dict en vez de un string.
    Devuelve una lista de mensajes de error (vacía si todo está OK).
    """
    errors: List[str] = []
    sections = master_cv.get("cv", {}).get("sections", {})

    for section_name, entries in sections.items():
        if not isinstance(entries, list):
            continue
        for i, entry in enumerate(entries):
            if isinstance(entry, str):
                continue
            if not isinstance(entry, dict):
                continue
            label = entry.get("name") or entry.get("company") or entry.get("institution") or f"entrada #{i}"
            highlights = entry.get("highlights") or []
            for j, h in enumerate(highlights):
                if not isinstance(h, str):
                    errors.append(
                        f"cv.sections.{section_name}[{i}] ({label}) → highlights[{j}] "
                        f"no es un texto válido (llegó como {type(h).__name__}). "
                        "Causa típica: un bullet SIN comillas que contiene ': ' "
                        "(dos puntos + espacio). Solución: poné ese bullet completo "
                        "entre comillas simples en el YAML."
                    )
    return errors


def strip_internal_keys(data: Any) -> Any:
    """Saca recursivamente cualquier clave que empiece con '_' (metadata
    interna que usa el frontend, como '_src_section'/'_src_index' para la
    función de 'traer bullet del master'). RenderCV rechaza cualquier
    clave que no reconozca, así que esto TIENE que correr antes de
    guardar/renderizar cualquier YAML que haya pasado por la UI web.
    """
    if isinstance(data, dict):
        return {
            k: strip_internal_keys(v)
            for k, v in data.items()
            if not (isinstance(k, str) and k.startswith("_"))
        }
    if isinstance(data, list):
        return [strip_internal_keys(v) for v in data]
    return data


def _safe_get(lst: List[Any], idx: Optional[int]) -> Any:
    if idx is None or not isinstance(idx, int):
        return None
    return lst[idx] if 0 <= idx < len(lst) else None


def _apply_entry_selection(
    master_list: List[Dict[str, Any]],
    selection_items: List[Dict[str, Any]],
    max_entries: int,
    max_highlights: int,
    source_section: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Lógica compartida por 'experience' y 'projects': para cada entrada
    elegida por el LLM (por índice), copia la entrada original y le aplica
    el reorder/filtro de highlights que pidió el LLM — SIEMPRE recortado a
    `max_highlights`, sin importar cuántos haya pedido el modelo. También
    recorta la cantidad de entradas a `max_entries` (se queda con las
    primeras, asumiendo que el LLM ya las ordenó de más a menos relevante).

    Si `source_section` viene seteado, cada entrada devuelta lleva además
    '_src_section'/'_src_index' (metadata interna, ver strip_internal_keys)
    para que el frontend pueda ofrecer "traer un bullet más del master".
    """
    result: List[Dict[str, Any]] = []

    for item in selection_items[: max_entries * 3]:  # margen por si hay índices inválidos
        if len(result) >= max_entries:
            break

        idx = item.get("index")
        original = _safe_get(master_list, idx)
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
            if len(filtered_highlights) >= max_highlights:
                break

        entry["highlights"] = filtered_highlights or original_highlights[:max_highlights]
        if source_section is not None:
            entry["_src_section"] = source_section
            entry["_src_index"] = idx
        result.append(entry)

    return result


def _build_verified_keywords(
    master_cv: Dict[str, Any], candidate_keywords: List[str], max_keywords: int
) -> List[str]:
    """El LLM puede 'alucinar' una keyword que suena bien pero no está
    respaldada por el CV real. Acá se verifica cada candidata contra un
    corpus armado con TODO el texto del master_cv (summary, highlights,
    skills, languages) y se descarta cualquiera que no aparezca literalmente
    (case-insensitive).
    """
    sections = master_cv.get("cv", {}).get("sections", {})
    corpus_parts: List[str] = []

    for entries in sections.values():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if isinstance(entry, str):
                corpus_parts.append(entry)
            elif isinstance(entry, dict):
                corpus_parts.append(str(entry.get("details", "")))
                corpus_parts.append(str(entry.get("label", "")))
                corpus_parts.append(str(entry.get("name", "")))
                corpus_parts.extend(str(h) for h in entry.get("highlights", []) if isinstance(h, str))

    corpus = " \n ".join(corpus_parts).lower()

    verified: List[str] = []
    for kw in candidate_keywords:
        if not isinstance(kw, str) or not kw.strip():
            continue
        kw_clean = kw.strip()
        if kw_clean.lower() in corpus and kw_clean not in verified:
            verified.append(kw_clean)
        if len(verified) >= max_keywords:
            break

    return verified


def build_target_cv(
    master_cv: Dict[str, Any],
    selection: Dict[str, Any],
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    config = config or load_config()
    master_sections = master_cv.get("cv", {}).get("sections", {})
    new_sections: Dict[str, Any] = {}

    # --- Summary: elegimos UNA variante existente, no se redacta una nueva ---
    master_summary = master_sections.get("summary")
    summary_idx = selection.get("summary_index")
    if master_summary:
        s = _safe_get(master_summary, summary_idx) or master_summary[0]
        new_sections["summary"] = [s]

    # --- Keywords ATS: verificadas contra el propio master_cv, nunca inventadas ---
    verified_keywords = _build_verified_keywords(
        master_cv, selection.get("keywords_detected", []) or [], config["max_keywords"]
    )
    if verified_keywords:
        new_sections["keywords"] = ["Palabras clave: " + ", ".join(verified_keywords)]

    # --- Experiencia ---
    new_experience = _apply_entry_selection(
        master_sections.get("experience", []),
        selection.get("selected_experience", []),
        config["max_experience_entries"],
        config["max_highlights_per_entry"],
        source_section="experience",
    )
    if new_experience:
        new_sections["experience"] = new_experience

    # --- Proyectos ---
    new_projects = _apply_entry_selection(
        master_sections.get("projects", []),
        selection.get("selected_projects", []),
        config["max_project_entries"],
        config["max_highlights_per_entry"],
        source_section="projects",
    )
    if new_projects:
        new_sections["projects"] = new_projects

    # --- Educación: el título principal (índice 0) SIEMPRE se incluye ---
    master_education = master_sections.get("education", [])
    if master_education:
        new_education = [deepcopy(master_education[0])]
        extra_indices = [
            i for i in selection.get("selected_education_indices", [])
            if isinstance(i, int) and 0 < i < len(master_education)
        ]
        for i in extra_indices[: config["max_education_extra"]]:
            new_education.append(deepcopy(master_education[i]))
        new_sections["education"] = new_education

    # --- Skills ---
    master_skills = master_sections.get("skills", [])
    skill_indices: List[int] = []
    for i in selection.get("selected_skills_indices", []):
        if isinstance(i, int) and 0 <= i < len(master_skills) and i not in skill_indices:
            skill_indices.append(i)
    skill_indices = skill_indices[: config["max_skill_categories"]]
    if skill_indices:
        new_sections["skills"] = [master_skills[i] for i in skill_indices]

    # --- Languages: se mantienen siempre igual ---
    if master_sections.get("languages"):
        new_sections["languages"] = deepcopy(master_sections["languages"])

    target = deepcopy(master_cv)
    target["cv"]["sections"] = new_sections
    target.setdefault("design", {})["theme"] = config.get(
        "rendercv_theme", target.get("design", {}).get("theme", "engineeringresumes")
    )
    return target