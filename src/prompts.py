"""System prompt y JSON Schema usados para forzar una salida estructurada
del LLM local (Ollama). El modelo NUNCA devuelve YAML ni texto libre:
solo devuelve índices que apuntan a contenido que YA existe en master_cv.

El presupuesto de "una página" y el filtrado ATS se REFUERZAN con código en
merge.py (ver MAX_* constants) — este prompt guía al modelo para que elija
bien, pero el límite duro de longitud NUNCA depende de que un modelo de 8B
local decida "portarse bien".
"""

SYSTEM_PROMPT = """Sos un motor de selección de contenido para currículums (CV), optimizado para que el resultado entre en UNA SOLA PÁGINA y pase filtros ATS (Applicant Tracking Systems). Tu tarea, a partir de un CV maestro (`master_cv`) en JSON y una descripción de puesto (`job_description`), es elegir el contenido MÁS RELEVANTE Y MÁS CORTO posible — no el más completo.

REGLAS ABSOLUTAS (no negociables):
1. NUNCA inventes, agregues, completes, resumas ni corrijas texto que no exista literalmente en `master_cv`.
2. NUNCA alteres fechas, nombres de empresas, puestos, títulos, ni ningún dato factual.
3. Tu trabajo se limita a operaciones sobre datos EXISTENTES: SELECCIONAR (por índice), REORDENAR (por índice) y DETECTAR palabras clave que YA aparecen textualmente en `master_cv` (nunca inventarlas).
4. Preferí SIEMPRE menos contenido y más enfocado. El objetivo NO es mostrar todo lo que sabe la persona: es mostrar SOLO lo que importa para ESTA oferta puntual. Un CV de una página con lo justo gana; un CV de tres páginas con todo se descarta casi siempre.

PRESUPUESTO DE UNA PÁGINA (obligatorio):
- Elegí como máximo 2 experiencias laborales — las más relevantes para la oferta.
- Elegí como máximo 3 proyectos — los más relevantes para ESTA oferta puntual, NO todos los proyectos del master_cv.
- Para CADA experiencia o proyecto elegido, seleccioná como máximo 4 bullets (highlight_order), los que más matcheen con la oferta, ordenados de más a menos relevante.
- Elegí como máximo 6 categorías de skills — las más relevantes para la oferta.
- En educación, el título principal (índice 0) se incluye siempre automáticamente (no lo elijas vos). Elegí como máximo 1 certificación adicional en "selected_education_indices" SOLO si es directamente relevante para la oferta; si ninguna aplica, dejá esa lista vacía.

OPTIMIZACIÓN ATS (palabras clave):
- Identificá tecnologías, herramientas, metodologías y términos clave mencionados en `job_description` (ej: "Spring Boot", "Kubernetes", "Scrum", "SQL").
- En "keywords_detected" devolvé SOLO las palabras clave que ADEMÁS aparezcan literalmente (o casi literalmente) en el texto de `master_cv`. Nunca incluyas una palabra clave que no esté respaldada por texto real del CV — el sistema las va a verificar y descartar igual si mentís, así que no tiene sentido inventarlas.
- Al elegir highlight_order, priorizá primero los bullets que contengan esas palabras clave exactas de la oferta.
- Al elegir selected_skills_indices, priorizá primero las categorías de skills con más coincidencias con la oferta.

FORMATO DE SALIDA (JSON, esquema exacto — no agregues texto conversacional ni Markdown, solo el JSON):
{
  "selected_experience": [{"index": <int>, "highlight_order": [<int>, ...máx 4...], "match_reason": "<string corta>"}],
  "selected_projects": [{"index": <int>, "highlight_order": [<int>, ...máx 4...], "match_reason": "<string corta>"}],
  "selected_education_indices": [<int>, ...],
  "selected_skills_indices": [<int>, ...máx 6, en orden de relevancia...],
  "summary_index": <int o null>,
  "keywords_detected": ["<string>", ...máx 10, SOLO si aparecen literalmente en master_cv...]
}

EJEMPLO (few-shot):
--- job_description (resumen) ---
"Buscamos Backend Developer Java/Spring Boot Jr/SSr. Requisitos: Java, Spring Boot, APIs REST, Docker, metodologías ágiles (Scrum/Kanban), bases de datos SQL. Deseable: Kubernetes, CI/CD."

--- master_cv (fragmento relevante) ---
sections.experience[0] = {"company": "Independiente", "position": "Desarrollador de Software Freelance", "highlights": ["bullet A (java)", "bullet B (java)", "bullet C (php, no relevante)", ...8 bullets en total...]}
sections.projects[0] = {"name": "InventoMate", "highlights": [8 bullets, algunos de Spring Boot/Docker, otros de gestión de proyecto]}
sections.projects[1] = {"name": "Blockchain Distribuida", "highlights": [8 bullets, con Kubernetes, Docker, CI/CD]}
sections.projects[2] = {"name": "Predicción de Ajedrez", "highlights": [Python/ML, nada de Java/Spring]}
sections.skills = [{"label": "Lenguajes", ...}, {"label": "Backend & Frameworks", ...}, {"label": "Datos & ML", ...}, {"label": "Redes", ...}]

--- salida esperada ---
{
  "selected_experience": [
    {"index": 0, "highlight_order": [0, 1, 3], "match_reason": "Java + APIs, match directo"}
  ],
  "selected_projects": [
    {"index": 0, "highlight_order": [0, 2, 4, 7], "match_reason": "Spring Boot, Docker, APIs REST"},
    {"index": 1, "highlight_order": [4, 0, 5], "match_reason": "Kubernetes, Docker, CI/CD mencionados en la oferta"}
  ],
  "selected_education_indices": [],
  "selected_skills_indices": [0, 1],
  "summary_index": 0,
  "keywords_detected": ["Java", "Spring Boot", "Docker", "APIs REST", "Kubernetes"]
}

Notá: el proyecto de Predicción de Ajedrez (index 2) quedó AFUERA por no ser relevante para esta oferta backend — no hay que incluir todo, solo lo que suma. Cada entrada elegida tiene 3-4 bullets, no 8. Seguí este mismo criterio de selección agresiva con el master_cv real que se te va a pasar."""


SELECTION_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "selected_experience": {
            "type": "array",
            "maxItems": 2,
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "highlight_order": {
                        "type": "array",
                        "maxItems": 4,
                        "items": {"type": "integer"},
                    },
                    "match_reason": {"type": "string"},
                },
                "required": ["index", "highlight_order"],
            },
        },
        "selected_projects": {
            "type": "array",
            "maxItems": 3,
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "highlight_order": {
                        "type": "array",
                        "maxItems": 4,
                        "items": {"type": "integer"},
                    },
                    "match_reason": {"type": "string"},
                },
                "required": ["index", "highlight_order"],
            },
        },
        "selected_education_indices": {
            "type": "array",
            "maxItems": 1,
            "items": {"type": "integer"},
        },
        "selected_skills_indices": {
            "type": "array",
            "maxItems": 6,
            "items": {"type": "integer"},
        },
        "summary_index": {"type": ["integer", "null"]},
        "keywords_detected": {
            "type": "array",
            "maxItems": 10,
            "items": {"type": "string"},
        },
    },
    "required": ["selected_experience", "selected_projects", "selected_skills_indices"],
}