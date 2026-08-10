"""Procesamiento de Job Descriptions para el pipeline de IR.

Incluye:
- Extracción heurística de la sección de requisitos técnicos.
- Chunking con ventana deslizante para evitar truncamiento por límite de tokens.
- Detección de términos negados / excluidos de la oferta (P0.2): cuando el
  JD dice "no se requiere X", X no debe rankear como requisito positivo.
"""

import re

from .keywords import extract_keywords
from .sparse import keyword_in_text
from .stopwords import is_stopword


def extract_requirements_section(jd: str) -> str:
    """Extrae la sección de requisitos/qualifications del JD.

    Si no encuentra delimitadores conocidos, devuelve el JD completo.
    El resultado se usa como query fija para el cross-encoder.
    """
    patterns = [
        # Secciones que SÍ son requisitos (empiezan acá el contenido)
        r"(?:Requisitos|Requirements|Qualifications|What you need|Must have|Responsabilidades|Responsibilities|Perfil buscado|Lo que buscamos|Buscamos)[\s:]*(.+?)(?=\n(?:Ofrecemos|Ofreceremos|Beneficios|Qué ofrecemos|Que ofrecemos|What we offer|Nice to have|Deseable|About us|About the company|Quiénes somos|Sobre nosotros|Apply now|Postulate|Postúlate|Postulate ya|Aplicá|Aplica|Cómo postularme|Como postularme|Cómo aplicar|Salario|Remuneración|Remuneracion|Compensación|Compensacion|$))",
        # Secciones que NO son requisitos (cortan el contenido)
        r"(?:Nice to have|Deseable|Plus|Preferred)[\s:]*(.+?)(?=\n|$)",
    ]
    for pattern in patterns:
        match = re.search(pattern, jd, re.IGNORECASE | re.DOTALL)
        if match:
            return match.group(1).strip()
    return jd.strip()


def chunk_text(text: str, max_tokens: int = 200, overlap: int = 50) -> list[str]:
    """Divide el texto en chunks de aproximadamente max_tokens palabras
    con overlap para no perder contexto en los bordes.

    Usado para el JD antes de pasarlo al encoder denso (los sentence-transformers
    truncan los textos largos, así que el JD completo se divide en chunks).
    """
    words = text.split()
    if len(words) <= max_tokens:
        return [text]
    chunks = []
    start = 0
    while start < len(words):
        end = min(start + max_tokens, len(words))
        chunks.append(" ".join(words[start:end]))
        start += max_tokens - overlap
        if end == len(words):
            break
    return chunks


# ---------------------------------------------------------------------------
# P0.2: negación / exclusiones del JD
# ---------------------------------------------------------------------------

# Marcadores de negación ES/EN. La regla es: si una ORACIÓN (segmento entre
# puntos/! /? /saltos de línea) contiene alguno de estos, es una "zona
# negada" y sus términos técnicos dejan de ser requisitos positivos.
# Deliberadamente conservador: solo frases inequívocas de exclusión, no
# negaciones vagas ("no nos gusta", "no solo").
_NEGATION_PATTERNS = (
    re.compile(r"no\s+se\s+requiere", re.IGNORECASE),
    re.compile(r"no\s+se\s+requieren", re.IGNORECASE),
    re.compile(r"no\s+se\s+necesita", re.IGNORECASE),
    re.compile(r"no\s+se\s+necesitan", re.IGNORECASE),
    re.compile(r"no\s+es\s+necesario", re.IGNORECASE),
    re.compile(r"no\s+es\s+requisito", re.IGNORECASE),
    re.compile(r"no\s+es\s+excluyente", re.IGNORECASE),
    re.compile(r"no\s+buscamos|no\s+estamos\s+buscando", re.IGNORECASE),
    re.compile(r"no\s+se\s+valora|no\s+se\s+valoran", re.IGNORECASE),
    re.compile(r"excluyente\s*:\s*no", re.IGNORECASE),
    re.compile(r"not\s+required|is\s+not\s+required|not\s+a\s+requirement", re.IGNORECASE),
    re.compile(r"not\s+necessary|not\s+needed", re.IGNORECASE),
    re.compile(r"no\s+experience(?:\s+in|\s+with|\s+of)?", re.IGNORECASE),
    re.compile(r"not\s+looking\s+for", re.IGNORECASE),
    re.compile(r"no\s+need\s+(?:for|to)?", re.IGNORECASE),
)

