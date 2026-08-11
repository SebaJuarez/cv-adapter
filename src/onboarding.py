"""Onboarding conversacional (F4): estructura respuestas libres en un
achievement candidato (facts + primera variante).

El LLM propone y el usuario CONFIRMA antes de que nada entre al master:
este módulo solo devuelve el candidato — la persistencia la hace el POST
/api/master-cv del frontend. Defensivo por diseño: cualquier fallo
(proveedor caído, timeout, JSON inválido) degrada con gracia a un
candidato crudo (todo en `action` + el texto tal cual) para que el chat
nunca se quede trabado.
"""

from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict

from .llm_node import _EMPTY_FACTS, _FACTS_SCHEMA, _call_llm, _verify_facts

# Schema del candidato: los facts estructurados (misma verificación que
# extract_achievement_facts) más una primera redacción de CV.
_ONBOARDING_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "facts": _FACTS_SCHEMA,
        "variant_text": {"type": "string"},
    },
    "required": ["facts", "variant_text"],
}


def _source_text(answers: Dict[str, Any]) -> str:
    """El texto fuente de la verificación: las respuestas no vacías."""
    return " ".join(
        (answers.get(k) or "").strip() for k in ("work", "tools", "outcomes")
        if (answers.get(k) or "").strip()
    )


def _fallback_candidate(answers: Dict[str, Any]) -> Dict[str, Any]:
    """Candidato crudo sin LLM: nada se pierde, nada se inventa.

    `action` lleva lo que hizo, y la variante es el relato completo tal
    cual lo escribió el usuario (tools/outcomes quedan para que los cargue
    a mano o los edite en la tarjeta).
    """
    work = (answers.get("work") or "").strip()
    facts = dict(_EMPTY_FACTS)
    facts["action"] = work
    return {"facts": facts, "variant_text": _source_text(answers)}


def structurize_achievement(
    answers: Dict[str, Any], config: Dict[str, Any], timeout: float = 10.0
) -> Dict[str, Any]:
    """Convierte las respuestas del chat en un achievement candidato.

    Devuelve `{"facts": {...}, "variant_text": str}`: el frontend arma el
    achievement, lo muestra para confirmar/editar y recién ahí lo guarda.
    """
    work = (answers.get("work") or "").strip()
    if not work:
        return _fallback_candidate(answers)
    source = _source_text(answers)

    system_prompt = (
        "Sos un estructurador de logros de CV para el primer armado de un "
        "curriculum. Dado el relato libre de una persona: separás los HECHOS "
        "verificables (qué se hizo, con qué herramientas, alcance, resultados "
        "medibles) y escribís UNA redacción de CV en primera persona, concisa, "
        "lista para un curriculum. Regla inquebrantable: SOLO podés usar "
        "información que aparezca en el relato. NUNCA inventes tecnologías, "
        "métricas, equipos ni clientes. Si algo no aparece, dejalo vacío."
    )
    user_prompt = (
        "### relato de la persona ###\n"
        f"{source}\n\n"
        "Devolvé SOLO el JSON con: facts = {action: qué hiciste en una frase "
        "(verbo + objeto); tools: tecnologías/herramientas mencionadas; scope: "
        "alcance (personas, clientes, sistema, proceso); outcomes: resultados "
        "medibles del relato como lista de {metric, value}}; variant_text = la "
        "redacción de CV en una frase, en primera persona, que use SOLO lo del "
        "relato."
    )

    pool = None
    try:
        pool = ThreadPoolExecutor(max_workers=1)
        future = pool.submit(_call_llm, system_prompt, user_prompt, _ONBOARDING_SCHEMA, config)
        result = future.result(timeout=timeout) or {}
        facts = _verify_facts(result.get("facts") or {}, source)
        variant_text = (result.get("variant_text") or "").strip()
        if not variant_text:
            return {"facts": facts, "variant_text": source}
        return {"facts": facts, "variant_text": variant_text}
    except Exception:
        # Timeout, RuntimeError del proveedor, JSON inválido… el candidato
        # crudo siempre existe: el onboarding nunca se traba.
        return _fallback_candidate(answers)
    finally:
        if pool is not None:
            pool.shutdown(wait=False, cancel_futures=True)
