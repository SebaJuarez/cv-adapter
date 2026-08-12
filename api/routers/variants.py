"""Router de generación asistida de variantes (F6, doc §6.6)."""

from typing import Any, Dict

from fastapi import APIRouter, HTTPException

from src.config import load_config
from src.llm_node import generate_variant_text

from ..schemas import GenerateVariantIn

router = APIRouter(tags=["variants"])


@router.post("/api/variants/generate")
def generate_variant(payload: GenerateVariantIn) -> Dict[str, Any]:
    """Redacta una variante nueva orientada a `angle` (botón "Generar
    versión para [ángulo]", F6).

    El LLM reescribe SOLO con los hechos que manda el frontend (el master
    del disco puede diferir de la edición en memoria sin guardar) y
    devuelve el texto + los términos técnicos no verificados contra el
    logro, para que la UI los resalte. La variante jamás entra al master
    acá: la persiste el POST /api/master-cv existente tras la aprobación
    humana explícita.
    """
    if not payload.angle.strip():
        raise HTTPException(status_code=422, detail="Falta el ángulo de la redacción.")
    has_content = bool(payload.current_text.strip()) or bool(
        payload.facts
    ) or any(t.strip() for t in payload.variant_texts)
    if not has_content:
        raise HTTPException(
            status_code=422,
            detail="El logro no tiene contenido para redactar (hechos y redacciones vacíos).",
        )
    try:
        return generate_variant_text(
            angle=payload.angle,
            facts=payload.facts,
            variant_texts=payload.variant_texts,
            current_text=payload.current_text,
            jd_snippet=payload.jd_snippet,
            config=load_config(),
        )
    except RuntimeError as e:
        # El proveedor falló (o el modelo devolvió algo inválido): 502 con
        # detalle legible. El frontend muestra toast + enlace a Configuración.
        raise HTTPException(status_code=502, detail=str(e))