"""Eval harness del motor de retrieval híbrido.

Compara los canales (sparse BM25, dense, keywords) y configs de fusión
(RRF k/pesos, stemming on/off) contra un eval set etiquetado, y reporta
recall@10 y MRR@10 por config. Reusa las piezas peladas de src/ — no
duplica lógica del pipeline.

Uso:
    python scripts/eval_retrieval.py [--master data/master_cv_example.yaml]
    python scripts/eval_retrieval.py [--master data/master_cv.yaml]

Casos de evaluación (formato JSON, lista de objetos):
    {
        "id": "nombre-del-caso",
        "job_description": "texto de la oferta",
        "relevant_bullets": ["experience_0_bullet_0", "skills_1_0"],
        "note": "opcional: qué generalización cubre"
    }

Fuentes, en orden:
1. tests/data/eval/*.json  -> eval set sintético (versionable, sin datos
   personales). Etiquetado contra master_cv_example.yaml.
2. data/eval/*.json        -> eval set real (gitignored): copiá la plantilla
   de abajo, etiquetá los bullets relevantes de TU master y corré el script
   con --master data/master_cv.yaml. Plantilla:

   [
     {
       "id": "real-001",
       "job_description": "...",
       "relevant_bullets": ["experience_0_bullet_0"],
       "note": ""
     }
   ]

El script reporta por cada config: recall@10 y MRR@10 promediados sobre los
casos. Incluye canales aislados, el barrido de fusión (k, pesos, stemming)
y el pipeline completo con reranker (solo para la config por defecto de
config.json, que es lo que corre el pipeline real).
"""

import argparse
import json
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import load_config
from src.retrieval import (
    SparseIndex,
    build_keyword_ranking,
    chunk_text,
    extract_requirements_section,
    reciprocal_rank_fusion,
)
from src.retrieval.dense import DenseIndex, prefixed_texts
from src.retrieval.sparse import set_stemming
from src.selection import _extract_bullets_from_section

ROOT = Path(__file__).resolve().parent.parent
SYNTHETIC_EVAL_DIR = ROOT / "tests" / "data" / "eval"
REAL_EVAL_DIR = ROOT / "data" / "eval"

_RETRIEVAL_SECTIONS = ["experience", "projects", "skills", "education"]


def load_cases() -> list[dict]:
    """Carga los casos del eval set sintético + real (si existe)."""
    cases = []
    for case_dir in (SYNTHETIC_EVAL_DIR, REAL_EVAL_DIR):
        if not case_dir.exists():
            continue
        for path in sorted(case_dir.glob("*.json")):
            with open(path, encoding="utf-8") as f:
                cases.extend(json.load(f))
    if not cases:
        raise SystemExit(
            "No hay casos de eval en tests/data/eval/ ni data/eval/ (gitignored)."
        )
    return cases


