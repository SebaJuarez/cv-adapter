"""Motor de selección de contenido basado en Information Retrieval híbrido.

Reemplaza la función `generate_selection()` de `llm_node.py` para la fase de
retrieval (selección de bullets/experiencias/skills). El LLM se relega a una
fase estratégica posterior (summary, keywords implícitas, match_reasons).

Nuevas features:
- Exposición de scores por bullet para el frontend (relevancia visual).
- JD snippets: el fragmento del JD que mejor matcheó con cada bullet.
- Section scores: score promedio por entrada para heatmap de secciones.
"""

import hashlib
import json
from copy import deepcopy
from datetime import datetime
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

_RETRIEVAL_SECTIONS = ["experience", "projects", "skills", "education"]
_SECTION_LIMIT_KEYS = {
    "experience": "max_experience_entries",
    "projects": "max_project_entries",
    "skills": "max_skill_categories",
    "education": "max_education_extra",
}


def _extract_bullets_from_section(
    master_cv: dict[str, Any], section_name: str
) -> list[BulletDoc]:
    sections = master_cv.get("cv", {}).get("sections", {})
    entries = sections.get(section_name, [])
    bullets: list[BulletDoc] = []

    for entry_idx, entry in enumerate(entries):
        if not isinstance(entry, dict):
            continue

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

    store.save_bullets(section_name, bullets)
    store.save_sparse(section_name, sparse_idx.bm25)
    store.save_dense(section_name, dense_idx.embeddings)

    return sparse_idx, dense_idx


def _load_indices_for_section(
    section_name: str,
    dense_model: SentenceTransformer,
    store: IndexStore,
) -> tuple[SparseIndex, DenseIndex] | None:
    bullets = store.load_bullets(section_name)
    dense_emb = store.load_dense(section_name)
    sparse_obj = store.load_sparse(section_name)

    if bullets is None or dense_emb is None or sparse_obj is None:
        return None

    if not hasattr(sparse_obj, "get_scores"):
        return None

    sparse_idx = SparseIndex()
    sparse_idx.bm25 = sparse_obj
    sparse_idx.bullet_ids = [b.id for b in bullets]

    dense_idx = DenseIndex(dense_model)
    dense_idx.bullet_ids = [b.id for b in bullets]
    dense_idx.embeddings = dense_emb

    return sparse_idx, dense_idx


def _generate_match_reason(bullet_text: str, jd_chunk: str) -> str:
    import re

    stopwords = {
        "the", "and", "for", "with", "you", "will", "are", "our", "that", "have",
        "this", "your", "from", "they", "been", "their", "what", "when", "where",
        "than", "then", "them", "these", "those", "being", "having", "doing",
        "about", "into", "through", "during", "before", "after", "above", "below",
        "between", "under", "over", "again", "further", "once", "here", "there",
        "why", "how", "all", "any", "both", "each", "few", "more", "most", "other",
        "some", "such", "only", "own", "same", "so", "than", "too", "very", "can",
        "just", "should", "now", "use", "using", "used", "work", "working", "worked",
        "experience", "experienced", "years", "year", "least", "plus", "good", "strong",
        "excellent", "solid", "deep", "proven", "track", "record", "ability", "able",
        "looking", "seeking", "join", "team", "company", "role", "position", "job",
    }

    def extract_words(text: str) -> set[str]:
        words = re.findall(r"\b[a-z]{3,}\b", text.lower())
        return {w for w in words if w not in stopwords}

    bullet_words = extract_words(bullet_text)
    jd_words = extract_words(jd_chunk)
    common = sorted(bullet_words & jd_words)

    if not common:
        return "Relevante para la oferta"
    if len(common) == 1:
        return f"Matchea con requisitos de la oferta: menciona {common[0]}"
    if len(common) == 2:
        return f"Matchea con requisitos de la oferta: menciona {common[0]} y {common[1]}"
    return f"Matchea con requisitos de la oferta: menciona {', '.join(common[:-1])} y {common[-1]}"




def _parse_date(date_str: str) -> datetime:
    """Parsea fechas tipo '2021-03', '2021' o 'present'."""
    if not date_str or str(date_str).lower() == "present":
        return datetime(9999, 12, 31)
    try:
        return datetime.strptime(str(date_str), "%Y-%m")
    except ValueError:
        try:
            return datetime.strptime(str(date_str), "%Y")
        except ValueError:
            return datetime(1, 1, 1)


def _reorder_entries_chronologically(
    master_cv: dict[str, Any],
    section_name: str,
    selected_entries: list[dict],
) -> list[dict]:
    """Reordena las entradas seleccionadas por start_date descendente
    (más reciente primero), respetando la convención universal de CVs.
    """
    sections = master_cv.get("cv", {}).get("sections", {})
    master_list = sections.get(section_name, [])

    def _entry_date(entry_sel: dict) -> datetime:
        idx = entry_sel.get("index")
        if idx is None or idx < 0 or idx >= len(master_list):
            return datetime(1, 1, 1)
        original = master_list[idx]
        if not isinstance(original, dict):
            return datetime(1, 1, 1)
        return _parse_date(original.get("start_date", ""))

    return sorted(selected_entries, key=_entry_date, reverse=True)


