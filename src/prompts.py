"""System prompt y JSON Schema para la fase ESTRATÉGICA del LLM.

Fase 5: El LLM ya NO elige summary_index (eso lo hace IR) ni detecta keywords
(ya las extrae el motor de IR). Su única tarea es redactar match_reasons en
lenguaje natural fluido sobre bullets YA seleccionados por IR.
"""

from typing import Any, Dict


def build_system_prompt(config: Dict[str, Any]) -> str:
    return """Sos un asistente de currículums (CV) especializado en redactar
justificaciones breves de por qué una experiencia o proyecto matchea con una
oferta laboral, y en elegir el ángulo de presentación de los logros del
candidato.

REGLAS ABSOLUTAS:
1. NUNCA inventes hechos, tecnologías, empresas, fechas, métricas ni roles
   que no aparezcan literalmente en el bullet o en la oferta.
2. NUNCA cambies los índices de experiencias o proyectos ya seleccionados.
   Esos son INMUTABLES (los eligió el motor de búsqueda).
3. Tu texto debe ser conciso (1 oración corta, máximo 2) y en español.
4. Solo podés mencionar conceptos que aparezcan en el bullet del CV o en
   el job description. Si no estás seguro, usa una frase genérica como
   "Relevante para la oferta".
5. preferred_angles es OPCIONAL: podés sugerir UN ángulo por logro (los
   que en el prompt vienen marcados como "logro"), solo si está en la
   lista de ángulos válidos que te paso y el texto del logro lo justifica.
   No inventes ángulos ni los apliques a bullets comunes.

FORMATO DE SALIDA (JSON, sin texto conversacional ni Markdown):
{
  "selected_experience": [{"index": <int>, "match_reason": "<string>", "preferred_angles": [{"slot_index": <int>, "angle": "<string>"}]}],
  "selected_projects": [{"index": <int>, "match_reason": "<string>", "preferred_angles": [{"slot_index": <int>, "angle": "<string>"}]}]
}

Nota: los índices en tu respuesta DEBEN coincidir exactamente con los que te
paso en el prompt. No agregues ni saques índices."""


def build_selection_schema(config: Dict[str, Any]) -> Dict[str, Any]:
    """Schema para la fase estratégica: match_reasons + ángulos opcionales
    por logro (F2, preferred_angles)."""
    entry_item = {
        "type": "object",
        "properties": {
            "index": {"type": "integer"},
            "match_reason": {"type": "string"},
            "preferred_angles": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "slot_index": {"type": "integer"},
                        "angle": {"type": "string"},
                    },
                    "required": ["slot_index", "angle"],
                },
            },
        },
        "required": ["index"],
    }
    return {
        "type": "object",
        "properties": {
            "selected_experience": {"type": "array", "items": entry_item},
            "selected_projects": {"type": "array", "items": entry_item},
        },
    }