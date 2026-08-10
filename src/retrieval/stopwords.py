"""Stopwords compartidas para el pipeline de retrieval léxico (BM25).

IMPORTANTE — alcance deliberadamente acotado:
Este filtro se usa SOLO en el camino léxico (BM25, ver sparse.py) y en la
generación de texto explicativo (match_reason, ver selection.py). NO se debe
usar antes de encodear texto con el modelo denso (dense.py): los
sentence-transformers están entrenados con oraciones naturales completas,
incluyendo artículos/preposiciones, y sacarlas antes de encodear generalmente
empeora la calidad semántica en vez de mejorarla. El stopword removal es una
técnica de IR léxico clásico, no de embeddings.

El corpus de cada sección acá es chico (un puñado de bullets de un solo
candidato), así que el IDF de BM25 no diluye estadísticamente las palabras
vacías tan bien como en un corpus grande — de ahí que convenga filtrarlas
de forma explícita en vez de confiar solo en el IDF.
"""

STOPWORDS_EN: frozenset[str] = frozenset({
    "a", "an", "the", "and", "or", "but", "if", "then", "than", "so",
    "for", "with", "without", "of", "to", "in", "on", "at", "by", "from",
    "up", "down", "out", "off", "over", "under", "again", "further",
    "once", "here", "there", "when", "where", "why", "how", "all", "any",
    "both", "each", "few", "more", "most", "other", "some", "such",
    "only", "own", "same", "too", "very", "can", "will", "just", "should",
    "now", "is", "are", "was", "were", "be", "been", "being", "have",
    "has", "had", "having", "do", "does", "did", "doing", "you", "your",
    "yours", "yourself", "we", "our", "ours", "they", "their", "theirs",
    "them", "this", "that", "these", "those", "it", "its", "as", "about",
    "into", "through", "during", "before", "after", "above", "below",
    "between", "not", "no", "nor",
})

STOPWORDS_ES: frozenset[str] = frozenset({
    "el", "la", "los", "las", "un", "una", "unos", "unas", "de", "del",
    "al", "y", "o", "u", "pero", "si", "no", "que", "quien", "quienes",
    "para", "por", "con", "sin", "sobre", "entre", "hacia", "hasta",
    "desde", "durante", "mediante", "segun", "según", "ante", "bajo",
    "tras", "en", "es", "son", "fue", "fueron", "ser", "estar", "esta",
    "está", "estas", "están", "esto", "eso", "aquello", "este", "esa",
    "ese", "aquel", "aquella", "mi", "tu", "su", "sus", "nuestro",
    "nuestra", "nuestros", "nuestras", "yo", "tu2", "el2", "ella",
    "nosotros", "ustedes", "ellos", "ellas", "lo", "le", "les", "se",
    "muy", "mas", "más", "menos", "todo", "toda", "todos", "todas",
    "otro", "otra", "otros", "otras", "cada", "algun", "algún", "alguna",
    "algunos", "algunas", "ningun", "ningún", "ninguna", "solo", "sólo",
    "asi", "así", "tambien", "también", "cuando", "donde", "dónde",
    "como", "cómo", "porque", "por qué",
})

# Términos técnicos cortos que jamás se deben filtrar aunque coincidan
# por casualidad con alguna forma de una stopword genérica (ej. "r" como
# lenguaje, "go" como lenguaje, "ci"/"cd" en CI/CD, "ml"/"ai" como siglas).
TECH_ALLOWLIST: frozenset[str] = frozenset({
    "r", "go", "c", "js", "ts", "ci", "cd", "ai", "ml", "nlp", "qa",
    "ui", "ux", "os", "io", "vr", "ar", "db", "api", "sql", "aws",
    "gcp", "sre", "dry", "kiss", "xp",
})

STOPWORDS: frozenset[str] = (STOPWORDS_EN | STOPWORDS_ES) - TECH_ALLOWLIST

# Palabras genéricas de ofertas laborales que NO son términos técnicos
# aunque aparezcan en contextos de extracción ("No se requiere EXPERIENCIA
# en...", "Buscamos un PERFIL backend"). Sin este filtro, "experiencia" o
# "conocimientos" se colarían como keywords abiertas (P1.1) o términos
# negados (P0.2). Compartido entre jd_processor y keywords (un módulo hoja
# no puede importar al otro sin circularidad).
GENERIC_JD_WORDS: frozenset[str] = frozenset({
    # Español
    "experiencia", "conocimiento", "conocimientos", "manejo", "nivel",
    "años", "año", "ingles", "inglés", "titulo", "título", "estudios",
    "carrera", "universidad", "deseable", "excluyente", "requerido",
    "requerida", "requisito", "requisitos", "obligatorio", "trabajo",
    "laboral", "perfil", "puesto", "cargo", "empresa", "idioma", "idiomas",
    "modalidad", "jornada", "horario", "salario", "sueldo", "beneficios",
    "búsqueda", "busqueda", "candidato", "candidatos", "disponibilidad",
    "remoto", "remota", "híbrido", "hibrido", "hibrida", "híbrida",
    "presencial", "senior", "junior", "semi", "mid", "sr", "jr", "ssr",
    # Inglés
    "experience", "years", "year", "knowledge", "level", "english",
    "spanish", "degree", "required", "requirement", "requirements",
    "candidate", "candidates", "job", "work", "role", "position",
    "company", "skills", "skill", "bachelor", "master", "university",
    "desired", "preferred", "must", "need", "needed", "remote", "hybrid",
    "onsite", "salary", "benefits", "language", "languages", "availability",
})


def is_stopword(token: str) -> bool:
    return token.lower() in STOPWORDS