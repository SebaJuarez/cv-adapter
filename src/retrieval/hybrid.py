"""Reciprocal Rank Fusion (RRF) para combinar rankings sparse y dense.

Cada sección tiene su propio pipeline híbrido. El RRF combina los rankings
de BM25 (léxico) y embeddings (semántico) en un solo ranking unificado.
"""

from collections import defaultdict


def reciprocal_rank_fusion(
    sparse_ranking: list[str],
    dense_ranking: list[str],
    k: int = 60,
    keyword_ranking: list[str] | None = None,
    keyword_weight: float = 0.5,
) -> list[str]:
    """Combina rankings (sparse BM25 + dense embeddings + keyword-boost opcional) via RRF.

    k=60 es el valor estándar de la literatura (Cormack et al.).
    Un documento presente en más de un ranking acumula score; si solo está
    en uno, sigue teniendo score pero menor.

    El canal de keyword-boost (`keyword_ranking`) es OPCIONAL y a propósito
    tiene menos peso por default (0.5) que sparse/dense (1.0 cada uno): la
    idea es que una keyword exacta del JD empuje hacia arriba a un bullet
    que ya viene compitiendo por relevancia semántica/léxica, sin que un
    bullet "denso en keywords" pero pobre en impacto narrativo le gane
    a uno mejor solo por listar más tecnologías.

    Args:
        sparse_ranking: bullet_ids ordenados por BM25.
        dense_ranking: bullet_ids ordenados por similitud coseno (Max-Sim).
        k: constante de suavizado RRF.
        keyword_ranking: bullet_ids ordenados por peso de keywords del JD
            que contienen literalmente (ver keywords.build_keyword_ranking).
        keyword_weight: peso relativo del canal de keywords (< 1.0 por
            default, ver arriba). Configurable vía config.json
            (`keyword_boost_weight`).

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
            scores[doc_id] += keyword_weight * (1.0 / (k + rank + 1))

    return sorted(scores.keys(), key=lambda d: scores[d], reverse=True)