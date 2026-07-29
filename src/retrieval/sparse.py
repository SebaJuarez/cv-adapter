"""Índice BM25 por sección para matching léxico + sinónimos.

Usa rank-bm25 (Python puro) con expansión de sinónimos técnicos.
Cada sección tiene su propio índice BM25 independiente.
"""

import re

import numpy as np
from rank_bm25 import BM25Okapi

from .stopwords import is_stopword

# Diccionario curado de sinónimos técnicos para expandir queries.
# Se aplica tanto a la query (JD) como a los documentos (bullets).
# NOTA: cada clave debe ser única. Para términos ambiguos, preferir
# la forma más común o manejarlo por contexto.
SYNONYMS = {
    "postgres": ["postgresql"],
    "k8s": ["kubernetes"],
    "gh actions": ["github actions"],
    "js": ["javascript"],
    "ts": ["typescript"],
    "py": ["python"],
    "tf": ["tensorflow"],  # "terraform" se maneja como forma completa
    "terraform": ["infrastructure as code", "iac"],
    "aws": ["amazon web services"],
    "gcp": ["google cloud platform"],
    "azure": ["microsoft azure"],
    "ci/cd": ["continuous integration", "continuous delivery", "continuous deployment"],
    "rest": ["restful"],
    "api": ["apis"],
    "db": ["database"],
    "ml": ["machine learning"],
    "ai": ["artificial intelligence"],
    "nlp": ["natural language processing"],
    "cv": ["computer vision"],
    "oop": ["object oriented programming"],
    "fp": ["functional programming"],
    "sql": ["structured query language"],
    "nosql": ["mongodb", "cassandra", "dynamodb", "couchdb"],
    "agile": ["scrum", "kanban"],
    "devops": ["sre", "site reliability engineering"],
}


# ------------------------------------------------------------------
# Mapa bidireccional de sinónimos, expuesto para quien necesite
# "¿esta keyword y esta otra son la misma cosa?" fuera del tokenizador
# BM25 (ej. merge.py para verificar keywords ATS, o el canal de
# keyword-boost del RRF). Única fuente de verdad: si se agrega un
# sinónimo acá, todo el pipeline lo ve igual.
# ------------------------------------------------------------------
_SYNONYM_GROUPS: dict[str, set[str]] = {}
for _key, _syns in SYNONYMS.items():
    _group = {_key.lower()} | {s.lower() for s in _syns}
    for _term in _group:
        _SYNONYM_GROUPS[_term] = _group


def get_synonym_variants(keyword: str) -> set[str]:
    """Devuelve todas las variantes sinónimas de una keyword (incluida ella
    misma). Si no está en la tabla, devuelve un singleton con ella misma."""
    kw_low = keyword.lower().strip()
    return _SYNONYM_GROUPS.get(kw_low, {kw_low})


def tokenize_with_synonyms(text: str) -> list[str]:
    """Tokeniza un texto en palabras y expande con sinónimos conocidos.

    Captura términos compuestos (bigramas) y términos con slash.
    """
    text = text.lower()
    # Normalizar separadores: reemplazar guiones por espacios para bigramas
    text = text.replace("-", " ").replace("/", " / ")

    tokens = re.findall(r"\b\w+(?:\s+/\s+\w+)?\b", text)
    # También capturar bigramas comunes manualmente
    words = text.split()

    expanded = []
    i = 0
    while i < len(words):
        # Intentar bigrama primero
        if i + 1 < len(words):
            bigram = words[i] + " " + words[i + 1]
            if bigram in SYNONYMS:
                expanded.append(bigram)
                for syn in SYNONYMS[bigram]:
                    expanded.extend(syn.split())
                i += 2
                continue
        # Unigrama
        token = words[i]
        expanded.append(token)
        if token in SYNONYMS:
            for syn in SYNONYMS[token]:
                expanded.extend(syn.split())
        i += 1

    # Filtrar stopwords DESPUÉS de expandir sinónimos (así un bigrama tipo
    # "gh actions" ya quedó armado antes de tocar nada). Con un corpus tan
    # chico por sección, el IDF de BM25 no diluye solo las palabras vacías
    # como lo haría en un corpus grande, así que conviene sacarlas a mano.
    return [t for t in expanded if not is_stopword(t)]


class SparseIndex:
    """Índice BM25 para una sección del CV.

    Cada bullet es un documento. La query es el JD (tokenizado con sinónimos).
    """

    def __init__(self):
        self.bm25: BM25Okapi | None = None
        self.bullet_ids: list[str] = []

    def build(self, bullet_docs: list[dict]) -> None:
        """Construye el índice BM25 a partir de una lista de BulletDoc dicts."""
        self.bullet_ids = [b["id"] for b in bullet_docs]
        tokenized = [tokenize_with_synonyms(b["text"]) for b in bullet_docs]
        self.bm25 = BM25Okapi(tokenized)

    def query(self, query_text: str, top_k: int = 50) -> list[str]:
        """Devuelve los top_k bullet_ids ordenados por score BM25 descendente."""
        if self.bm25 is None or not self.bullet_ids:
            return []
        tokens = tokenize_with_synonyms(query_text)
        scores = self.bm25.get_scores(tokens)
        n = len(scores)
        k = min(top_k, n)
        if k == 0:
            return []
        top_indices = np.argpartition(scores, -k)[-k:]
        top_indices = top_indices[np.argsort(scores[top_indices])[::-1]]
        return [self.bullet_ids[i] for i in top_indices]