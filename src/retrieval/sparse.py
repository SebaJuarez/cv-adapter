"""Índice BM25 por sección para matching léxico + sinónimos.

Usa rank-bm25 (Python puro) con expansión de sinónimos técnicos.
Cada sección tiene su propio índice BM25 independiente.
"""

import re

import numpy as np
from nltk.stem.snowball import SnowballStemmer
from rank_bm25 import BM25Okapi

from .stopwords import is_stopword

# Stemmers Snowball (ES + EN) para generalizar variantes morfológicas
# ("trabajo/trabajé/trabajando" -> "trabaj", "containers/containerized" -> "container").
# El corpus es ES/EN mezclado y no hay forma fiable de asignar idioma por
# token: se toma el stem MÁS CORTO entre ambos idiomas, porque el stemmer
# "equivocado" típicamente no modifica la palabra y entonces gana el que sí
# la normalizó. El criterio es idéntico para query y documentos, así que el
# matching siempre es consistente.
_STEMMER_ES = SnowballStemmer("spanish")
_STEMMER_EN = SnowballStemmer("english")

# Flag de stemming a nivel de módulo: sparse.py es un módulo hoja sin acceso
# a config, y SelectionEngine lo sincroniza desde config["use_stemming"] al
# construirse (ver selection.py). El hash del índice persistido incluye este
# flag, así que apagarlo/encenderlo reconstruye el corpus BM25.
_STEMMING_ENABLED = True


def set_stemming(enabled: bool) -> None:
    """Activa o desactiva el stemming del tokenizador BM25 (config use_stemming)."""
    global _STEMMING_ENABLED
    _STEMMING_ENABLED = bool(enabled)


def _stem_token(token: str) -> str:
    """Stem de un token: el más corto entre ES y EN (ver _STEMMER_ES).

    Solo tokens puramente alfabéticos: los que tienen separadores ("ci/cd",
    "c++", "next.js") son términos técnicos exactos y el stemmer los mutila
    ("next.js" -> "next.j" con el stemmer de inglés), así que se devuelven
    tal cual.
    """
    if not re.fullmatch(r"[a-záéíóúñü]+", token):
        return token
    es_stem = _STEMMER_ES.stem(token)
    en_stem = _STEMMER_EN.stem(token)
    if len(es_stem) < len(en_stem):
        return es_stem
    if len(en_stem) < len(es_stem):
        return en_stem
    return en_stem  # empate: preferir el stem de inglés

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


def keyword_in_text(keyword: str, text: str) -> bool:
    """¿Aparece la keyword (o alguna variante sinónima) como término completo
    en el texto?

    Matching case-insensitive con límites de palabra, para evitar los falsos
    positivos del substring simple: "js" NO matchea dentro de "jsp" ni "json",
    pero SÍ matchea "node.js" y "ci/cd" (un separador no-alfanumérico es un
    límite válido). Única fuente de verdad de sinónimos: SYNONYMS.
    """
    text_low = text.lower()
    for variant in get_synonym_variants(keyword):
        pattern = re.compile(r"(^|[^a-z0-9])" + re.escape(variant) + r"([^a-z0-9]|$)")
        if pattern.search(text_low):
            return True
    return False


def tokenize_with_synonyms(text: str) -> list[str]:
    """Tokeniza un texto en palabras y expande con sinónimos conocidos.

    Captura términos compuestos (bigramas) y términos con slash ("ci/cd").
    Para los términos con slash NO se reemplaza el separador antes de
    tokenizar: si se hiciera ("ci/cd" -> "ci / cd"), el token original se
    rompe en partes y el lookup en SYNONYMS nunca matchea (bug C3).
    """
    text = text.lower().replace("-", " ")
    words = text.split()

    expanded = []
    i = 0
    while i < len(words):
        # Intentar bigrama primero ("gh actions" -> github actions)
        if i + 1 < len(words):
            bigram = words[i] + " " + words[i + 1]
            if bigram in SYNONYMS:
                expanded.append(bigram)
                for syn in SYNONYMS[bigram]:
                    expanded.extend(syn.split())
                i += 2
                continue
        # Unigrama (incluye términos con slash como "ci/cd" o "gh")
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
    filtered = [t for t in expanded if not is_stopword(t)]

    # Stemming DESPUÉS de filtrar stopwords: si se stemmea antes, una
    # stopword puede quedar en una forma que ya no está en la lista
    # ("was" -> "wa") y colarse al índice de un corpus donde cada término
    # vacío cuenta. Solo aplica si use_stemming está activo.
    if _STEMMING_ENABLED:
        return [_stem_token(t) for t in filtered]
    return filtered


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