_SENTENCE_SPLIT_RE = re.compile(r"[.!?\n]+")

# Palabras genéricas de ofertas que NO son términos técnicos aunque
# aparezcan en un fragmento negado ("No se requiere EXPERIENCIA en...").
# Sin este filtro, "experiencia" penalizaría cualquier bullet del master
# que la mencione — el caso de ruido más probable de la heurística.
_GENERIC_JD_WORDS = frozenset({
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


def _clean_negation_tokens(fragment: str) -> list[str]:
    """Tokens candidatos de un fragmento negado: minúsculas, sin stopwords
    ni palabras genéricas de ofertas. Solo los tokens que representan
    contenido técnico potencial quedan para el doble chequeo con master."""
    words = re.findall(r"[a-zA-ZáéíóúñüÁÉÍÓÚÑÜ][\w+#.-]*", fragment)
    tokens = []
    for word in words:
        low = word.lower()
        if is_stopword(low) or low in _GENERIC_JD_WORDS:
            continue
        if len(low) < 3:
            continue
        tokens.append(low)
    return tokens


def extract_negated_terms(jd: str, master_corpus: str = "") -> set[str]:
    """Términos que la oferta EXCLUYE explícitamente ("no se requiere X").

    Detección: se divide el JD en oraciones y se marcan las que contienen
    un marcador de negación (ES/EN). De esas oraciones salen los
    candidatos:

    1. Términos del diccionario curado (TECH_KEYWORDS): se devuelven
       directo — son unívocos y "no se requiere Docker" es inequívoco.
    2. N-gramas abiertos (1-2 palabras) del fragmento, filtrando stopwords
       y palabras genéricas de ofertas ("experiencia", "conocimientos"...).
       Para no penalizar ruido, un candidato abierto solo sobrevive si
       existe literalmente (o alguna variante sinónima) en el master
       (`keyword_in_text`) — mismo doble chequeo que las open keywords:
       si el usuario no tiene nada de ese tema, penalizar es un no-op.

    Regla de JD contradictorio: si un término negado TAMBIÉN aparece en
    una oración NO negada del JD, la mención positiva gana y el término no
    se penaliza (evitar falsos negativos agresivos).

    Args:
        jd: texto completo de la oferta (NO la sección de requisitos: la
            cláusula de exclusión suele estar fuera de esa sección).
        master_corpus: texto del CV maestro (lowercase). Sin él, solo se
            detectan términos del diccionario curado.

    Returns:
        Set de términos negados (minúsculas), vacío si no hay negaciones.
    """
    if not jd:
        return set()

    sentences = [s.strip() for s in _SENTENCE_SPLIT_RE.split(jd) if s.strip()]
    negated_sentences = [
        s for s in sentences if any(p.search(s) for p in _NEGATION_PATTERNS)
    ]
    if not negated_sentences:
        return set()

    fragment = " ".join(negated_sentences)
    positive = " ".join(s for s in sentences if s not in negated_sentences)

    candidates: set[str] = set()

    dict_terms, _ = extract_keywords(fragment)
    candidates.update(dict_terms)

    tokens = _clean_negation_tokens(fragment)
    for token in tokens:
        if keyword_in_text(token, master_corpus):
            candidates.add(token)
    for i in range(len(tokens) - 1):
        bigram = f"{tokens[i]} {tokens[i + 1]}"
        if keyword_in_text(bigram, master_corpus):
            candidates.add(bigram)

    # JD contradictorio: la mención positiva desactiva la penalización.
    return {c for c in candidates if c and not keyword_in_text(c, positive)}
