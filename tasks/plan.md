# Plan: Generalización del motor híbrido de recuperación

Ver `tasks/spec.md` para el contexto. Orden por dependencias (cada fase es un commit):

## Fase 1 — Expansión léxica (sparse) — `feat(retrieval): stemming es/en en el tokenizador BM25`

- Depende de: nada.
- `src/retrieval/sparse.py`: `tokenize_with_synonyms` aplica Snowball ES+EN tras expandir sinónimos, antes de filtrar stopwords. Se elige stemmer por presencia de tokens latinos (ES si el texto tiene tildes/ñ o palabras ES conocidas, si no EN) — simplificación: aplicar ES y EN sobre cada token y quedarse con el resultado menor? NO: usar detección por idioma del texto (heurística simple: si el texto contiene tildes → ES; si no, correr ambos y elegir el stem más corto). Decidir en implementación, documentar en docstring.
- `src/config.py`: `use_stemming: true` en DEFAULTS.
- `src/selection.py`: MMR ya usa `tokenize_with_synonyms` → recibe stemming gratis (aceptable).
- Tests: actualizar `test_tokenize_ci_cd_expande_sinonimos`; agregar casos de variantes morfológicas; verificar `ci/cd`, `c++`, `node.js` no se rompen.

## Fase 2 — Modelos multilingües + fix de invalidación — `feat(retrieval): modelos multilingües (e5-small + mMARCO)`

- Depende de: Fase 1 (el hash de índice incluirá `use_stemming`).
- `src/config.py`: nuevos defaults `dense_model`, `cross_encoder_model`.
- `src/retrieval/dense.py`: helper `embed_query`/`embed_passages` (o flag en SelectionEngine) que antepone `query:`/`passage:` si el modelo es e5 (detección por nombre).
- `src/selection.py`: usar los prefijos al encodear query chunks y bullets.
- `src/retrieval/store.py`: `is_fresh`/`save_hash` incluyen hash de (master, dense_model, cross_encoder_model, use_stemming).
- `src/selection.py`: hash del singleton incluye `rrf_k`, `sparse_weight`, `dense_weight`, `use_stemming` (adelanto de Fase 3, inofensivo).
- Tests: hash cambia con modelo; prefijos aplicados solo para e5.

## Fase 3 — Fusión calibrada — `feat(retrieval): rrf_k y pesos de canales configurables`

- Depende de: Fase 2.
- `src/config.py`: `rrf_k: 15`, `sparse_weight: 1.0`, `dense_weight: 1.0`.
- `src/retrieval/hybrid.py`: `reciprocal_rank_fusion(sparse_ranking, dense_ranking, k, keyword_ranking, keyword_weight, sparse_weight, dense_weight)`.
- `src/selection.py`: pasar los pesos desde config en los dos call sites.
- Tests: RRF respeta pesos/k; default documentado en docstring.

## Fase 4 — Eval harness — `feat(retrieval): eval harness y eval set sintético`

- Depende de: Fases 1–3 (evalúa configs ya implementadas).
- `tests/data/eval/*.json`: ~10 JDs ficticios ES/EN con bullets relevantes del `master_cv_example.yaml`.
- `scripts/eval_retrieval.py`: carga casos (tests/data/eval + data/eval si existe), corre cada canal por separado y el pipeline completo (reusando `src/`), reporta recall@10/MRR + barrido (rrf_k ∈ {10,15,20,30,60}, pesos sparse/dense ∈ {0.5,1.0}, use_stemming on/off).
- Salida markdown del barrido → decide defaults finales de `rrf_k`/pesos.

## Fase 5 — Verificación integral

- Depende de: Fases 1–4.
- `pytest` completo; CLI con JD real; comparación antes/después de la selección; `/api/health`; actualizar AGENTS.md si aplica (modelos nuevos, flags nuevos).

## Riesgos y mitigaciones

- Modelos nuevos requieren descarga (e5-small ~120MB, mMARCO ~470MB) — primer uso, solo una vez.
- mMARCO algo más lento que ms-marco en CPU — mismo orden de magnitud; configurable.
- Stemming puede romper términos cortos — mitigado por `TECH_ALLOWLIST` y tests de regresión.
- Sin eval real etiquetado, los defaults se fijan con el set sintético — el harness deja el barrido re-ejecutable cuando el usuario etiquete.
