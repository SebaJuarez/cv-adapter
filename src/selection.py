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
    build_keyword_ranking,
    chunk_text,
    extract_keywords,
    extract_requirements_section,
    reciprocal_rank_fusion,
)
from .retrieval.keywords import _count_keyword_occurrences
from .retrieval.sparse import get_synonym_variants

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

    from .retrieval.stopwords import STOPWORDS

    # Palabras "de relleno" propias de un JD (no son stopwords léxicas
    # generales, pero tampoco aportan nada como explicación de match:
    # "menciona experiencia y años" no le dice nada útil al usuario).
    filler = {
        "use", "using", "used", "work", "working", "worked",
        "experience", "experienced", "years", "year", "least", "plus", "good", "strong",
        "excellent", "solid", "deep", "proven", "track", "record", "ability", "able",
        "looking", "seeking", "join", "team", "company", "role", "position", "job",
    }
    stopwords = STOPWORDS | filler

    def extract_words(text: str) -> set[str]:
        # \w+ (con re.UNICODE implícito en Python 3) para no perder tildes
        # ("según", "más") al filtrar texto en español.
        words = re.findall(r"\b[a-záéíóúñü]{3,}\b", text.lower())
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


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _mmr_select(
    bullets_sorted: list[dict],
    max_highlights: int,
    diversity_lambda: float = 0.7,
) -> list[dict]:
    """Selecciona highlights balanceando relevancia y diversidad (MMR).

    Antes, dentro de una entrada, se tomaban directamente los N bullets de
    mayor score — sin nada que impida que esos N digan, en el fondo, lo
    mismo con otras palabras ("REST APIs en Java" repetido 3 veces),
    desperdiciando el presupuesto de página en vez de cubrir más
    competencias distintas.

    Usa similitud de Jaccard sobre tokens (BM25-style, con sinónimos y
    stopwords ya filtradas) como proxy de redundancia — deliberadamente
    léxico y no basado en embeddings, así corre siempre (aunque
    `use_reranker=False`) sin costo de inferencia extra. Se puede migrar
    a similitud por embeddings más adelante reusando el DenseIndex ya
    calculado; queda anotado como mejora futura, no bloquea esta fase.

    diversity_lambda=1.0 desactiva la diversidad por completo (equivale al
    comportamiento anterior: puro top-N por score). Es el default
    conservador si en algún momento se quiere apagar sin tocar código.
    """
    if len(bullets_sorted) <= max_highlights or diversity_lambda >= 1.0:
        return bullets_sorted[:max_highlights]

    from .retrieval.sparse import tokenize_with_synonyms

    token_sets = [set(tokenize_with_synonyms(b["text"])) for b in bullets_sorted]
    scores = [b["score"] for b in bullets_sorted]
    max_score = max(scores) or 1.0

    selected = [0]  # el de mejor score siempre entra primero, nunca se sacrifica
    remaining = list(range(1, len(bullets_sorted)))

    while len(selected) < max_highlights and remaining:
        best_i, best_mmr = remaining[0], float("-inf")
        for i in remaining:
            relevance = scores[i] / max_score  # normalizado a [0,1] para que pese parecido a la similitud
            redundancy = max(_jaccard(token_sets[i], token_sets[j]) for j in selected)
            mmr = diversity_lambda * relevance - (1 - diversity_lambda) * redundancy
            if mmr > best_mmr:
                best_mmr, best_i = mmr, i
        selected.append(best_i)
        remaining.remove(best_i)

    selected.sort()  # preservar el orden original (por score) para la presentación
    return [bullets_sorted[i] for i in selected]


