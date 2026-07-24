"""Motor de selección de contenido basado en Information Retrieval híbrido.

Reemplaza la función `generate_selection()` de `llm_node.py` para la fase de
retrieval (selección de bullets/experiencias/skills). El LLM se relega a una
fase estratégica posterior (summary, keywords implícitas, match_reasons).

Pipeline por sección:
    1. Extraer bullets del master_cv por sección.
    2. Cargar o reconstruir índices BM25 + Dense (cacheados en disco).
    3. Procesar JD: extract_requirements_section → chunk → embed chunks.
    4. Late Interaction (Max-Sim): cada bullet contra su mejor chunk.
    5. Hybrid Retrieval (RRF de sparse + dense).
    6. Cross-Encoder re-rank (query fija = requisitos extraídos).
    7. Agrupar bullets en entradas por score máximo (no por cantidad).
    8. Devolver formato compatible con merge.py.
"""

import json
from copy import deepcopy
from typing import Any

import numpy as np
from sentence_transformers import SentenceTransformer

from .config import load_config
from .retrieval import (
    BulletDoc,
    CrossEncoderReranker,
    DenseIndex,
    IndexStore,
    SparseIndex,
    chunk_text,
    extract_requirements_section,
    reciprocal_rank_fusion,
)

# Secciones soportadas para retrieval híbrido
_RETRIEVAL_SECTIONS = ["experience", "projects", "skills", "education"]

# Mapeo de sección -> clave de config para límites
_SECTION_LIMIT_KEYS = {
    "experience": "max_experience_entries",
    "projects": "max_project_entries",
    "skills": "max_skill_categories",
    "education": "max_education_extra",
}


def _extract_bullets_from_section(
    master_cv: dict[str, Any], section_name: str
) -> list[BulletDoc]:
    """Extrae todos los bullets de una sección del CV maestro como BulletDocs.

    Para "skills", cada skill entry se trata como un "bullet" de una sola línea.
    Para "education", los highlights se tratan como bullets.
    """
    sections = master_cv.get("cv", {}).get("sections", {})
    entries = sections.get(section_name, [])
    bullets: list[BulletDoc] = []

    for entry_idx, entry in enumerate(entries):
        if not isinstance(entry, dict):
            continue

        # Determinar label de la entrada
        if section_name == "experience":
            label = entry.get("company", "") or entry.get("position", "")
        elif section_name == "projects":
            label = entry.get("name", "")
        elif section_name == "education":
            label = entry.get("institution", "") or entry.get("degree", "")
        elif section_name == "skills":
            label = entry.get("label", "")
        else:
            label = ""

        if section_name == "skills":
            # Skills: un "bullet" por entry, texto = label + details
            text = f"{entry.get('label', '')}: {entry.get('details', '')}".strip(": ")
            if text:
                bullets.append(
                    BulletDoc(
                        id=f"{section_name}_{entry_idx}_0",
                        text=text,
                        section=section_name,
                        entry_index=entry_idx,
                        bullet_index=0,
                        entry_label=label,
                    )
                )
        else:
            # Experience, projects, education: un bullet por highlight
            for bullet_idx, highlight in enumerate(entry.get("highlights", [])):
                if isinstance(highlight, str) and highlight.strip():
                    bullets.append(
                        BulletDoc(
                            id=f"{section_name}_{entry_idx}_bullet_{bullet_idx}",
                            text=highlight.strip(),
                            section=section_name,
                            entry_index=entry_idx,
                            bullet_index=bullet_idx,
                            entry_label=label,
                        )
                    )

    return bullets


def _build_indices_for_section(
    section_name: str,
    bullets: list[BulletDoc],
    dense_model: SentenceTransformer,
    store: IndexStore,
) -> tuple[SparseIndex, DenseIndex]:
    """Construye (o carga) índices sparse y dense para una sección."""
    sparse_idx = SparseIndex()
    dense_idx = DenseIndex(dense_model)

    bullet_dicts = [
        {
            "id": b.id,
            "text": b.text,
            "section": b.section,
            "entry_index": b.entry_index,
            "bullet_index": b.bullet_index,
            "entry_label": b.entry_label,
        }
        for b in bullets
    ]

    sparse_idx.build(bullet_dicts)
    dense_idx.build(bullet_dicts)

    # Persistir
    store.save_bullets(section_name, bullets)
    store.save_sparse(section_name, sparse_idx)
    store.save_dense(section_name, dense_idx.embeddings)

    return sparse_idx, dense_idx


