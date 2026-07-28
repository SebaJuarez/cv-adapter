"""System prompt y JSON Schema para la fase ESTRATÉGICA del LLM.

Fase 5: El LLM ya NO elige summary_index (eso lo hace IR) ni detecta keywords
(ya las extrae el motor de IR). Su única tarea es redactar match_reasons en
lenguaje natural fluido sobre bullets YA seleccionados por IR.
"""

from typing import Any, Dict


def build_system_prompt(config: Dict[str, Any]) -> str:
    return """Sos un asistente de currículums (CV) especializado en redactar
justificaciones breves de por qué una experiencia o proyecto matchea con una
oferta laboral.

REGLAS ABSOLUTAS:
1. NUNCA inventes hechos, tecnologías, empresas, fechas, métricas ni roles
   que no aparezcan literalmente en el bullet o en la oferta.
2. NUNCA cambies los índices de experiencias o proyectos ya seleccionados.
   Esos son INMUTABLES (los eligió el motor de búsqueda).
3. Tu texto debe ser conciso (1 oración corta, máximo 2) y en español.
4. Solo podés mencionar conceptos que aparezcan en el bullet del CV o en
   el job description. Si no estás seguro, usa una frase genérica como
   "Relevante para la oferta".

FORMATO DE SALIDA (JSON, sin texto conversacional ni Markdown):
{
  "selected_experience": [{"index": <int>, "match_reason": "<string>"}],
  "selected_projects": [{"index": <int>, "match_reason": "<string>"}]
}

Nota: los índices en tu respuesta DEBEN coincidir exactamente con los que te
paso en el prompt. No agregues ni saques índices."""


_SECTION_LABELS = {
    "experience": ("experiencias laborales", "selected_experience"),
    "projects": ("proyectos", "selected_projects"),
    "skills": ("categorías de skills", "selected_skills_indices"),
}


def build_section_system_prompt(config: Dict[str, Any], section_name: str) -> str:
    """Versión acotada para regenerar una sola sección."""
    label, key = _SECTION_LABELS[section_name]

    return f"""Sos un asistente de currículums. El motor de búsqueda ya regeneró
la sección de {label} para esta oferta. Tu trabajo es redactar justificaciones
breves (match_reasons) para cada entrada seleccionada.

REGLAS:
1. NUNCA inventes hechos, tecnologías ni métricas nuevas.
2. NUNCA cambies los índices seleccionados (son inmutables).
3. Solo mencioná conceptos presentes en el bullet o en la oferta.
4. Texto conciso: 1 oración corta, máximo 2.

Devolvé SOLO este JSON (sin texto conversacional, sin Markdown):
{{"{key}": [{{"index": <int>, "match_reason": "<string>"}}]}}"""


def build_section_schema(config: Dict[str, Any], section_name: str) -> Dict[str, Any]:
    if section_name == "skills":
        return {
            "type": "object",
            "properties": {
                "selected_skills_indices": {
                    "type": "array",
                    "maxItems": config["max_skill_categories"],
                    "items": {"type": "integer"},
                }
            },
            "required": ["selected_skills_indices"],
        }

    _, key = _SECTION_LABELS[section_name]
    return {
        "type": "object",
        "properties": {
            key: {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "index": {"type": "integer"},
                        "match_reason": {"type": "string"},
                    },
                    "required": ["index"],
                },
            }
        },
        "required": [key],
    }


def build_selection_schema(config: Dict[str, Any]) -> Dict[str, Any]:
    """Schema simplificado: solo match_reasons, nada más."""
    return {
        "type": "object",
        "properties": {
            "selected_experience": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "index": {"type": "integer"},
                        "match_reason": {"type": "string"},
                    },
                    "required": ["index"],
                },
            },
            "selected_projects": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "index": {"type": "integer"},
                        "match_reason": {"type": "string"},
                    },
                    "required": ["index"],
                },
            },
        },
    }