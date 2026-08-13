"""Fusión determinística.

Toma el master_cv completo + la selección del pipeline IR (que es SOLO índices y
orden) y arma el target_cv. Ningún string nuevo se genera acá: todo texto
proviene, byte a byte, de master_cv.

El presupuesto de "una sola página" se fuerza ACÁ con código (no solo con
el prompt): un modelo de 8B local puede ignorar instrucciones de brevedad,
así que los límites vienen de config.json (ver src/config.py) y se aplican
siempre, sin importar cuánto contenido pida devolver el LLM.
"""

from copy import deepcopy
from typing import Any, Dict, List, Optional

from .achievements import (
    apply_variant_usage,
    approved_variant_texts,
    entry_bullet_slots,
    facts_corpus_parts,
    resolve_slot_text,
    resolve_slot_with_variant,
    validate_achievements_structure,
)
from .config import load_config
from .retrieval.sparse import keyword_in_text as _keyword_in_text




def _reorder_skill_details(
    skill_entry: Dict[str, Any],
    priority_keywords: List[str],
) -> Dict[str, Any]:
    """Reordena los ítems dentro de `details` de una skill category.

    Los ítems que contienen alguna keyword prioritaria (o su sinónimo)
    aparecen primero, preservando su orden relativo original. El resto
    sigue después, también en orden relativo original.

    No agrega ni quita ningún ítem — solo reordena.
    """
    details = skill_entry.get("details", "")
    if not isinstance(details, str) or not details.strip():
        return skill_entry

    items = [item.strip() for item in details.split(",") if item.strip()]
    if not items:
        return skill_entry

    def _matches(item: str) -> bool:
        item_low = item.lower()
        return any(_keyword_in_text(kw, item_low) for kw in priority_keywords)

    matched = [item for item in items if _matches(item)]
    unmatched = [item for item in items if not _matches(item)]

    reordered = deepcopy(skill_entry)
    reordered["details"] = ", ".join(matched + unmatched)
    return reordered


