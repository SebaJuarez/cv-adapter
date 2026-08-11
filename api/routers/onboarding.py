"""Router del onboarding conversacional (F4): estructura las respuestas
libres del chat en un achievement candidato.

El candidato NUNCA se guarda acá: el endpoint solo devuelve
{facts, variant_text} y el frontend lo muestra para confirmar/editar
antes de persistir con el POST /api/master-cv existente.
"""

from fastapi import APIRouter, HTTPException

from src.config import load_config
from src.onboarding import structurize_achievement

from ..schemas import OnboardingAnswersIn

router = APIRouter(tags=["onboarding"])


@router.post("/api/onboarding/structurize")
def onboarding_structurize(payload: OnboardingAnswersIn) -> dict:
    work = (payload.work or "").strip()
    if not work:
        raise HTTPException(
            status_code=422,
            detail="Contame al menos qué hiciste: no hay nada que estructurar.",
        )
    answers = {
        "work": work,
        "tools": (payload.tools or "").strip(),
        "outcomes": (payload.outcomes or "").strip(),
    }
    return structurize_achievement(answers, load_config())
