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
    sparse_weight: float = 1.0,
    dense_weight: float = 1.0,
) -> list[str]:
    """Combina rankings (sparse BM25 + dense embeddings + keyword-boost opcional) via RRF.

    k=60 es el valor estándar de la literatura (Cormack et al.) para corpus
    grandes; con corpus chicos (decenas de documentos por sección, como los
    bullets de un CV) k=10-20 rinde mejor porque respeta más las diferencias
    de rank. Un documento presente en más de un ranking acumula score; si
    solo está en uno, sigue teniendo score pero menor.

    El canal de keyword-boost (`keyword_ranking`) es OPCIONAL y a propósito
    tiene menos peso por default (0.5) que sparse/dense (1.0 cada uno): la
    idea es que una keyword exacta del JD empuje hacia arriba a un bullet
    que ya viene compitiendo por relevancia semántica/léxica, sin que un
    bullet "denso en keywords" pero pobre en impacto narrativo le gane
    a uno mejor solo por listar más tecnologías.

    Los pesos `sparse_weight`/`dense_weight` escalan la contribución de cada
    canal al score RRF (multiplican el término 1/(k+rank)), como ya hacía
    `keyword_weight`. Sirven para rebalancear canales según el dominio
    (ej. ofertas con identificadores exactos -> más peso a sparse) sin
    cambiar la semántica rank-based del RRF.

    Args:
        sparse_ranking: bullet_ids ordenados por BM25.
        dense_ranking: bullet_ids ordenados por similitud coseno (Max-Sim).
        k: constante de suavizado RRF.
        keyword_ranking: bullet_ids ordenados por peso de keywords del JD
            que contienen literalmente (ver keywords.build_keyword_ranking).
        keyword_weight: peso relativo del canal de keywords (< 1.0 por
            default, ver arriba). Configurable vía config.json
            (`keyword_boost_weight`).
        sparse_weight: peso del canal BM25 (config `sparse_weight`).
        dense_weight: peso del canal denso (config `dense_weight`).

    Returns:
        bullet_ids fusionados y ordenados por score RRF descendente.
    """
    scores: dict[str, float] = defaultdict(float)

    for rank, doc_id in enumerate(sparse_ranking):
        scores[doc_id] += sparse_weight * (1.0 / (k + rank + 1))

    for rank, doc_id in enumerate(dense_ranking):
        scores[doc_id] += dense_weight * (1.0 / (k + rank + 1))

    if keyword_ranking:
        for rank, doc_id in enumerate(keyword_ranking):
            scores[doc_id] += keyword_weight * (1.0 / (k + rank + 1))

    # Los docs con score <= 0 solo aparecían en canales con peso 0: un canal
    # con peso 0 se interpreta como "ignorado", no como "rankear con score 0".
    return sorted(
        (d for d, s in scores.items() if s > 0),
        key=lambda d: scores[d],
        reverse=True,
    )