def _load_indices_for_section(
    section_name: str,
    dense_model: SentenceTransformer,
    store: IndexStore,
) -> tuple[SparseIndex, DenseIndex] | None:
    """Carga índices persistidos para una sección. Devuelve None si no existen."""
    bullets = store.load_bullets(section_name)
    dense_emb = store.load_dense(section_name)
    sparse_obj = store.load_sparse(section_name)

    if bullets is None or dense_emb is None or sparse_obj is None:
        return None

    sparse_idx = SparseIndex()
    sparse_idx.bm25 = sparse_obj
    sparse_idx.bullet_ids = [b.id for b in bullets]

    dense_idx = DenseIndex(dense_model)
    dense_idx.bullet_ids = [b.id for b in bullets]
    dense_idx.embeddings = dense_emb

    return sparse_idx, dense_idx


def _group_bullets_into_entries(
    ranked_bullets: list[dict],
    max_entries: int,
    max_highlights_per_entry: int,
) -> list[dict]:
    """Agrupa bullets rankeados en entradas, respetando presupuestos.

    ORDENA POR SCORE MÁXIMO DE LA ENTRADA (no por cantidad de bullets).
    Esto evita que un proyecto con 3 bullets mediocres supere una
    experiencia con 2 bullets excelentes.
    """
    from collections import defaultdict

    entries = defaultdict(list)
    for bullet in ranked_bullets:
        key = (bullet["section"], bullet["entry_index"])
        if len(entries[key]) < max_highlights_per_entry:
            entries[key].append(bullet)

    if not entries:
        return []

    # Ordenar entradas por score máximo (calidad), no por cantidad
    sorted_entries = sorted(
        entries.items(),
        key=lambda x: max(b["score"] for b in x[1]),
        reverse=True,
    )[:max_entries]

    result = []
    for (section, entry_idx), bullets in sorted_entries:
        # Ordenar bullets dentro de la entrada por score descendente
        bullets_sorted = sorted(bullets, key=lambda b: b["score"], reverse=True)
        result.append(
            {
                "index": entry_idx,
                "highlight_order": [b["bullet_index"] for b in bullets_sorted],
                "match_reason": bullets_sorted[0]["text"][:120] + "...",
            }
        )
    return result


