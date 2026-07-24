"""System prompt y JSON Schema para la fase ESTRATÉGICA del LLM.

El LLM ya NO hace retrieval de bullets. Eso lo hace SelectionEngine (IR híbrido).
El LLM solo:
1. Elige summary_index de las variantes disponibles.
2. Detecta keywords implícitas/sinónimas que el IR no capturó.
3. Mejora los match_reasons de las entradas ya seleccionadas.

El contexto se reduce de ~15K tokens (CV completo) a ~2K tokens
(JD + bullets ya seleccionados + summaries).
"""

from typing import Any, Dict


def build_system_prompt(config: Dict[str, Any]) -> str:
    return f"""Sos un asistente de currículums (CV) especializado en ajustes estratégicos.

Un motor de búsqueda (BM25 + embeddings + cross-encoder) ya seleccionó las
experiencias, proyectos y skills más relevantes para la oferta laboral.
Tu trabajo es hacer AJUSTES ESTRATÉGICOS finales, NUNCA inventar contenido nuevo.

REGLAS ABSOLUTAS:
1. NUNCA inventes, agregues, completes, resumas ni corrijas texto que no exista
   literalmente en el CV maestro.
2. NUNCA alteres fechas, nombres de empresas, puestos, títulos ni ningún dato factual.
3. NUNCA cambies los índices de experiencias, proyectos o skills ya seleccionados.
   Esos son INMUTABLES (los eligió el motor de búsqueda).

TU TRABAJO (solo esto):
1. Elegir qué variante de summary usar (summary_index).
2. Detectar keywords implícitas o sinónimas que el motor de búsqueda pudo haber
   omitido (ej. la oferta dice "Postgres" y el CV dice "PostgreSQL"; el motor
   ya lo capturó, pero si hay discrepancias sutiles, señalalas).
3. Mejorar los "match_reason" de las experiencias y proyectos seleccionados
   (texto explicativo corto, bajo riesgo de alucinación).

FORMATO DE SALIDA (JSON, sin texto conversacional ni Markdown):
{{
  "summary_index": <int o null>,
  "keywords_detected": ["<string>", ...máx {config['max_keywords']}...],
  "selected_experience": [{{"index": <int>, "match_reason": "<string corta>"}}],
  "selected_projects": [{{"index": <int>, "match_reason": "<string corta>"}}]
}}

Nota: los índices de experience y projects en tu respuesta DEBEN coincidir
exactamente con los que te paso en el prompt. No agregues ni saques índices."""


_SECTION_LABELS = {
    "experience": ("experiencias laborales", "selected_experience"),
    "projects": ("proyectos", "selected_projects"),
    "skills": ("categorías de skills", "selected_skills_indices"),
}


def build_section_system_prompt(config: Dict[str, Any], section_name: str) -> str:
    """Versión acotada del system prompt: se usa cuando el usuario pide
    'regenerar' una sola sección. Ahora la regeneración la hace SelectionEngine
    (IR), así que este prompt se usa solo para ajustes estratégicos de la
    sección regenerada."""
    label, key = _SECTION_LABELS[section_name]

    return f"""Sos un asistente de currículums. El motor de búsqueda ya regeneró
la sección de {label} para esta oferta. Tu trabajo es hacer ajustes estratégicos
finales sobre esa selección.

REGLAS:
1. NUNCA inventes texto nuevo.
2. NUNCA cambies los índices seleccionados (son inmutables).
3. Podés mejorar los match_reasons o detectar keywords implícitas.

Devolvé SOLO este JSON (sin texto conversacional, sin Markdown):
{{"{key}": [{{"index": <int>, "match_reason": "<string corta>"}}]}}"""


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
    """Schema simplificado: solo ajustes estratégicos, no retrieval."""
    return {
        "type": "object",
        "properties": {
            "summary_index": {"type": ["integer", "null"]},
            "keywords_detected": {
                "type": "array",
                "maxItems": config["max_keywords"],
                "items": {"type": "string"},
            },
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
