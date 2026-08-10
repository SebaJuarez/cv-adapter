# Spec: Generalización del motor híbrido de recuperación (sparse + dense)

## Objetivo

Mejorar la generalización del IR híbrido del pipeline (BM25 + embeddings + keywords + RRF + cross-encoder) frente a ofertas que no usan exactamente el vocabulario del CV master. Criterios de éxito:

1. Variantes morfológicas ES/EN matchean en el canal léxico ("trabajo"/"trabajé"/"trabajando", "container"/"containers") sin tocar la verificación ATS literal.
2. El canal semántico y el reranker funcionan con ofertas en español (hoy son inglés-only).
3. Cambiar `dense_model`/`cross_encoder_model` en config.json invalida el índice persistido (hoy carga embeddings stale).
4. Fusión calibrada a corpus chico: `rrf_k` y pesos de canales configurables (evidencia: k=60 es para corpus TREC; con ~10–50 bullets por sección, k=10–20).
5. Existe un eval harness (`scripts/eval_retrieval.py`) con eval set sintético versionable + eval real en `data/eval/` (gitignored) que reporta recall@10/MRR por canal y barrido de configs.

## Decisiones tomadas (con el usuario)

- Modelo denso: `intfloat/multilingual-e5-small` (prefijos `query:`/`passage:`).
- Reranker: `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1` (multilingüe).
- Expansión LLM (Q2E/HyDE): excluida — la evidencia (EACL 2024, ACL 2025) muestra que perjudica a retrievers con reranker fuerte y ampliaría el rol del LLM en fase 1.
- Eval set: sintético en `tests/data/eval/` + real en `data/eval/` etiquetado por el usuario.

## Comandos

- Tests: `pytest`
- CLI: `python main.py --master data/master_cv.yaml --job data/job_description.txt`
- Eval: `python scripts/eval_retrieval.py`
- Web: `uvicorn app:app --reload` → http://127.0.0.1:8000

## Estructura

```
src/retrieval/sparse.py      → stemming Snowball ES/EN en tokenize_with_synonyms
src/retrieval/dense.py       → helper de prefijos E5 (query:/passage:)
src/retrieval/hybrid.py      → rrf_k y pesos de canales en reciprocal_rank_fusion
src/retrieval/store.py       → is_fresh/save_hash incluyen identidad de modelos
src/config.py                → nuevos DEFAULTS: use_stemming, rrf_k, sparse_weight, dense_weight, nuevos modelos
src/selection.py             → prefijos E5 al encodear, hash del singleton con claves nuevas
tests/test_retrieval.py      → tests actualizados + casos de stemming
tests/test_selection.py      → casos de prefijos/hash si aplica
tests/data/eval/             → eval set sintético (JSON)
scripts/eval_retrieval.py    → eval harness
data/eval/                   → eval set real (gitignored, etiquetado por el usuario)
tasks/                       → spec, plan, todo
```

## Estilo de código

Mismo estilo del repo: docstrings en español, sin comentarios salvo los necesarios, `from .x import y` relativo en `src/`, dicts tipados con `dict[str, ...]`. El stemming va dentro de `tokenize_with_synonyms` (después de expandir sinónimos, antes del filtro de stopwords), NO en `keyword_in_text`/`_count_keyword_occurrences` (verificación ATS literal) ni antes de encodear (misma regla que stopwords.py).

## Estrategia de testing

- `pytest` (framework existente).
- Actualizar tests que asumen tokens sin stem (ej. `test_tokenize_ci_cd_expande_sinonimos`).
- Tests nuevos: stemming ES/EN, prefijos E5, hash de `IndexStore` con modelos, `rrf_k`/pesos en RRF.
- Verificación manual final: CLI con JD real + barrido de eval.

## Límites

- **Siempre:** correr `pytest` antes de terminar cada fase; respetar invariantes del AGENTS.md (LLM nunca redacta el YAML final; límites de página en código; keywords ATS verificadas; `strip_internal_keys` antes de guardar); respetar el gotcha de `": "` en YAML si se tocan fixtures; textos en español.
- **Preguntar antes:** agregar dependencias nuevas (se evita: `snowballstemmer` ya está vía nltk).
- **Nunca:** romper la verificación ATS literal de merge.py; usar el LLM para expansión de queries; guardar datos personales fuera de `data/` (gitignored).

## Éxito

- `pytest` verde.
- `python scripts/eval_retrieval.py` corre con el set sintético y reporta métricas por canal.
- El barrido del eval fija los defaults finales de `rrf_k`/pesos.
- El CLI con JD real funciona y la selección no empeora respecto a la previa.
