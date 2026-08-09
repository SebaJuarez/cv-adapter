"""Procesamiento de Job Descriptions para el pipeline de IR.

Incluye:
- Extracción heurística de la sección de requisitos técnicos.
- Chunking con ventana deslizante para evitar truncamiento por límite de tokens.
"""

import re


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

    Usado para el JD antes de pasarlo al dense encoder (MiniLM trunca a 256 tokens).
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
