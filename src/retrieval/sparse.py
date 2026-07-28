"""Índice BM25 por sección para matching léxico + sinónimos.

Usa rank-bm25 (Python puro) con expansión de sinónimos técnicos.
Cada sección tiene su propio índice BM25 independiente.
"""

import re

import numpy as np
from rank_bm25 import BM25Okapi

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
# Stopwords combinadas ES + EN para retrieval léxico.
# NO aplicar en embeddings densos ni en extracción de keywords técnicas.
# ------------------------------------------------------------------
COMBINED_STOPWORDS = {
    # --- Español ---
    "el", "la", "los", "las", "un", "una", "unos", "unas", "lo", "al", "del",
    "de", "a", "en", "por", "para", "con", "sin", "sobre", "entre", "hacia",
    "desde", "hasta", "bajo", "ante", "tras", "durante", "según", "mediante",
    "excepto", "salvo", "contra",
    "y", "e", "o", "u", "ni", "pero", "sino", "aunque", "porque", "pues", "como",
    "cuando", "donde", "mientras",
    "ya", "todavía", "aún", "aquí", "allí", "ahora", "antes", "después", "luego",
    "entonces", "así", "bien", "mal", "muy", "mucho", "poco", "más", "menos", "tan",
    "tanto", "también", "tampoco", "sí", "no", "apenas",
    "que", "quien", "cual", "cuyo", "cuanto",
    "yo", "tú", "él", "ella", "nosotros", "vosotros", "ellos", "ellas", "me", "te",
    "se", "le", "les", "nos", "os", "mi", "tu", "su", "nuestro", "vuestra", "este",
    "ese", "aquel", "esto", "eso", "aquello", "mío", "tuyo", "suyo", "nuestra",
    "vuestra", "míos", "tuyos", "suyos", "nuestras", "vuestras",
    # Verbos auxiliares / funcionales comunes (infinitivo + 3ra persona presente/pasado)
    "ser", "es", "son", "fue", "era", "soy", "eres", "somos", "sois", "fui",
    "fuiste", "fueron", "fuimos", "fuisteis", "sea", "seas", "seamos", "seáis",
    "sean", "sido", "estado", "siendo",
    "haber", "ha", "han", "había", "habían", "he", "has", "hemos", "habéis", "haya",
    "tener", "tiene", "tienen", "tenía", "tenían", "tengo", "tienes", "tenemos",
    "tenéis", "tuvieron", "tuvimos", "tuvisteis",
    "hacer", "hace", "hacen", "hizo", "hicieron", "hacemos", "hacéis", "hicimos",
    "hicisteis",
    "poder", "puede", "pueden", "podía", "podían", "puedo", "puedes", "podemos",
    "podéis",
    "decir", "dice", "dicen", "dijo", "dijeron", "decimos", "decís", "dijimos",
    "dijisteis",
    "ir", "va", "van", "iba", "iban", "voy", "vas", "vamos", "vais",
    "ver", "ve", "ven", "vio", "vieron", "vimos", "visteis",
    "dar", "da", "dan", "dio", "dieron", "damos", "dais",
    "saber", "sabe", "saben", "sabía", "sabían", "sé", "sabes", "sabemos", "sabéis",
    "querer", "quiere", "quieren", "quería", "querían", "quiero", "quieres",
    "queremos", "queréis",
    "llegar", "llega", "llegan", "llegó", "llegaron",
    "pasar", "pasa", "pasan", "pasó", "pasaron",
    "deber", "debe", "deben", "debía", "debían",
    "poner", "pone", "ponen", "puso", "pusieron",
    "parecer", "parece", "parecen", "parecía", "parecían",
    "quedar", "queda", "quedan", "quedó", "quedaron",
    "pensar", "piensa", "piensan", "pensó", "pensaron",
    "salir", "sale", "salen", "salió", "salieron",
    "volver", "vuelve", "vuelven", "volvió", "volvieron",
    "tomar", "toma", "toman", "tomó", "tomaron",
    "conseguir", "consigue", "consiguen", "consiguió", "consiguieron",
    "empezar", "empieza", "empiezan", "empezó", "empezaron",
    "sentir", "siente", "sienten", "sintió", "sintieron",
    "tratar", "trata", "tratan", "trató", "trataron",
    "mantener", "mantiene", "mantienen", "mantuvo", "mantuvieron",
    "terminar", "termina", "terminan", "terminó", "terminaron",
    "llevar", "lleva", "llevan", "llevó", "llevaron",
    "encontrar", "encuentra", "encuentran", "encontró", "encontraron",
    "seguir", "sigue", "siguen", "siguió", "siguieron",
    "crear", "crea", "crean", "creó", "crearon",
    "dejar", "deja", "dejan", "dejó", "dejaron",
    # --- Inglés (lista original + ampliación básica) ---
    "the", "and", "for", "with", "you", "will", "are", "our", "that", "have",
    "this", "your", "from", "they", "been", "their", "what", "when", "where",
    "than", "then", "them", "these", "those", "being", "having", "doing",
    "about", "into", "through", "during", "before", "after", "above", "below",
    "between", "under", "over", "again", "further", "once", "here", "there",
    "why", "how", "all", "any", "both", "each", "few", "more", "most", "other",
    "some", "such", "only", "own", "same", "so", "too", "very", "can",
    "just", "should", "now", "use", "using", "used", "work", "working", "worked",
    "experience", "experienced", "years", "year", "least", "plus", "good", "strong",
    "excellent", "solid", "deep", "proven", "track", "record", "ability", "able",
    "looking", "seeking", "join", "team", "company", "role", "position", "job",
    "a", "an", "as", "at", "be", "by", "do", "did", "does", "done", "had", "has",
    "he", "her", "him", "his", "i", "if", "in", "is", "it", "its", "me", "my",
    "not", "of", "on", "or", "out", "she", "to", "up", "us", "was", "we", "were",
}


def tokenize_with_synonyms(text: str) -> list[str]:
    """Tokeniza un texto en palabras y expande con sinónimos conocidos.

    Captura términos compuestos (bigramas) y términos con slash.
    Las stopwords se filtran DESPUÉS de la expansión de sinónimos,
    para no descartar un sinónimo expandido que por casualidad
    coincida con la lista.
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

    # Filtrar stopwords DESPUÉS de expandir sinónimos
    return [t for t in expanded if t not in COMBINED_STOPWORDS]


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