def _group_bullets_into_entries(
    ranked_bullets: list[dict],
    max_entries: int,
    max_highlights_per_entry: int,
) -> list[dict]:
    from collections import defaultdict

    entries = defaultdict(list)
    for bullet in ranked_bullets:
        key = (bullet["section"], bullet["entry_index"])
        if len(entries[key]) < max_highlights_per_entry:
            entries[key].append(bullet)

    if not entries:
        return []

    sorted_entries = sorted(
        entries.items(),
        key=lambda x: max(b["score"] for b in x[1]),
        reverse=True,
    )[:max_entries]

    result = []
    for (section, entry_idx), bullets in sorted_entries:
        bullets_sorted = sorted(bullets, key=lambda b: b["score"], reverse=True)
        avg_score = round(sum(b["score"] for b in bullets_sorted) / len(bullets_sorted), 3)
        result.append(
            {
                "index": entry_idx,
                "highlight_order": [b["bullet_index"] for b in bullets_sorted],
                "match_reason": bullets_sorted[0].get("match_reason", bullets_sorted[0]["text"][:120] + "..."),
                "entry_score": avg_score,  # NUEVO: score promedio de la entrada
            }
        )
    return result


class SelectionEngine:
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

        reranker = self._get_reranker()
        score_mode = "cross_encoder" if reranker is not None else "positional_fallback"

        selection: dict[str, Any] = {
            "selected_experience": [],
            "selected_projects": [],
            "selected_skills_indices": [],
            "selected_education_indices": [],
            "summary_index": None,
            "keywords_detected": [],
            "bullet_scores": {},       # NUEVO: bullet_id -> score (0-1)
            "jd_snippets": {},         # NUEVO: bullet_id -> snippet del JD
            "section_scores": {},      # NUEVO: section -> {entry_idx: score}
            "score_mode": score_mode,  # NUEVO: "cross_encoder" | "positional_fallback"
        }

        for section in _RETRIEVAL_SECTIONS:
            bullets = _extract_bullets_from_section(master_cv, section)
            if not bullets:
                continue

            indices = _load_indices_for_section(section, dense_model, self.store)
            if indices is None or not self.store.is_fresh(master_json):
                indices = _build_indices_for_section(
                    section, bullets, dense_model, self.store
                )

            sparse_idx, dense_idx = indices
            sparse_ranking = sparse_idx.query(query_text, top_k=50)
            dense_ranking, chunk_map = dense_idx.query(chunk_embeddings, top_k=50)
            hybrid_ranking = reciprocal_rank_fusion(sparse_ranking, dense_ranking)

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
                    best_chunk_idx = chunk_map.get(bid, 0)
                    jd_chunk = query_chunks[best_chunk_idx] if best_chunk_idx < len(query_chunks) else query_text
                    match_reason = _generate_match_reason(b.text, jd_chunk)
                    final_ranking.append(
                        {
                            "id": bid,
                            "text": b.text,
                            "section": b.section,
                            "entry_index": b.entry_index,
                            "bullet_index": b.bullet_index,
                            "score": round(score, 3),
                            "match_reason": match_reason,
                            "best_chunk_idx": best_chunk_idx,
                            "jd_snippet": jd_chunk[:200],  # NUEVO
                        }
                    )
            else:
                final_ranking = []
                for rank, bid in enumerate(hybrid_ranking):
                    if bid not in bullet_map:
                        continue
                    b = bullet_map[bid]
                    best_chunk_idx = chunk_map.get(bid, 0)
                    jd_chunk = query_chunks[best_chunk_idx] if best_chunk_idx < len(query_chunks) else query_text
                    match_reason = _generate_match_reason(b.text, jd_chunk)
                    final_ranking.append(
                        {
                            "id": bid,
                            "text": b.text,
                            "section": b.section,
                            "entry_index": b.entry_index,
                            "bullet_index": b.bullet_index,
                            "score": round(1.0 / (rank + 1), 3),
                            "match_reason": match_reason,
                            "best_chunk_idx": best_chunk_idx,
                            "jd_snippet": jd_chunk[:200],
                        }
                    )

            # Guardar scores y snippets globales
            section_scores = {}
            for b in final_ranking:
                selection["bullet_scores"][b["id"]] = b["score"]
                selection["jd_snippets"][b["id"]] = b["jd_snippet"]
                eidx = b["entry_index"]
                if eidx not in section_scores or b["score"] > section_scores[eidx]:
                    section_scores[eidx] = b["score"]
            if section_scores:
                selection["section_scores"][section] = section_scores

            max_entries = self.config.get(_SECTION_LIMIT_KEYS[section], 3)
            max_highlights = self.config.get("max_highlights_per_entry", 4)

            if section == "skills":
                seen = set()
                skill_indices = []
                for b in final_ranking:
                    idx = b["entry_index"]
                    if idx not in seen:
                        seen.add(idx)
                        skill_indices.append(idx)
                selection["selected_skills_indices"] = skill_indices[:max_entries]

            elif section == "education":
                seen = set()
                edu_indices = []
                for b in final_ranking:
                    idx = b["entry_index"]
                    if idx != 0 and idx not in seen:
                        seen.add(idx)
                        edu_indices.append(idx)
                selection["selected_education_indices"] = edu_indices[:max_entries]

            else:
                grouped = _group_bullets_into_entries(
                    final_ranking, max_entries, max_highlights
                )
                key = f"selected_{section}"
                selection[key] = grouped
                # Reordenar cronológicamente (más reciente primero) después de seleccionar por score
                if section in ("experience", "projects") and selection[key]:
                    selection[key] = _reorder_entries_chronologically(
                        master_cv, section, selection[key]
                    )

        if not self.store.is_fresh(master_json):
            self.store.save_hash(master_json)

        return selection

    def select_section(
        self,
        master_cv: dict[str, Any],
        job_description: str,
        section_name: str,
    ) -> dict[str, Any]:
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
        dense_ranking, chunk_map = dense_idx.query(chunk_embeddings, top_k=50)
        hybrid_ranking = reciprocal_rank_fusion(sparse_ranking, dense_ranking)

        reranker = self._get_reranker()
        score_mode = "cross_encoder" if reranker is not None else "positional_fallback"
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
                best_chunk_idx = chunk_map.get(bid, 0)
                jd_chunk = query_chunks[best_chunk_idx] if best_chunk_idx < len(query_chunks) else query_text
                match_reason = _generate_match_reason(b.text, jd_chunk)
                final_ranking.append(
                    {
                        "id": bid,
                        "text": b.text,
                        "section": b.section,
                        "entry_index": b.entry_index,
                        "bullet_index": b.bullet_index,
                        "score": round(score, 3),
                        "match_reason": match_reason,
                        "best_chunk_idx": best_chunk_idx,
                        "jd_snippet": jd_chunk[:200],
                    }
                )
        else:
            final_ranking = []
            for rank, bid in enumerate(hybrid_ranking):
                if bid not in bullet_map:
                    continue
                b = bullet_map[bid]
                best_chunk_idx = chunk_map.get(bid, 0)
                jd_chunk = query_chunks[best_chunk_idx] if best_chunk_idx < len(query_chunks) else query_text
                match_reason = _generate_match_reason(b.text, jd_chunk)
                final_ranking.append(
                    {
                        "id": bid,
                        "text": b.text,
                        "section": b.section,
                        "entry_index": b.entry_index,
                        "bullet_index": b.bullet_index,
                        "score": round(1.0 / (rank + 1), 3),
                        "match_reason": match_reason,
                        "best_chunk_idx": best_chunk_idx,
                        "jd_snippet": jd_chunk[:200],
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
            return {"selected_skills_indices": skill_indices[:max_entries], "score_mode": score_mode}

        elif section_name == "education":
            seen = set()
            edu_indices = []
            for b in final_ranking:
                idx = b["entry_index"]
                if idx != 0 and idx not in seen:
                    seen.add(idx)
                    edu_indices.append(idx)
            return {"selected_education_indices": edu_indices[:max_entries], "score_mode": score_mode}

        else:
            grouped = _group_bullets_into_entries(
                final_ranking, max_entries, max_highlights
            )
            if section_name in ("experience", "projects") and grouped:
                grouped = _reorder_entries_chronologically(
                    master_cv, section_name, grouped
                )
            return {f"selected_{section_name}": grouped, "score_mode": score_mode}


# ---------------------------------------------------------------------
# Singleton global para evitar recarga de modelos en cada request
# ---------------------------------------------------------------------
_engine_singleton: SelectionEngine | None = None
_engine_singleton_hash: str | None = None


def get_selection_engine(config: dict[str, Any] | None = None) -> SelectionEngine:
    """Devuelve una instancia de SelectionEngine, reutilizando la misma
    en memoria si la configuración relevante no cambió.

    Esto evita recargar los modelos de embeddings y cross-encoder en cada
    request de FastAPI (o cada corrida del CLI), reduciendo la latencia
    percibida de varios segundos a fracciones de segundo después del
    primer uso.
    """
    global _engine_singleton, _engine_singleton_hash
    config = config or load_config()
    # Solo hasheamos las claves que afectan a los modelos o a la selección
    hashable = json.dumps(
        {k: config.get(k) for k in (
            "dense_model", "cross_encoder_model", "use_reranker",
            "max_experience_entries", "max_project_entries",
            "max_highlights_per_entry", "max_skill_categories",
            "max_education_extra", "max_keywords",
        )},
        sort_keys=True,
    )
    config_hash = hashlib.sha256(hashable.encode("utf-8")).hexdigest()
    if _engine_singleton is None or _engine_singleton_hash != config_hash:
        _engine_singleton = SelectionEngine(config)
        _engine_singleton_hash = config_hash
    return _engine_singleton