def _select_highlights_with_coverage(
    bullets_sorted: list[dict],
    max_highlights: int,
    critical_keyword_variants: dict[str, set[str]] | None,
    diversity_lambda: float = 0.7,
) -> list[int]:
    """Elige qué bullets de una entrada entran al presupuesto de highlights.

    Dos pasadas, en orden:
    1. Diversidad (MMR): elige N bullets que balancean relevancia y
       variedad de contenido, en vez de los N de mayor score a secas
       (ver `_mmr_select`).
    2. Cobertura de keywords: si alguna keyword crítica del JD (frecuencia
       alta, ver `select()`) no quedó cubierta por esos N, pero SÍ está
       cubierta por un bullet descartado de la MISMA entrada, hace UN
       intercambio — nunca agrega, nunca inventa, solo prioriza qué texto
       YA seleccionable entra en el presupuesto. Como máximo un swap por
       entrada, para no desarmar el orden más de lo necesario.

    Nota: la cobertura es un ajuste local a la entrada (no busca cobertura
    global entre TODAS las entradas seleccionadas) — puede terminar
    reforzando una keyword que ya está cubierta en otra entrada. Es una
    limitación conocida y aceptable para esta primera versión.
    """
    top = _mmr_select(bullets_sorted, max_highlights, diversity_lambda)
    # Identidad por la clave "id" del bullet (no por id() de Python: frágil
    # y difícil de razonar si alguna vez se copian los dicts).
    top_ids = {b["id"] for b in top}
    rest = [b for b in bullets_sorted if b["id"] not in top_ids]

    if not rest or not critical_keyword_variants:
        return [b["bullet_index"] for b in top]

    def _covers(bullet: dict, variants: set[str]) -> bool:
        # Texto crudo: _count_keyword_occurrences normaliza por dentro, pero
        # los términos con separadores (c++, next.js) necesitan el original.
        text = bullet["text"]
        return any(_count_keyword_occurrences(text, v) > 0 for v in variants)

    covered = {
        kw
        for kw, variants in critical_keyword_variants.items()
        if any(_covers(b, variants) for b in top)
    }
    uncovered_variants = [
        variants
        for kw, variants in critical_keyword_variants.items()
        if kw not in covered
    ]
    if not uncovered_variants:
        return [b["bullet_index"] for b in top]

    for candidate in rest:
        if any(_covers(candidate, variants) for variants in uncovered_variants):
            top = top[:-1] + [candidate]  # swap: afuera el de menor score del top
            break

    return [b["bullet_index"] for b in top]


