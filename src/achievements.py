"""Logros con variantes de redacción.

Cada logro (achievement) separa los hechos verificables (facts) de sus
variantes de redacción (variants), cada una orientada a un ángulo distinto.
El formato legacy `highlights: [str]` sigue siendo válido: en memoria, cada
string legacy es un "slot" de tipo legacy y cada achievement un "slot" de
tipo achievement (en ese orden), y el resto del pipeline IR trabaja sobre
esa lista unificada de slots sin saber cuál era el formato original.

Invariantes:
- Ninguna variante `pending` aparece en un target generado: un logro sin
  variantes `approved` se ignora en silencio en merge (jamás se inventa
  contenido), igual que un índice inválido.
- `deprecated` no se borra: solo deja de ofrecerse en selecciones nuevas.
"""

from typing import Any, Dict, List, Optional

# Ángulos de énfasis: set chico y fijo para que la elección siga siendo
# clara y comparable contra el JD.
VALID_ANGLES = [
    "liderazgo",
    "ownership",
    "escala",
    "reduccion_costo",
    "velocidad_entrega",
    "impacto_tecnico",
    "calidad_testing",
    "cross_funcional",
    "vision_producto",
]
VALID_STATUSES = ("pending", "approved", "deprecated")
VALID_SOURCES = ("manual", "imported", "generated")

# Una variante puede tener hasta 2 ángulos (no más, para que la elección
# siga siendo clara).
MAX_ANGLES_PER_VARIANT = 2

# Un logro escrito a mano es revisado por el usuario por definición: el
# status ausente se trata como aprobado (las importadas sin revisar traen
# status 'pending' explícito).
DEFAULT_STATUS = "approved"


def variant_status(variant: Dict[str, Any]) -> str:
    """Status efectivo de una variante (el ausente es `approved`)."""
    status = variant.get("status", DEFAULT_STATUS)
    return status if status in VALID_STATUSES else DEFAULT_STATUS


def normalize_angles(variant: Dict[str, Any]) -> List[str]:
    """Ángulos de una variante: acepta `angle: str` o `angle: [str, ...]`."""
    angle = variant.get("angle")
    if isinstance(angle, str):
        return [angle] if angle else []
    if isinstance(angle, list):
        return [a for a in angle if isinstance(a, str) and a]
    return []


