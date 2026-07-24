"""Pipeline de Information Retrieval híbrido para cv-adapter.

Módulos:
- jd_processor: extracción de requisitos y chunking del JD.
- store: persistencia de índices por sección.
- sparse: BM25 con sinónimos.
- dense: embeddings con Late Interaction (Max-Sim), NumPy puro.
- hybrid: Reciprocal Rank Fusion.
- rerank: Cross-encoder re-ranker.
"""
from .jd_processor import extract_requirements_section, chunk_text
from .store import BulletDoc, IndexStore
from .sparse import SparseIndex
from .dense import DenseIndex
from .hybrid import reciprocal_rank_fusion
from .rerank import CrossEncoderReranker

__all__ = [
    "extract_requirements_section",
    "chunk_text",
    "BulletDoc",
    "IndexStore",
    "SparseIndex",
    "DenseIndex",
    "reciprocal_rank_fusion",
    "CrossEncoderReranker",
]