def _group_bullets_into_entries(
    ranked_bullets: list[dict],
    max_entries: int,
    max_highlights_per_entry: int,
    critical_keyword_variants: dict[str, set[str]] | None = None,
    diversity_lambda: float = 0.7,
) -> tuple[list[dict], list[dict]]:
    """Agrupa bullets en entradas y separa incluidos vs excluidos por presupuesto.

    Returns:
        (included_entries, excluded_entries)
    """
    from collections import defaultdict

    entries = defaultdict(list)
    for bullet in ranked_bullets:
        key = (bullet["section"], bullet["entry_index"])
        entries[key].append(bullet)

    if not entries:
        return [], []

    # Ordenar todas las entradas por score máximo descendente
    sorted_entries = sorted(
        entries.items(),
        key=lambda x: max(b["score"] for b in x[1]),
        reverse=True,
    )

    included = []
    excluded = []

    for idx, ((section, entry_idx), bullets) in enumerate(sorted_entries):
        bullets_sorted = sorted(bullets, key=lambda b: b["score"], reverse=True)
        avg_score = round(sum(b["score"] for b in bullets_sorted) / len(bullets_sorted), 3)
        entry_data = {
            "index": entry_idx,
            "highlight_order": [b["bullet_index"] for b in bullets_sorted],
            "match_reason": bullets_sorted[0].get("match_reason", bullets_sorted[0]["text"][:120] + "..."),
            "entry_score": avg_score,
        }
        if idx < max_entries:
            # Recortar highlights al presupuesto, con ajuste de cobertura
            # de keywords críticas (ver _select_highlights_with_coverage).
            entry_data["highlight_order"] = _select_highlights_with_coverage(
                bullets_sorted, max_highlights_per_entry, critical_keyword_variants, diversity_lambda
            )
            included.append(entry_data)
        else:
            excluded.append(entry_data)

    return included, excluded


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

    def _resolve_summary_index(
        self, master_cv: dict[str, Any], query_text: str
    ) -> tuple[int | None, str]:
        """Elige qué variante de summary usar, de forma determinística.

        Antes esto era responsabilidad exclusiva del LLM estratégico
        (Ollama). Es, en el fondo, el mismo problema de similitud
        JD↔texto que ya resuelve IR para todo lo demás — no hay motivo
        para depender de un servicio externo (con su propia latencia y
        riesgo de falla) para una decisión que el cross-encoder/BM25 ya
        cargados en memoria resuelven igual de bien y sin red.

        Returns:
            (índice elegido o None si no hay variantes, modo usado).
        """
        summaries = master_cv.get("cv", {}).get("sections", {}).get("summary", [])
        if not summaries:
            return None, "none"
        if len(summaries) == 1:
            return 0, "single_option"

        reranker = self._get_reranker()
        candidates = [{"id": str(i), "text": s} for i, s in enumerate(summaries)]

        if reranker is not None:
            ranked = reranker.rerank(query_text, candidates, top_k=1)
            if ranked:
                return int(ranked[0][0]), "cross_encoder"

        # Fallback léxico: overlap de tokens (BM25-style, sin IDF) contra el JD.
        from .retrieval.sparse import tokenize_with_synonyms

        jd_tokens = set(tokenize_with_synonyms(query_text))
        best_idx, best_score = 0, -1
        for i, s in enumerate(summaries):
            overlap = len(jd_tokens & set(tokenize_with_synonyms(s)))
            if overlap > best_score:
                best_idx, best_score = i, overlap
        return best_idx, "positional_fallback"

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

        # Keywords "críticas" (mismo umbral de frecuencia que critical_missing
        # en retrieval/keywords.py) para el paso de optimización de cobertura
        # dentro de _group_bullets_into_entries: si una de estas quedó afuera
        # del top-N de una entrada por poco margen de score, se prioriza su
        # inclusión sobre el bullet de menor score, sin agregar contenido nuevo.
        _jd_kws, _jd_freqs = extract_keywords(job_description)
        critical_keyword_variants = {
            kw: get_synonym_variants(kw)
            for kw in _jd_kws
            if _jd_freqs.get(kw, 0) >= 2
        }

        # Keywords ATS candidatas: las del JD (ordenadas por frecuencia).
        # merge.py las filtra contra el master (solo sobreviven las que
        # existen en ambos lados) — acá no se descarta nada, la verificación
        # es responsabilidad exclusiva de _build_verified_keywords.
        max_keywords = self.config.get("max_keywords", 10)
        keywords_detected = _jd_kws[:max_keywords]

        summary_index, summary_index_mode = self._resolve_summary_index(master_cv, query_text)

        selection: dict[str, Any] = {
            "selected_experience": [],
            "selected_projects": [],
            "selected_skills_indices": [],
            "selected_education_indices": [],
            "summary_index": summary_index,
            "summary_index_mode": summary_index_mode,  # NUEVO: transparencia de cómo se eligió
            "keywords_detected": keywords_detected,
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
            keyword_ranking = build_keyword_ranking(
                [{"id": b.id, "text": b.text} for b in bullets], job_description
            )
            hybrid_ranking = reciprocal_rank_fusion(
                sparse_ranking,
                dense_ranking,
                keyword_ranking=keyword_ranking,
                keyword_weight=self.config.get("keyword_boost_weight", 0.5),
            )

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
                selection["excluded_skills_indices"] = skill_indices[max_entries:]

            elif section == "education":
                seen = set()
                edu_indices = []
                for b in final_ranking:
                    idx = b["entry_index"]
                    if idx != 0 and idx not in seen:
                        seen.add(idx)
                        edu_indices.append(idx)
                selection["selected_education_indices"] = edu_indices[:max_entries]
                selection["excluded_education_indices"] = edu_indices[max_entries:]

            else:
                grouped, excluded_grouped = _group_bullets_into_entries(
                    final_ranking,
                    max_entries,
                    max_highlights,
                    critical_keyword_variants,
                    self.config.get("diversity_lambda", 0.7),
                )
                key = f"selected_{section}"
                selection[key] = grouped
                selection[f"excluded_{section}"] = excluded_grouped
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

        _jd_kws, _jd_freqs = extract_keywords(job_description)
        critical_keyword_variants = {
            kw: get_synonym_variants(kw)
            for kw in _jd_kws
            if _jd_freqs.get(kw, 0) >= 2
        }

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
        keyword_ranking = build_keyword_ranking(
            [{"id": b.id, "text": b.text} for b in bullets], job_description
        )
        hybrid_ranking = reciprocal_rank_fusion(
            sparse_ranking,
            dense_ranking,
            keyword_ranking=keyword_ranking,
            keyword_weight=self.config.get("keyword_boost_weight", 0.5),
        )

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
            return {
                "selected_skills_indices": skill_indices[:max_entries],
                "excluded_skills_indices": skill_indices[max_entries:],
                "score_mode": score_mode,
            }

        elif section_name == "education":
            seen = set()
            edu_indices = []
            for b in final_ranking:
                idx = b["entry_index"]
                if idx != 0 and idx not in seen:
                    seen.add(idx)
                    edu_indices.append(idx)
            return {
                "selected_education_indices": edu_indices[:max_entries],
                "excluded_education_indices": edu_indices[max_entries:],
                "score_mode": score_mode,
            }

        else:
            grouped, excluded_grouped = _group_bullets_into_entries(
                final_ranking,
                max_entries,
                max_highlights,
                critical_keyword_variants,
                self.config.get("diversity_lambda", 0.7),
            )
            if section_name in ("experience", "projects") and grouped:
                grouped = _reorder_entries_chronologically(
                    master_cv, section_name, grouped
                )
            return {
                f"selected_{section_name}": grouped,
                f"excluded_{section_name}": excluded_grouped,
                "score_mode": score_mode,
            }


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
            "diversity_lambda", "keyword_boost_weight",
        )},
        sort_keys=True,
    )
    config_hash = hashlib.sha256(hashable.encode("utf-8")).hexdigest()
    if _engine_singleton is None or _engine_singleton_hash != config_hash:
        _engine_singleton = SelectionEngine(config)
        _engine_singleton_hash = config_hash
    return _engine_singleton