def representative_variant(achievement: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Variante representativa para indexación/selección:

    la `approved` con mayor `used_count`; empate → la más reciente
    (`created_at`, ISO comparables lexicográficamente); si no hay
    variantes `approved`, devuelve None.
    """
    approved = [
        v for v in achievement.get("variants", []) if variant_status(v) == "approved"
    ]
    if not approved:
        return None

    def _key(v: Dict[str, Any]):
        return (int(v.get("used_count", 0) or 0), str(v.get("created_at") or ""))

    return max(approved, key=_key)


def index_text(achievement: Dict[str, Any]) -> str:
    """Texto indexable de un logro: el de la variante representativa;
    sin `approved`, cae al texto de la primera variante que tenga texto
    (parking para que el logro siga siendo recuperable).
    """
    rep = representative_variant(achievement)
    if rep is not None:
        text = rep.get("text")
        if isinstance(text, str) and text:
            return text
    for v in achievement.get("variants", []):
        text = v.get("text")
        if isinstance(text, str) and text:
            return text
    return ""


def approved_variant_texts(achievement: Dict[str, Any]) -> List[str]:
    """Textos de todas las variantes `approved` (corpus ATS)."""
    texts: List[str] = []
    for v in achievement.get("variants", []):
        if variant_status(v) != "approved":
            continue
        text = v.get("text")
        if isinstance(text, str) and text.strip():
            texts.append(text)
    return texts


def resolve_variant(
    achievement: Dict[str, Any], preferred_angle: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """Variante final de un logro para el target: `approved` cuyo ángulo
    coincide con `preferred_angle` (primera en orden de array), o la
    representativa si no hay match de ángulo. None si no hay variantes
    `approved` → el slot se ignora en silencio (regla de `pending`).
    Devuelve la variante completa para poder registrar su `id` en
    `used_count`; `resolve_variant_text` es su proyección a texto.
    """
    approved = [
        v for v in achievement.get("variants", []) if variant_status(v) == "approved"
    ]
    if not approved:
        return None
    if preferred_angle:
        for v in approved:
            if preferred_angle in normalize_angles(v):
                text = v.get("text")
                if isinstance(text, str) and text:
                    return v
    rep = representative_variant(achievement)
    if rep is not None:
        text = rep.get("text")
        if isinstance(text, str) and text:
            return rep
    return None


def resolve_variant_text(
    achievement: Dict[str, Any], preferred_angle: Optional[str] = None
) -> Optional[str]:
    """Texto final de un logro para el target (ver `resolve_variant`)."""
    variant = resolve_variant(achievement, preferred_angle)
    if variant is None:
        return None
    text = variant.get("text")
    return text if isinstance(text, str) else None


def entry_bullet_slots(entry: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Lista unificada de slots de una entrada: los achievements primero
    (por orden de array) y los highlights legacy después (por orden de
    array). El índice de cada slot es el mismo que usan selection
    (indexación) y merge (resolución), así que los `highlight_order`
    valen para ambos.
    """
    slots: List[Dict[str, Any]] = []
    achievements = entry.get("achievements")
    if isinstance(achievements, list):
        for ach in achievements:
            if isinstance(ach, dict) and ach.get("variants"):
                slots.append(
                    {"kind": "achievement", "achievement": ach, "text": index_text(ach)}
                )
    for h in entry.get("highlights", []):
        if isinstance(h, str) and h.strip():
            slots.append({"kind": "legacy", "text": h.strip()})
    return slots


def resolve_slot_text(
    slot: Dict[str, Any], preferred_angle: Optional[str] = None
) -> Optional[str]:
    """Texto final de un slot para el target. None significa que el slot
    no se puede emitir (logro sin variantes `approved`) → se ignora en
    silencio, jamás se inventa contenido de reemplazo.
    """
    text, _ = resolve_slot_with_variant(slot, preferred_angle)
    return text


def resolve_slot_with_variant(
    slot: Dict[str, Any], preferred_angle: Optional[str] = None
) -> tuple:
    """(texto emitido, variante usada o None). Igual regla que
    `resolve_slot_text`, pero devuelve además la variante `approved` que
    merge emitió — la necesita para incrementar `used_count`. Para
    slots legacy la variante es siempre None.
    """
    if slot.get("kind") == "achievement":
        variant = resolve_variant(slot.get("achievement") or {}, preferred_angle)
        if variant is None:
            return None, None
        text = variant.get("text")
        return (text if isinstance(text, str) else None), variant
    return slot.get("text"), None


def apply_variant_usage(
    master_cv: Dict[str, Any], usage_counts: Dict[str, int]
) -> int:
    """Suma `used_count` de las variantes existentes (match por `id`) en
    todo el master. Devuelve cuántas variantes se actualizaron.

    Nunca crea variantes: los ids ausentes (borrados o renombrados) se
    ignoran en silencio — el dato de uso se pierde, nunca se inventa.
    """
    if not usage_counts:
        return 0
    updated = 0
    sections = master_cv.get("cv", {}).get("sections", {})
    for entries in sections.values():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            achievements = entry.get("achievements")
            if not isinstance(achievements, list):
                continue
            for ach in achievements:
                variants = ach.get("variants") if isinstance(ach, dict) else None
                if not isinstance(variants, list):
                    continue
                for variant in variants:
                    if not isinstance(variant, dict):
                        continue
                    times = usage_counts.get(variant.get("id"))
                    if times:
                        variant["used_count"] = (
                            int(variant.get("used_count", 0) or 0) + times
                        )
                        updated += 1
    return updated


def facts_corpus_parts(achievement: Dict[str, Any]) -> List[str]:
    """Partes de `facts` que suman al corpus ATS: `action` + `tools`.
    El resto del respaldo lo dan los textos de las variantes aprobadas.
    """
    parts: List[str] = []
    facts = achievement.get("facts")
    if isinstance(facts, dict):
        action = facts.get("action")
        if isinstance(action, str) and action.strip():
            parts.append(action)
        tools = facts.get("tools")
        if isinstance(tools, list):
            parts.extend(t for t in tools if isinstance(t, str) and t.strip())
    return parts


def validate_achievements_structure(master_cv: Dict[str, Any]) -> List[str]:
    """Chequeo estructural del bloque `achievements` de todo el master.
    Devuelve una lista de mensajes de error (vacía si todo está OK), en
    el mismo estilo que `validate_master_cv_structure` (merge.py).

    Reglas:
    - Una entrada usa `highlights` O `achievements`, nunca ambos a la vez:
      la conversión legacy → achievement es mecánica y sin pérdida, así que
      mezclar formatos en una entrada es siempre un error del usuario.
    - Todo achievement tiene `id` y al menos una variante; toda variante
      tiene `id` y `text` no vacío; status/source/angle pertenecen a las
      taxonomías fijas; `used_count` es un entero >= 0.
    """
    errors: List[str] = []
    sections = master_cv.get("cv", {}).get("sections", {})
    for section_name, entries in sections.items():
        if not isinstance(entries, list):
            continue
        for i, entry in enumerate(entries):
            if not isinstance(entry, dict) or "achievements" not in entry:
                continue
            label = (
                entry.get("name")
                or entry.get("company")
                or entry.get("institution")
                or f"entrada #{i}"
            )
            prefix = f"cv.sections.{section_name}[{i}] ({label})"
            if entry.get("highlights"):
                errors.append(
                    f"{prefix} tiene `highlights` y `achievements` a la vez: "
                    "usá un solo formato por entrada."
                )
            achievements = entry["achievements"]
            if not isinstance(achievements, list):
                errors.append(f"{prefix} → `achievements` debe ser una lista.")
                continue
            for j, ach in enumerate(achievements):
                ap = f"{prefix} → achievements[{j}]"
                if not isinstance(ach, dict):
                    errors.append(f"{ap} debe ser un objeto.")
                    continue
                aid = ach.get("id")
                if not isinstance(aid, str) or not aid.strip():
                    errors.append(f"{ap} falta el `id` (texto único y estable del logro).")
                variants = ach.get("variants")
                if not isinstance(variants, list) or not variants:
                    errors.append(f"{ap} debe tener al menos una variante de redacción.")
                    continue
                for k, variant in enumerate(variants):
                    vp = f"{ap} → variants[{k}]"
                    if not isinstance(variant, dict):
                        errors.append(f"{vp} debe ser un objeto.")
                        continue
                    text = variant.get("text")
                    if not isinstance(text, str) or not text.strip():
                        errors.append(f"{vp} falta el `text` (redacción de la variante).")
                    vid = variant.get("id")
                    if not isinstance(vid, str) or not vid.strip():
                        errors.append(f"{vp} falta el `id` de la variante.")
                    status = variant.get("status")
                    if status is not None and status not in VALID_STATUSES:
                        errors.append(
                            f"{vp} tiene status inválido {status!r} "
                            f"(válidos: {', '.join(VALID_STATUSES)})."
                        )
                    source = variant.get("source")
                    if source is not None and source not in VALID_SOURCES:
                        errors.append(
                            f"{vp} tiene source inválido {source!r} "
                            f"(válidos: {', '.join(VALID_SOURCES)})."
                        )
                    angles = normalize_angles(variant)
                    if len(angles) > MAX_ANGLES_PER_VARIANT:
                        errors.append(
                            f"{vp} tiene {len(angles)} ángulos "
                            f"(máximo {MAX_ANGLES_PER_VARIANT})."
                        )
                    invalid_angles = [a for a in angles if a not in VALID_ANGLES]
                    if invalid_angles:
                        errors.append(
                            f"{vp} tiene ángulos desconocidos: {', '.join(invalid_angles)}."
                        )
                    used_count = variant.get("used_count")
                    if used_count is not None and (
                        not isinstance(used_count, int)
                        or isinstance(used_count, bool)
                        or used_count < 0
                    ):
                        errors.append(f"{vp} `used_count` debe ser un entero >= 0.")
    return errors