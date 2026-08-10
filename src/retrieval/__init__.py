"""Pipeline de Information Retrieval híbrido para cv-adapter.

Módulos:
- jd_processor: extracción de requisitos y chunking del JD.
- store: persistencia de índices por sección.
- sparse: BM25 con sinónimos.
- dense: embeddings con Late Interaction (Max-Sim), NumPy puro.
- hybrid: Reciprocal Rank Fusion.
- rerank: Cross-encoder re-ranker.
- keywords: extracción y verificación ATS de keywords técnicas.
"""
from .jd_processor import (
    chunk_text,
    extract_negated_terms,
    extract_requirements_section,
)
from .store import BulletDoc, IndexStore
from .sparse import SparseIndex
from .dense import DenseIndex
from .hybrid import reciprocal_rank_fusion
from .rerank import CrossEncoderReranker
from .keywords import build_keyword_ranking, build_keyword_report, extract_keywords

__all__ = [
    "extract_requirements_section",
    "extract_negated_terms",
    "chunk_text",
    "BulletDoc",
    "IndexStore",
    "SparseIndex",
    "DenseIndex",
    "reciprocal_rank_fusion",
    "CrossEncoderReranker",
    "build_keyword_report",
    "extract_keywords",
    "build_keyword_ranking",
]