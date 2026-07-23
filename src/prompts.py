"""System prompt y JSON Schema usados para forzar una salida estructurada
del LLM local (Ollama). El modelo NUNCA devuelve YAML ni texto libre:
solo devuelve índices que apuntan a contenido que YA existe en master_cv.

Los límites (cuántas experiencias, bullets, etc.) vienen de config.json y
se inyectan acá en tiempo de ejecución — así el texto que ve el modelo
siempre coincide con lo que después va a forzar merge.py por código. El
límite REAL y duro está en merge.py, esto solo ayuda al modelo a elegir
mejor desde el principio.
"""
from typing import Any, Dict


def build_system_prompt(config: Dict[str, Any]) -> str:
    return f"""Sos un motor de selección de contenido para currículums (CV), optimizado para que el resultado entre en UNA SOLA PÁGINA y pase filtros ATS (Applicant Tracking Systems). Tu tarea, a partir de un CV maestro (`master_cv`) en JSON y una descripción de puesto (`job_description`), es elegir el contenido MÁS RELEVANTE Y MÁS CORTO posible — no el más completo.

REGLAS ABSOLUTAS (no negociables):
1. NUNCA inventes, agregues, completes, resumas ni corrijas texto que no exista literalmente en `master_cv`.
2. NUNCA alteres fechas, nombres de empresas, puestos, títulos, ni ningún dato factual.
3. Tu trabajo se limita a operaciones sobre datos EXISTENTES: SELECCIONAR (por índice), REORDENAR (por índice) y DETECTAR palabras clave que YA aparecen textualmente en `master_cv` (nunca inventarlas).
4. Preferí SIEMPRE menos contenido y más enfocado. El objetivo NO es mostrar todo lo que sabe la persona: es mostrar SOLO lo que importa para ESTA oferta puntual.

PRESUPUESTO DE UNA PÁGINA (obligatorio):
- Elegí como máximo {config['max_experience_entries']} experiencias laborales — las más relevantes para la oferta.
- Elegí como máximo {config['max_project_entries']} proyectos — los más relevantes para ESTA oferta puntual, NO todos los proyectos del master_cv.
- Para CADA experiencia o proyecto elegido, seleccioná como máximo {config['max_highlights_per_entry']} bullets (highlight_order), los que más matcheen con la oferta, ordenados de más a menos relevante.
- Elegí como máximo {config['max_skill_categories']} categorías de skills — las más relevantes para la oferta.
- En educación, el título principal (índice 0) se incluye siempre automáticamente (no lo elijas vos). Elegí como máximo {config['max_education_extra']} certificación(es) adicional(es) en "selected_education_indices" SOLO si son directamente relevantes para la oferta.

OPTIMIZACIÓN ATS (palabras clave):
- Identificá tecnologías, herramientas, metodologías y términos clave mencionados en `job_description` (ej: "Spring Boot", "Kubernetes", "Scrum", "SQL").
- En "keywords_detected" devolvé como máximo {config['max_keywords']} palabras clave, y SOLO las que ADEMÁS aparezcan literalmente en el texto de `master_cv`. Nunca incluyas una palabra clave que no esté respaldada por texto real del CV — el sistema las va a verificar y descartar igual si mentís.
- Al elegir highlight_order, priorizá primero los bullets que contengan esas palabras clave exactas de la oferta.
- Al elegir selected_skills_indices, priorizá primero las categorías de skills con más coincidencias con la oferta.

FORMATO DE SALIDA (JSON, esquema exacto — no agregues texto conversacional ni Markdown, solo el JSON):
{{
  "selected_experience": [{{"index": <int>, "highlight_order": [<int>, ...], "match_reason": "<string corta>"}}],
  "selected_projects": [{{"index": <int>, "highlight_order": [<int>, ...], "match_reason": "<string corta>"}}],
  "selected_education_indices": [<int>, ...],
  "selected_skills_indices": [<int>, ..., en orden de relevancia...],
  "summary_index": <int o null>,
  "keywords_detected": ["<string>", ..., SOLO si aparecen literalmente en master_cv...]
}}

ADVERTENCIA ANTI-COPIA (muy importante):
El ejemplo de abajo es SOLO para mostrar la FORMA del JSON — usa nombres y
tecnologías inventados (Xxx, Yyy) a propósito para que te resulte imposible
copiarlo por error. Tu respuesta real tiene que basarse EXCLUSIVAMENTE en el
`job_description` y el `master_cv` reales que te paso después del ejemplo.
Si la oferta real es corta, vaga o de una sola palabra (ej: "php"), NO
completes con tecnologías, herramientas o proyectos que no tengan relación
directa y explícita con esa oferta, aunque existan en el master_cv y aunque
el ejemplo de abajo las mencione — es preferible devolver "keywords_detected"
vacío o muy corto a inventar relevancia que no está.

EJEMPLO (solo formato, valores ficticios):
--- job_description (resumen) ---
"Buscamos perfil para el puesto P. Requisitos: tecnología Xxx, tecnología Yyy, metodología Zzz."

--- master_cv (fragmento ilustrativo) ---
sections.experience[0] = {{"company": "...", "highlights": ["bullet 0", "bullet 1", "bullet 2", "bullet 3 (sobre Xxx)", "..."]}}
sections.projects[0] = {{"name": "...", "highlights": ["bullet 0 (sobre Yyy)", "bullet 1", "..."]}}
sections.projects[1] = {{"name": "...", "highlights": ["...sin relación con Xxx/Yyy/Zzz..."]}}
sections.skills = [{{"label": "categoría A", ...}}, {{"label": "categoría B", ...}}]

--- salida esperada (estructura — los VALORES reales dependen 100% de la oferta y el master_cv que te den) ---
{{
  "selected_experience": [
    {{"index": 0, "highlight_order": [3, 0], "match_reason": "menciona Xxx, que pide la oferta"}}
  ],
  "selected_projects": [
    {{"index": 0, "highlight_order": [0], "match_reason": "menciona Yyy"}}
  ],
  "selected_education_indices": [],
  "selected_skills_indices": [0],
  "summary_index": 0,
  "keywords_detected": ["Xxx", "Yyy"]
}}

Notá: el proyecto index 1 quedó AFUERA por no tener relación con la oferta — no hay que incluir todo, solo lo que suma. Seguí este mismo criterio con la oferta y el master_cv REALES que se te van a pasar a continuación, no con este ejemplo."""


