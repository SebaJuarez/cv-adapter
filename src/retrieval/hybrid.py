"""Reciprocal Rank Fusion (RRF) para combinar rankings sparse y dense.

Cada sección tiene su propio pipeline híbrido. El RRF combina los rankings
de BM25 (léxico) y embeddings (semántico) en un solo ranking unificado.
Ahora también admite un tercer canal: keyword-match (cantidad de keywords
técnicas verificadas presentes en cada bullet), con peso configurable
menor que sparse/dense.
"""

from collections import defaultdict


def reciprocal_rank_fusion(
    sparse_ranking: list[str],
    dense_ranking: list[str],
    keyword_ranking: list[str] | None = None,
    k: int = 60,
    keyword_weight: float = 0.4,
) -> list[str]:
    """Combina dos rankings (sparse BM25 + dense embeddings) via RRF.

    Opcionalmente incorpora un tercer ranking basado en presencia de
    keywords técnicas verificadas del JD, con un peso menor para no
    sobre-priorizar bullets densos en términos por sobre bullets con
    mejor impacto narrativo.

    k=60 es el valor estándar de la literatura (Cormack et al.).
    Un documento presente en ambos rankings acumula score; si solo está
    en uno, sigue teniendo score pero menor.

    Args:
        sparse_ranking: bullet_ids ordenados por BM25.
        dense_ranking: bullet_ids ordenados por similitud coseno (Max-Sim).
        keyword_ranking: bullet_ids ordenados por cantidad de keywords
            técnicas verificadas presentes (opcional).
        k: constante de suavizado RRF.
        keyword_weight: peso del canal keyword (default 0.4 < 1.0 de
            sparse/dense).

    Returns:
        bullet_ids fusionados y ordenados por score RRF descendente.
    """
    scores: dict[str, float] = defaultdict(float)

    for rank, doc_id in enumerate(sparse_ranking):
        scores[doc_id] += 1.0 / (k + rank + 1)

    for rank, doc_id in enumerate(dense_ranking):
        scores[doc_id] += 1.0 / (k + rank + 1)

    if keyword_ranking:
        for rank, doc_id in enumerate(keyword_ranking):
            scores[doc_id] += keyword_weight / (k + rank + 1)

    return sorted(scores.keys(), key=lambda d: scores[d], reverse=True)