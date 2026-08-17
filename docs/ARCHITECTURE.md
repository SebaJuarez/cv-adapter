# Arquitectura del pipeline  detalle de implementación

Este documento asume que ya leíste la sección [**Motor de
recuperación**](../README.md#motor-de-recuperación) del README (los tres
canales de retrieval, RRF, cross-encoder, MMR, fase LLM, merge
determinístico)

## 1. Procesamiento del JD (Job Description)

Antes de que el JD llegue a los tres canales de retrieval:

- `extract_requirements_section` recorta heurísticamente la parte de
  "requisitos" del texto (busca encabezados típicos en ES/EN), para no
  usar como query el bloque de beneficios o el "cómo postularte".
- `chunk_text` parte el JD en ventanas de ~200 tokens con overlap, porque
  el modelo de embeddings trunca textos largos.
- `extract_negated_terms` detecta cláusulas de exclusión ("no se requiere
  X", "not required"), para que el bullet que las matchea se penalice más
  adelante en vez de tratarse como requisito positivo.
- **HyDE** (opcional, `use_hyde`): el LLM redacta un "CV hipotético" del
  candidato ideal para la oferta, y ese texto se antepone a los chunks del
  canal denso.

## 2. Cache de selección

El paso caro del pipeline (embeddings + cross-encoder) se cachea por hash
de `(oferta, CV maestro, config de retrieval)`. Regenerar la misma oferta,
o pedir "regenerar sección" desde la UI, no vuelve a pagar ese costo salvo
que algo de esa clave haya cambiado.

El TTL y el comportamiento de invalidación viven en
`src/retrieval/selection_cache.py`. Si editás `dense_model` o
`cross_encoder_model` en `config.json`, la clave de cache cambia sola y
no reusa resultados viejos; si además querés descartar los embeddings ya
persistidos en disco, hay que borrar `data/selection_cache/` a mano (o
esperar el TTL).

## 3. Referencia de `config.json`

Knobs del motor de retrieval, editables desde la pestaña **Configuración**
de la UI o directamente en el archivo:

| Clave | Qué controla |
|---|---|
| `rrf_k` | Constante `k` de Reciprocal Rank Fusion más chica que el default típico de la literatura, pensada para corpus de decenas de bullets por sección |
| `sparse_weight` / `dense_weight` / `keyword_boost_weight` | Peso de cada canal al fusionar los tres rankings |
| `diversity_lambda` | Balance relevancia/diversidad dentro de MMR |
| `negation_penalty` | Cuánto baja el score un bullet que matchea un término que el JD excluye explícitamente |
| `max_global_coverage_swaps` | Tope de swaps para rescatar una keyword crítica que quedó afuera por presupuesto de página |
| `use_reranker` | Activa/desactiva el paso de cross-encoder |
| `use_stemming` | Activa/desactiva stemming Snowball ES/EN en el canal sparse |
| `use_hyde` | Activa HyDE en el procesamiento del JD |
| `selection_cache_ttl_hours` | TTL del cache de selección |
| `dense_model` / `cross_encoder_model` | IDs de HuggingFace de los modelos de embeddings y re-ranking. |

## 4. Eval harness

```bash
python scripts/eval_retrieval.py --master data/master_cv_example.yaml
```

Compara canales aislados (sparse/dense/keywords) y distintas
configuraciones de fusión contra un set de evaluación, reportando
`recall@10` y `MRR@10` por config. Es el mecanismo para validar cualquier
cambio de knob antes de aplicarlo en serio, incluido activar HyDE.