_SECTION_LABELS = {
    "experience": ("experiencias laborales", "selected_experience", "max_experience_entries"),
    "projects": ("proyectos", "selected_projects", "max_project_entries"),
    "skills": ("categorías de skills", "selected_skills_indices", "max_skill_categories"),
}


def build_section_system_prompt(config: Dict[str, Any], section_name: str) -> str:
    """Versión acotada del system prompt: se usa cuando el usuario pide
    'regenerar' una sola sección (no todo el CV). Mismas reglas anti-
    alucinación, pero el JSON de salida solo cubre esa sección."""
    label, key, max_key = _SECTION_LABELS[section_name]
    if section_name == "skills":
        output_hint = f'{{"selected_skills_indices": [<int>, ..., máx {config[max_key]}, en orden de relevancia...]}}'
    else:
        output_hint = (
            f'{{"{key}": [{{"index": <int>, "highlight_order": [<int>, ...máx {config["max_highlights_per_entry"]}...], '
            f'"match_reason": "<string corta>"}}], ...máx {config[max_key]} entradas...}}'
        )

    return f"""Sos un motor de selección de contenido para currículums. El usuario ya generó un CV para una oferta puntual, pero no le convenció la selección de {label} y pidió que la REGENERES — probá con una combinación distinta, igual de relevante o más, pero no repitas exactamente la misma selección si hay alternativas razonables en el master_cv.

REGLAS ABSOLUTAS (no negociables):
1. NUNCA inventes texto que no exista literalmente en `master_cv`. Solo podés SELECCIONAR (por índice) y REORDENAR (por índice) contenido existente.
2. NUNCA alteres fechas, nombres de empresas, puestos ni ningún dato factual.
3. Basate EXCLUSIVAMENTE en el `job_description` y el `master_cv` reales que te paso — no en ningún ejemplo.
4. Elegí como máximo {config[max_key]} {label}, y como máximo {config['max_highlights_per_entry']} bullets por entrada (si aplica).
5. Si la oferta es corta o ambigua, no fuerces relevancia que no existe — es preferible elegir menos.

Devolvé SOLO este JSON (sin texto conversacional, sin Markdown):
{output_hint}"""


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

    _, key, max_key = _SECTION_LABELS[section_name]
    return {
        "type": "object",
        "properties": {
            key: {
                "type": "array",
                "maxItems": config[max_key],
                "items": {
                    "type": "object",
                    "properties": {
                        "index": {"type": "integer"},
                        "highlight_order": {
                            "type": "array",
                            "maxItems": config["max_highlights_per_entry"],
                            "items": {"type": "integer"},
                        },
                        "match_reason": {"type": "string"},
                    },
                    "required": ["index", "highlight_order"],
                },
            }
        },
        "required": [key],
    }


def build_selection_schema(config: Dict[str, Any]) -> Dict[str, Any]:
    entry_schema = lambda max_highlights: {  # noqa: E731
        "type": "object",
        "properties": {
            "index": {"type": "integer"},
            "highlight_order": {
                "type": "array",
                "maxItems": max_highlights,
                "items": {"type": "integer"},
            },
            "match_reason": {"type": "string"},
        },
        "required": ["index", "highlight_order"],
    }

    return {
        "type": "object",
        "properties": {
            "selected_experience": {
                "type": "array",
                "maxItems": config["max_experience_entries"],
                "items": entry_schema(config["max_highlights_per_entry"]),
            },
            "selected_projects": {
                "type": "array",
                "maxItems": config["max_project_entries"],
                "items": entry_schema(config["max_highlights_per_entry"]),
            },
            "selected_education_indices": {
                "type": "array",
                "maxItems": config["max_education_extra"],
                "items": {"type": "integer"},
            },
            "selected_skills_indices": {
                "type": "array",
                "maxItems": config["max_skill_categories"],
                "items": {"type": "integer"},
            },
            "summary_index": {"type": ["integer", "null"]},
            "keywords_detected": {
                "type": "array",
                "maxItems": config["max_keywords"],
                "items": {"type": "string"},
            },
        },
        "required": ["selected_experience", "selected_projects", "selected_skills_indices"],
    }