def load_master(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def recall_at_k(ranking: list[str], relevant: set[str], k: int = 10) -> float:
    if not relevant:
        return 0.0
    return len(set(ranking[:k]) & relevant) / len(relevant)


def mrr_at_k(ranking: list[str], relevant: set[str], k: int = 10) -> float:
    for i, doc in enumerate(ranking[:k]):
        if doc in relevant:
            return 1.0 / (i + 1)
    return 0.0


def build_corpus(master: dict) -> list[dict]:
    bullets = []
    for section in _RETRIEVAL_SECTIONS:
        for b in _extract_bullets_from_section(master, section):
            bullets.append({"id": b.id, "text": b.text})
    return bullets


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--master",
        type=Path,
        default=ROOT / "data" / "master_cv_example.yaml",
        help="Master YAML del que salen los bullets (default: example).",
    )
    args = parser.parse_args()

    config = load_config()
    model_name = config.get("dense_model", "")
    use_reranker = config.get("use_reranker", True)

    from sentence_transformers import CrossEncoder, SentenceTransformer

    print(f"Cargando modelo denso: {model_name} ...", file=sys.stderr)
    dense_model = SentenceTransformer(model_name, device="cpu")
    reranker = None
    if use_reranker:
        ce_name = config.get("cross_encoder_model", "")
        print(f"Cargando reranker: {ce_name} ...", file=sys.stderr)
        from src.retrieval.rerank import CrossEncoderReranker

        reranker = CrossEncoderReranker(ce_name, device="cpu")

    master = load_master(args.master)
    cases = load_cases()
    corpus = build_corpus(master)
    relevant_ids = {bid for c in cases for bid in c["relevant_bullets"]}
    missing = relevant_ids - {b["id"] for b in corpus}
    if missing:
        print(
            f"ADVERTENCIA: bullets relevantes inexistentes en el master: "
            f"{sorted(missing)} (¿master equivocado?)",
            file=sys.stderr,
        )

    # Índices compartidos por todos los casos (el corpus no cambia).
    # El flag de stemming es global en sparse.py: se construye cada índice
    # con el flag en el estado correcto y se restaura después.
    set_stemming(True)
    sparse_stem = SparseIndex()
    sparse_stem.build(corpus)
    set_stemming(False)
    sparse_nostem = SparseIndex()
    sparse_nostem.build(corpus)
    set_stemming(True)

    dense_idx = DenseIndex(dense_model, model_name)
    dense_idx.build(corpus)

    # Configs de fusión a comparar: barrido de k y pesos (stemming on) +
    # una config sin stemming + el pipeline por defecto (con reranker).
    fusion_configs: list[tuple[str, dict]] = [
        ("k=10", {"k": 10, "sparse_weight": 1.0, "dense_weight": 1.0}),
        ("k=15 (default)", {"k": 15, "sparse_weight": 1.0, "dense_weight": 1.0}),
        ("k=30", {"k": 30, "sparse_weight": 1.0, "dense_weight": 1.0}),
        ("k=60 (Cormack)", {"k": 60, "sparse_weight": 1.0, "dense_weight": 1.0}),
        ("sparse 1.5 / dense 1.0", {"k": 15, "sparse_weight": 1.5, "dense_weight": 1.0}),
        ("sparse 1.0 / dense 1.5", {"k": 15, "sparse_weight": 1.0, "dense_weight": 1.5}),
        ("k=15 sin stemming", {"k": 15, "sparse_weight": 1.0, "dense_weight": 1.0}),
    ]
    default_config = {
        "k": config.get("rrf_k", 15),
        "sparse_weight": config.get("sparse_weight", 1.0),
        "dense_weight": config.get("dense_weight", 1.0),
    }

    # Acumuladores: (label) -> [recall, mrr] por caso
    results: dict[str, list[tuple[float, float]]] = {
        "sparse (stem on)": [],
        "sparse (sin stem)": [],
        "dense": [],
        "keywords": [],
        "reranker (pipeline default)": [],
    }
    for label, _ in fusion_configs:
        results[label] = []

    for case in cases:
        jd = case["job_description"]
        relevant = set(case["relevant_bullets"])
        query_text = extract_requirements_section(jd)
        query_chunks = chunk_text(query_text, max_tokens=200, overlap=50)
        chunk_embs = dense_model.encode(
            prefixed_texts(query_chunks, "query", model_name),
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )

        set_stemming(True)
        sparse_stem_ranking = sparse_stem.query(query_text, top_k=50)
        set_stemming(False)
        sparse_nostem_ranking = sparse_nostem.query(query_text, top_k=50)
        set_stemming(True)

        dense_ranking, _ = dense_idx.query(chunk_embs, top_k=50)
        kw_ranking = build_keyword_ranking(corpus, jd)

        results["sparse (stem on)"].append(
            (recall_at_k(sparse_stem_ranking, relevant), mrr_at_k(sparse_stem_ranking, relevant))
        )
        results["sparse (sin stem)"].append(
            (recall_at_k(sparse_nostem_ranking, relevant), mrr_at_k(sparse_nostem_ranking, relevant))
        )
        results["dense"].append(
            (recall_at_k(dense_ranking, relevant), mrr_at_k(dense_ranking, relevant))
        )
        results["keywords"].append(
            (recall_at_k(kw_ranking, relevant), mrr_at_k(kw_ranking, relevant))
        )

        for label, fcfg in fusion_configs:
            stemming = not label.endswith("sin stemming")
            sparse_rank = sparse_stem_ranking if stemming else sparse_nostem_ranking
            ranking = reciprocal_rank_fusion(
                sparse_rank,
                dense_ranking,
                k=fcfg["k"],
                keyword_ranking=kw_ranking,
                keyword_weight=config.get("keyword_boost_weight", 0.5),
                sparse_weight=fcfg["sparse_weight"],
                dense_weight=fcfg["dense_weight"],
            )
            results[label].append(
                (recall_at_k(ranking, relevant), mrr_at_k(ranking, relevant))
            )

        if reranker is not None:
            hybrid_default = reciprocal_rank_fusion(
                sparse_stem_ranking,
                dense_ranking,
                k=default_config["k"],
                keyword_ranking=kw_ranking,
                keyword_weight=config.get("keyword_boost_weight", 0.5),
                sparse_weight=default_config["sparse_weight"],
                dense_weight=default_config["dense_weight"],
            )
            candidates = [b for b in corpus if b["id"] in hybrid_default[:30]]
            reranked = reranker.rerank(query_text, candidates, top_k=10)
            reranked_ids = [bid for bid, _ in reranked]
            results["reranker (pipeline default)"].append(
                (recall_at_k(reranked_ids, relevant), mrr_at_k(reranked_ids, relevant))
            )

    n = len(cases)
    print(f"\n# Eval retrieval — {n} casos — master: {args.master}")
    print()
    print("| canal/config | recall@10 | MRR@10 |")
    print("|---|---|---|")
    for label in list(results):
        rows = results[label]
        avg_r = sum(r for r, _ in rows) / n
        avg_m = sum(m for _, m in rows) / n
        print(f"| {label} | {avg_r:.3f} | {avg_m:.3f} |")

    # Mejor config de fusión por MRR
    fusion_ranked = sorted(
        ((label, sum(m for _, m in results[label]) / n) for label, _ in fusion_configs),
        key=lambda x: x[1],
        reverse=True,
    )
    print(f"\nMejor config de fusión por MRR@10: {fusion_ranked[0][0]} "
          f"({fusion_ranked[0][1]:.3f})")


if __name__ == "__main__":
    main()
