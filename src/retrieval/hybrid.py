"""Reciprocal Rank Fusion (RRF) para combinar rankings sparse y dense.

Cada sección tiene su propio pipeline híbrido. El RRF combina los rankings
de BM25 (léxico) y embeddings (semántico) en un solo ranking unificado.
"""

from collections import defaultdict


def reciprocal_rank_fusion(
    sparse_ranking: list[str],
    dense_ranking: list[str],
    k: int = 60,
) -> list[str]:
    """Combina dos rankings (sparse BM25 + dense embeddings) via RRF.

    k=60 es el valor estándar de la literatura (Cormack et al.).
    Un documento presente en ambos rankings acumula score; si solo está
    en uno, sigue teniendo score pero menor.

    Args:
        sparse_ranking: bullet_ids ordenados por BM25.
        dense_ranking: bullet_ids ordenados por similitud coseno (Max-Sim).
        k: constante de suavizado RRF.

    Returns:
        bullet_ids fusionados y ordenados por score RRF descendente.
    """
    scores: dict[str, float] = defaultdict(float)

    for rank, doc_id in enumerate(sparse_ranking):
        scores[doc_id] += 1.0 / (k + rank + 1)

    for rank, doc_id in enumerate(dense_ranking):
        scores[doc_id] += 1.0 / (k + rank + 1)

    return sorted(scores.keys(), key=lambda d: scores[d], reverse=True)