def validate_master_cv_structure(master_cv: Dict[str, Any]) -> List[str]:
    """Chequeo defensivo post-carga: detecta el error más común al editar
    master_cv.yaml a mano — un bullet SIN comillas que contiene ": " (dos
    puntos + espacio). YAML interpreta eso como un mapeo anidado en vez de
    texto, y el 'highlight' termina siendo un dict en vez de un string.
    Devuelve una lista de mensajes de error (vacía si todo está OK).
    """
    errors: List[str] = validate_achievements_structure(master_cv)
    sections = master_cv.get("cv", {}).get("sections", {})

    for section_name, entries in sections.items():
        if not isinstance(entries, list):
            continue
        for i, entry in enumerate(entries):
            if isinstance(entry, str):
                continue
            if not isinstance(entry, dict):
                continue
            label = (
                entry.get("name")
                or entry.get("company")
                or entry.get("institution")
                or f"entrada #{i}"
            )
            highlights = entry.get("highlights") or []
            for j, h in enumerate(highlights):
                if not isinstance(h, str):
                    errors.append(
                        f"cv.sections.{section_name}[{i}] ({label}) → highlights[{j}] "
                        f"no es un texto válido (llegó como {type(h).__name__}). "
                        'Causa típica: un bullet SIN comillas que contiene ": " '
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


def _record_variant_usage(
    variant: Optional[Dict[str, Any]],
    variant_usage: Optional[Dict[str, int]],
) -> None:
    """Suma un uso a la variante emitida (F2, used_count). Solo cuenta lo
    que REALMENTE entró al target: este helper se llama tras un append
    exitoso (los duplicados descartados no suman)."""
    if variant is None or variant_usage is None:
        return
    variant_id = variant.get("id")
    if variant_id:
        variant_usage[variant_id] = variant_usage.get(variant_id, 0) + 1


def _apply_entry_selection(
    master_list: List[Dict[str, Any]],
    selection_items: List[Dict[str, Any]],
    max_entries: int,
    max_highlights: int,
    source_section: Optional[str] = None,
    variant_usage: Optional[Dict[str, int]] = None,
) -> List[Dict[str, Any]]:
    """Lógica compartida por 'experience' y 'projects': para cada entrada
    elegida (por índice), copia la entrada original y le aplica el reorder/filtro
    de bullets — SIEMPRE recortado a `max_highlights`, sin importar cuántos
    haya pedido el modelo. También recorta la cantidad de entradas a `max_entries`.

    Cada bullet es un slot de la entrada (ver `entry_bullet_slots`): un
    highlight legacy o un achievement. El texto final del slot lo resuelve
    `resolve_slot_text` — un achievement sin variantes `approved` devuelve
    None y se ignora en silencio, jamás se inventa una variante. El bloque
    `achievements` nunca llega al target (RenderCV no lo conoce): solo
    queda su texto resuelto en `highlights`.

    Si `source_section` viene seteado, cada entrada devuelta lleva además
    '_src_section'/'_src_index' (metadata interna, ver strip_internal_keys)
    para que el frontend pueda ofrecer "traer un bullet más del master".
    """
    result: List[Dict[str, Any]] = []

    for item in selection_items[
        : max_entries * 3
    ]:  # margen por si hay índices inválidos
        if len(result) >= max_entries:
            break

        idx = item.get("index")
        original = _safe_get(master_list, idx)
        if original is None:
            continue  # índice inválido -> se ignora, jamás se inventa una entrada

        entry = deepcopy(original)
        slots = entry_bullet_slots(original)
        order = item.get("highlight_order") or list(range(len(slots)))
        # Ángulos preferidos por logro (F2): dict {slot_index(str): ángulo}.
        # Solo matchean variantes con ese ángulo; si ninguna, el slot cae a
        # la variante representativa (misma regla de resolve_variant).
        preferred_angles = item.get("preferred_angles") or {}

        filtered_highlights = []
        emitted_slots: List[int] = []
        variant_meta: Dict[str, Dict[str, str]] = {}
        for s_idx in order:
            slot = _safe_get(slots, s_idx)
            if slot is None:
                continue
            text, variant = resolve_slot_with_variant(
                slot, preferred_angle=preferred_angles.get(str(s_idx))
            )
            if text is not None and text not in filtered_highlights:
                filtered_highlights.append(text)
                emitted_slots.append(s_idx)
                _record_variant_usage(variant, variant_usage)
                ach_id = (slot.get("achievement") or {}).get("id")
                variant_id = (variant or {}).get("id")
                if ach_id and variant_id:
                    variant_meta[str(s_idx)] = {
                        "ach_id": ach_id,
                        "variant_id": variant_id,
                        # F7 (historial): ángulo y texto emitido se persisten
                        # por corrida para trazabilidad (ver extract_bullet_variants).
                        "angle": (variant or {}).get("angle") or "",
                        "text": text,
                    }
            if len(filtered_highlights) >= max_highlights:
                break

        if not filtered_highlights:
            # order inválido/vacío -> caen los primeros slots resolubles del master
            for s_idx, slot in enumerate(slots):
                text, variant = resolve_slot_with_variant(slot)
                if text is not None and text not in filtered_highlights:
                    filtered_highlights.append(text)
                    emitted_slots.append(s_idx)
                    _record_variant_usage(variant, variant_usage)
                    ach_id = (slot.get("achievement") or {}).get("id")
                    variant_id = (variant or {}).get("id")
                    if ach_id and variant_id:
                        variant_meta[str(s_idx)] = {
                            "ach_id": ach_id,
                            "variant_id": variant_id,
                            "angle": (variant or {}).get("angle") or "",
                            "text": text,
                        }
                if len(filtered_highlights) >= max_highlights:
                    break

        entry["highlights"] = filtered_highlights
        entry.pop("achievements", None)
        if source_section is not None:
            entry["_src_section"] = source_section
            entry["_src_index"] = idx
            # Metadata por bullet (Fase 3, selector de variante): el orden
            # efectivo de slots y la variante emitida por cada logro, para
            # que el frontend pueda ofrecer el cambio de redacción. Solo en
            # memoria: strip_internal_keys las limpia al guardar.
            if variant_meta:
                entry["_src_slot_map"] = emitted_slots
                entry["_src_variant_map"] = variant_meta
        result.append(entry)

    return result


def extract_bullet_variants(target_cv: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Traza de qué variante emitió cada bullet del target (F7, historial).

    Recorre experience/projects y, para cada entrada con metadata interna
    (`_src_slot_map`/`_src_variant_map`), reconstruye por bullet el logro
    y la variante emitida, en el orden efectivo del target. Los bullets
    legacy (highlights planos, sin variante) no entran a la traza.

    Devuelve registros {section, entry_index, ach_id, variant_id, angle,
    text} — el texto queda guardado para que el historial siga legible
    aunque la variante se marque deprecated o se borre del master después.
    """
    records: List[Dict[str, Any]] = []
    sections = target_cv.get("cv", {}).get("sections", {})
    for section in ("experience", "projects"):
        for entry in sections.get(section, []):
            if not isinstance(entry, dict):
                continue
            meta_map = entry.get("_src_variant_map") or {}
            slot_map = entry.get("_src_slot_map")
            if not isinstance(meta_map, dict) or not isinstance(slot_map, list):
                continue
            for pos, text in enumerate(entry.get("highlights", [])):
                slot_idx = slot_map[pos] if pos < len(slot_map) else pos
                meta = meta_map.get(str(slot_idx))
                if not meta or not meta.get("ach_id") or not meta.get("variant_id"):
                    continue
                records.append(
                    {
                        "section": entry.get("_src_section") or section,
                        "entry_index": entry.get("_src_index", 0),
                        "ach_id": meta["ach_id"],
                        "variant_id": meta["variant_id"],
                        "angle": meta.get("angle") or "",
                        "text": text,
                    }
                )
    return records


def _master_cv_corpus(master_cv: Dict[str, Any]) -> str:
    sections = master_cv.get("cv", {}).get("sections", {})
    parts: List[str] = []
    for entries in sections.values():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if isinstance(entry, str):
                parts.append(entry)
            elif isinstance(entry, dict):
                parts.append(str(entry.get("details", "")))
                parts.append(str(entry.get("label", "")))
                parts.append(str(entry.get("name", "")))
                parts.extend(
                    str(h) for h in entry.get("highlights", []) if isinstance(h, str)
                )
                # D6: el corpus ATS suma los hechos (action/tools) y TODAS
                # las variantes aprobadas de los achievements — si una
                # keyword está aprobada en el banco de redacciones, "existe
                # en el master" aunque la variante emitida en esta corrida
                # no la mencione (el keyword_report ya verifica el texto
                # emitido con `in_target`).
                achievements = entry.get("achievements")
                if isinstance(achievements, list):
                    for ach in achievements:
                        if not isinstance(ach, dict):
                            continue
                        parts.extend(facts_corpus_parts(ach))
                        parts.extend(approved_variant_texts(ach))
    return " \n ".join(parts).lower()


def _build_verified_keywords(
    master_cv: Dict[str, Any],
    job_description: str,
    candidate_keywords: List[str],
    max_keywords: int,
) -> List[str]:
    """El LLM puede 'alucinar' una keyword que suena bien pero no tiene nada
    que ver con la oferta real. Una keyword solo sobrevive si aparece
    (o alguna de sus variantes sinónimas) en AMBOS lados: master_cv
    (respaldo real) y job_description (relevancia real).

    Reutiliza la tabla SYNONYMS de src/retrieval/sparse.py (vía keyword_in_text)
    para que "postgres" y "postgresql" se consideren el mismo término, y matchea
    con límites de palabra para que "js" no verifique contra "jsp". Evita
    inconsistencias entre retrieval y verificación ATS.
    """
    master_corpus = _master_cv_corpus(master_cv)
    jd_corpus = (job_description or "").lower()

    verified: List[str] = []
    for kw in candidate_keywords:
        if not isinstance(kw, str) or not kw.strip():
            continue
        kw_clean = kw.strip()
        if (
            _keyword_in_text(kw_clean, master_corpus)
            and _keyword_in_text(kw_clean, jd_corpus)
            and kw_clean not in verified
        ):
            verified.append(kw_clean)
        if len(verified) >= max_keywords:
            break

    return verified


def build_section_entries(
    master_cv: Dict[str, Any],
    section_name: str,
    section_selection: Dict[str, Any],
    config: Optional[Dict[str, Any]] = None,
    variant_usage: Optional[Dict[str, int]] = None,
) -> List[Any]:
    """Arma el contenido de UNA sola sección a partir de una selección scoped.
    La usa tanto build_target_cv (CV completo) como el endpoint de 'regenerar esta
    sección' (re-seleccionar solo una parte sin tocar el resto del CV).

    `variant_usage` (opcional) es un dict compartido donde se acumulan los
    `id` de las variantes emitidas (F2, para incrementar used_count)."""
    config = config or load_config()
    master_sections = master_cv.get("cv", {}).get("sections", {})

    if section_name in ("experience", "projects"):
        max_entries = (
            config["max_experience_entries"]
            if section_name == "experience"
            else config["max_project_entries"]
        )
        return _apply_entry_selection(
            master_sections.get(section_name, []),
            section_selection.get(f"selected_{section_name}", []),
            max_entries,
            config["max_highlights_per_entry"],
            source_section=section_name,
            variant_usage=variant_usage,
        )

    if section_name == "skills":
        master_skills = master_sections.get("skills", [])
        skill_indices: List[int] = []
        for i in section_selection.get("selected_skills_indices", []):
            if (
                isinstance(i, int)
                and 0 <= i < len(master_skills)
                and i not in skill_indices
            ):
                skill_indices.append(i)
        return [
            master_skills[i] for i in skill_indices[: config["max_skill_categories"]]
        ]

    raise ValueError(f"Sección no soportada para regeneración scoped: {section_name}")


def build_target_cv(
    master_cv: Dict[str, Any],
    selection: Dict[str, Any],
    config: Optional[Dict[str, Any]] = None,
    job_description: str = "",
    manual_keywords: Optional[List[str]] = None,
    variant_usage: Optional[Dict[str, int]] = None,
) -> Dict[str, Any]:
    """Arma el target_cv a partir del master_cv + la selección del pipeline.

    La selección puede venir del pipeline IR (SelectionEngine) o del LLM
    estratégico (o ambos mergeados). El formato es el mismo para mantener
    compatibilidad con el resto del sistema.

    `variant_usage` (opcional): dict compartido donde se acumulan los
    `id` de las variantes emitidas (F2, para incrementar used_count)."""
    config = config or load_config()
    master_sections = master_cv.get("cv", {}).get("sections", {})
    new_sections: Dict[str, Any] = {}

    # --- Summary: elegimos UNA variante existente ---
    master_summary = master_sections.get("summary")
    summary_idx = selection.get("summary_index")
    if master_summary:
        s = _safe_get(master_summary, summary_idx) or master_summary[0]
        new_sections["summary"] = [s]

    # --- Keywords ATS: verificadas contra master_cv + oferta ---
    verified_keywords = _build_verified_keywords(
        master_cv,
        job_description,
        selection.get("keywords_detected", []) or [],
        config["max_keywords"],
    )

    # Manual keywords con la misma lógica de sinónimos, pero con PRIORIDAD
    # sobre las detectadas: el usuario las escribió explícitamente y no debe
    # perderlas por el truncado de max_keywords. Las detectadas completan el
    # cupo restante.
    master_corpus = _master_cv_corpus(master_cv)
    final_keywords: List[str] = []
    for kw in manual_keywords or []:
        kw_clean = (kw or "").strip()
        if not kw_clean:
            continue
        if (
            _keyword_in_text(kw_clean, master_corpus)
            and kw_clean not in final_keywords
        ):
            final_keywords.append(kw_clean)
    for kw in verified_keywords:
        if kw not in final_keywords:
            final_keywords.append(kw)

    verified_keywords = final_keywords[: config["max_keywords"]]
    if verified_keywords and config.get("show_keywords_line", True):
        # Línea visible "Palabras clave: ..." — opcional (ver [5.1] de la
        # review): ayuda contra ATS basados en conteo simple de términos,
        # pero un reclutador humano puede leerla como relleno. El toggle
        # deja la decisión en manos del usuario en vez de aplicarla siempre.
        new_sections["keywords"] = ["Palabras clave: " + ", ".join(verified_keywords)]

    # --- Experiencia y proyectos ---
    new_experience = build_section_entries(
        master_cv, "experience", selection, config, variant_usage=variant_usage
    )
    if new_experience:
        new_sections["experience"] = new_experience

    new_projects = build_section_entries(
        master_cv, "projects", selection, config, variant_usage=variant_usage
    )
    if new_projects:
        new_sections["projects"] = new_projects

    # --- Educación: el título principal (índice 0) SIEMPRE se incluye ---
    master_education = master_sections.get("education", [])
    if master_education:
        new_education = [deepcopy(master_education[0])]
        extra_indices = [
            i
            for i in selection.get("selected_education_indices", [])
            if isinstance(i, int) and 0 < i < len(master_education)
        ]
        for i in extra_indices[: config["max_education_extra"]]:
            new_education.append(deepcopy(master_education[i]))
        for edu in new_education:
            if isinstance(edu, dict):
                edu.pop("achievements", None)
        new_sections["education"] = new_education

    # --- Skills ---
    new_skills = build_section_entries(master_cv, "skills", selection, config)
    if new_skills:
        # Reordenar ítems dentro de cada categoría: matches con keywords primero
        new_sections["skills"] = [
            _reorder_skill_details(s, verified_keywords) for s in new_skills
        ]

    # --- Languages: se mantienen siempre igual ---
    if master_sections.get("languages"):
        new_sections["languages"] = deepcopy(master_sections["languages"])

    # --- Secciones no manejadas por el pipeline: se preservan tal cual ---
    # El pipeline selecciona summary/experience/projects/education/skills y
    # mantiene languages. Cualquier OTRA sección del master (certifications,
    # interests, publications, awards…) se copia íntegra al target: son
    # contenido que el usuario agregó a mano y no debe perderse al adaptar.
    _HANDLED_SECTIONS = {
        "summary", "keywords", "experience", "projects",
        "education", "skills", "languages",
    }
    for name, entries in master_sections.items():
        if name not in _HANDLED_SECTIONS and name not in new_sections:
            new_sections[name] = deepcopy(entries)

    target = deepcopy(master_cv)
    target["cv"]["sections"] = new_sections
    target.setdefault("design", {})["theme"] = config.get(
        "rendercv_theme", target.get("design", {}).get("theme", "engineeringresumes")
    )
    return target


# ~Caracteres de texto corrido por línea a 10-11pt en A4 con márgenes estándar.
# Es una cota gruesa para la heurística de P1.4: sirve para avisar, jamás
# para bloquear (el render real es Typst y varía por tema).
_CHARS_PER_LINE = 90


def _text_lines(text: str) -> int:
    """Líneas estimadas para un texto corrido (summary, bullet, etc.)."""
    if not text or not str(text).strip():
        return 0
    return max(1, -(-len(str(text)) // _CHARS_PER_LINE))


def estimate_page_overflow(target_cv: Dict[str, Any], config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Estima si el target_cv cabe en una página (heurística NO bloqueante, P1.4).

    Cuenta líneas aproximadas del documento final: encabezado + una línea por
    entrada + texto corrido partido cada ~90 caracteres. El presupuesto por
    página sale de `config.json` (`lines_per_page`, default 45).

    Es una estimación a ojo: el layout real lo decide Typst según el tema.
    Por eso el resultado es informativo (banner en la web), nunca un filtro
    que descarte contenido.
    """
    config = config or {}
    budget = int(config.get("lines_per_page", 45))
    lines = 2  # nombre + ubicación/contacto
    sections = target_cv.get("cv", {}).get("sections", {})
    for section, entries in sections.items():
        if not isinstance(entries, list) or not entries:
            continue
        lines += 1  # título de sección
        if section == "summary":
            for text in entries:
                lines += _text_lines(text)
        elif section in ("experience", "projects"):
            for entry in entries:
                lines += 1  # encabezado de la entrada
                for highlight in entry.get("highlights", []):
                    lines += _text_lines(highlight)
        elif section == "skills":
            # Una línea por categoría, pero un details largo ocupa más de
            # una línea real: se mide con el mismo criterio que el resto
            # (_text_lines, ~90 chars por línea).
            for entry in entries:
                if isinstance(entry, dict):
                    details = entry.get("details", "")
                    if isinstance(details, list):
                        details = ", ".join(str(d) for d in details)
                    lines += max(1, _text_lines(details))
                else:
                    lines += max(1, _text_lines(entry))
        else:
            # keywords (una línea) y secciones passthrough (1 línea/entrada)
            lines += len(entries)
    overflow_lines = max(0, lines - budget)
    return {
        "estimated_lines": lines,
        "page_budget_lines": budget,
        "overflow": lines > budget,
        "overflow_lines": overflow_lines,
    }