class SelectionEngine:
    """Orquesta el pipeline de retrieval híbrido para seleccionar contenido del CV.

    Uso típico:
        engine = SelectionEngine(config)
        selection = engine.select(master_cv, job_description)
        # selection es un dict compatible con merge.py
    """

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or load_config()
        self.store = IndexStore()
        self._dense_model: SentenceTransformer | None = None
        self._reranker: CrossEncoderReranker | None = None

    def _get_dense_model(self) -> SentenceTransformer:
        if self._dense_model is None:
            model_name = self.config.get(
                "dense_model", "sentence-transformers/all-MiniLM-L6-v2"
            )
            self._dense_model = SentenceTransformer(model_name, device="cpu")
        return self._dense_model

    def _get_reranker(self) -> CrossEncoderReranker | None:
        if not self.config.get("use_reranker", True):
            return None
        if self._reranker is None:
            model_name = self.config.get(
                "cross_encoder_model", "cross-encoder/ms-marco-MiniLM-L-6-v2"
            )
            self._reranker = CrossEncoderReranker(model_name, device="cpu")
        return self._reranker

    def select(
        self,
        master_cv: dict[str, Any],
        job_description: str,
    ) -> dict[str, Any]:
        """Ejecuta el pipeline completo de retrieval híbrido.

        Devuelve un dict con el mismo formato que `generate_selection()`
        del LLM (para compatibilidad con merge.py):
            {
                "selected_experience": [{"index": int, "highlight_order": [...], "match_reason": str}],
                "selected_projects": [...],
                "selected_skills_indices": [int, ...],
                "selected_education_indices": [int, ...],
                "summary_index": None,  # el LLM lo elige después
                "keywords_detected": [],  # el LLM lo elige después
            }
        """
        # --- 1. Preparar JD: extraer requisitos + chunk + embed ---
        query_text = extract_requirements_section(job_description)
        query_chunks = chunk_text(query_text, max_tokens=200, overlap=50)

        dense_model = self._get_dense_model()
        chunk_embeddings = dense_model.encode(
            query_chunks,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )  # (n_chunks, dim)

        # --- 2. Serializar master_cv para verificar cache ---
        master_json = json.dumps(master_cv, ensure_ascii=False, sort_keys=True)

        # --- 3. Por cada sección: retrieval híbrido ---
        selection: dict[str, Any] = {
            "selected_experience": [],
            "selected_projects": [],
            "selected_skills_indices": [],
            "selected_education_indices": [],
            "summary_index": None,
            "keywords_detected": [],
        }

        for section in _RETRIEVAL_SECTIONS:
            bullets = _extract_bullets_from_section(master_cv, section)
            if not bullets:
                continue

            # Cargar o construir índices
            indices = _load_indices_for_section(section, dense_model, self.store)
            if indices is None or not self.store.is_fresh(master_json):
                indices = _build_indices_for_section(
                    section, bullets, dense_model, self.store
                )

            sparse_idx, dense_idx = indices

            # Sparse retrieval
            sparse_ranking = sparse_idx.query(query_text, top_k=50)

            # Dense retrieval (Late Interaction / Max-Sim)
            dense_ranking = dense_idx.query(chunk_embeddings, top_k=50)

            # Hybrid fusion (RRF)
            hybrid_ranking = reciprocal_rank_fusion(sparse_ranking, dense_ranking)

            # Cross-encoder re-rank (query fija = requisitos extraídos)
            reranker = self._get_reranker()
            if reranker is not None:
                # Mapear ids a bullets
                bullet_map = {b.id: b for b in bullets}
                candidate_bullets = [
                    {
                        "id": bid,
                        "text": bullet_map[bid].text,
                        "section": bullet_map[bid].section,
                        "entry_index": bullet_map[bid].entry_index,
                        "bullet_index": bullet_map[bid].bullet_index,
                    }
                    for bid in hybrid_ranking[:30]
                    if bid in bullet_map
                ]
                reranked = reranker.rerank(query_text, candidate_bullets, top_k=30)
                # Reconstruir ranking con scores
                final_ranking = []
                for bid, score in reranked:
                    b = bullet_map[bid]
                    final_ranking.append(
                        {
                            "id": bid,
                            "text": b.text,
                            "section": b.section,
                            "entry_index": b.entry_index,
                            "bullet_index": b.bullet_index,
                            "score": score,
                        }
                    )
            else:
                # Sin re-ranker: usar ranking híbrido con scores simulados
                bullet_map = {b.id: b for b in bullets}
                final_ranking = []
                for rank, bid in enumerate(hybrid_ranking):
                    if bid not in bullet_map:
                        continue
                    b = bullet_map[bid]
                    final_ranking.append(
                        {
                            "id": bid,
                            "text": b.text,
                            "section": b.section,
                            "entry_index": b.entry_index,
                            "bullet_index": b.bullet_index,
                            "score": 1.0 / (rank + 1),  # score decreciente
                        }
                    )

            # Agrupar bullets en entradas
            max_entries = self.config.get(_SECTION_LIMIT_KEYS[section], 3)
            max_highlights = self.config.get("max_highlights_per_entry", 4)

            if section == "skills":
                # Skills: no hay highlights, es una lista de índices
                seen = set()
                skill_indices = []
                for b in final_ranking:
                    idx = b["entry_index"]
                    if idx not in seen:
                        seen.add(idx)
                        skill_indices.append(idx)
                selection["selected_skills_indices"] = skill_indices[:max_entries]

            elif section == "education":
                # Education: índices de entradas extra (el índice 0 siempre se incluye)
                seen = set()
                edu_indices = []
                for b in final_ranking:
                    idx = b["entry_index"]
                    if idx != 0 and idx not in seen:
                        seen.add(idx)
                        edu_indices.append(idx)
                selection["selected_education_indices"] = edu_indices[:max_entries]

            else:
                # Experience / Projects: entradas con highlight_order
                grouped = _group_bullets_into_entries(
                    final_ranking, max_entries, max_highlights
                )
                key = f"selected_{section}"
                selection[key] = grouped

        # Guardar hash si era la primera vez
        if not self.store.is_fresh(master_json):
            self.store.save_hash(master_json)

        return selection

    def select_section(
        self,
        master_cv: dict[str, Any],
        job_description: str,
        section_name: str,
    ) -> dict[str, Any]:
        """Versión acotada: regenera UNA sola sección (usado por /api/regenerate-section).

        Devuelve un dict con la misma estructura que select() pero solo
        con la clave correspondiente a la sección pedida.
        """
        if section_name not in _RETRIEVAL_SECTIONS:
            raise ValueError(f"Sección no soportada: {section_name}")

        query_text = extract_requirements_section(job_description)
        query_chunks = chunk_text(query_text, max_tokens=200, overlap=50)

        dense_model = self._get_dense_model()
        chunk_embeddings = dense_model.encode(
            query_chunks,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )

        master_json = json.dumps(master_cv, ensure_ascii=False, sort_keys=True)
        bullets = _extract_bullets_from_section(master_cv, section_name)

        if not bullets:
            return (
                {f"selected_{section_name}": []}
                if section_name != "skills"
                else {"selected_skills_indices": []}
            )

        indices = _load_indices_for_section(section_name, dense_model, self.store)
        if indices is None or not self.store.is_fresh(master_json):
            indices = _build_indices_for_section(
                section_name, bullets, dense_model, self.store
            )

        sparse_idx, dense_idx = indices
        sparse_ranking = sparse_idx.query(query_text, top_k=50)
        dense_ranking = dense_idx.query(chunk_embeddings, top_k=50)
        hybrid_ranking = reciprocal_rank_fusion(sparse_ranking, dense_ranking)

        reranker = self._get_reranker()
        bullet_map = {b.id: b for b in bullets}

        if reranker is not None:
            candidate_bullets = [
                {
                    "id": bid,
                    "text": bullet_map[bid].text,
                    "section": bullet_map[bid].section,
                    "entry_index": bullet_map[bid].entry_index,
                    "bullet_index": bullet_map[bid].bullet_index,
                }
                for bid in hybrid_ranking[:30]
                if bid in bullet_map
            ]
            reranked = reranker.rerank(query_text, candidate_bullets, top_k=30)
            final_ranking = []
            for bid, score in reranked:
                b = bullet_map[bid]
                final_ranking.append(
                    {
                        "id": bid,
                        "text": b.text,
                        "section": b.section,
                        "entry_index": b.entry_index,
                        "bullet_index": b.bullet_index,
                        "score": score,
                    }
                )
        else:
            final_ranking = []
            for rank, bid in enumerate(hybrid_ranking):
                if bid not in bullet_map:
                    continue
                b = bullet_map[bid]
                final_ranking.append(
                    {
                        "id": bid,
                        "text": b.text,
                        "section": b.section,
                        "entry_index": b.entry_index,
                        "bullet_index": b.bullet_index,
                        "score": 1.0 / (rank + 1),
                    }
                )

        max_entries = self.config.get(_SECTION_LIMIT_KEYS[section_name], 3)
        max_highlights = self.config.get("max_highlights_per_entry", 4)

        if section_name == "skills":
            seen = set()
            skill_indices = []
            for b in final_ranking:
                idx = b["entry_index"]
                if idx not in seen:
                    seen.add(idx)
                    skill_indices.append(idx)
            return {"selected_skills_indices": skill_indices[:max_entries]}

        elif section_name == "education":
            seen = set()
            edu_indices = []
            for b in final_ranking:
                idx = b["entry_index"]
                if idx != 0 and idx not in seen:
                    seen.add(idx)
                    edu_indices.append(idx)
            return {"selected_education_indices": edu_indices[:max_entries]}

        else:
            grouped = _group_bullets_into_entries(
                final_ranking, max_entries, max_highlights
            )
            return {f"selected_{section_name}": grouped}
