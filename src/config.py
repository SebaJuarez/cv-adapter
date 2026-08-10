"""Configuración editable del pipeline.

Antes estos valores eran constantes hardcodeadas en merge.py y llm_node.py.
Ahora viven en config.json (raíz del proyecto), editable desde la UI web o
a mano. Si el archivo no existe todavía, se usan estos defaults — que son
los mismos valores que ya veníamos usando.
"""
import hashlib
import json
from pathlib import Path
from typing import Any, Dict

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.json"

DEFAULTS: Dict[str, Any] = {
    # --- proveedor del LLM: "ollama" (local) u "openai" (API remota compatible) ---
    "llm_provider": "ollama",
    "ollama_model": "llama3:8b",
    "openai_api_key": "",
    "openai_model": "gpt-4o-mini",
    "openai_base_url": "",
    "rendercv_theme": "engineeringresumes",
    "max_experience_entries": 2,
    "max_project_entries": 3,
    "max_highlights_per_entry": 4,
    "max_skill_categories": 6,
    "max_education_extra": 1,
    "max_keywords": 10,
    # --- para motor de IR ---
    "use_reranker": True,
    "use_stemming": True,  # stemming Snowball ES/EN en el tokenizador BM25
    # Modelos multilingües (ES/EN): el corpus real mezcla ambos idiomas y
    # los modelos inglés-only (MiniLM/ms-marco) pierden las ofertas en
    # español. e5-small requiere los prefijos query:/passage: al encodear.
    "dense_model": "intfloat/multilingual-e5-small",
    "cross_encoder_model": "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1",
    # RRF: k=60 es el valor de la literatura para corpus TREC (miles de
    # docs); con ~10-50 bullets por sección aplana las diferencias de rank
    # y conviene k=10-20. Los pesos escalan la contribución de cada canal
    # (keyword_boost_weight ya existía; sparse/dense default 1.0).
    "rrf_k": 15,
    "sparse_weight": 1.0,
    "dense_weight": 1.0,
    "keyword_boost_weight": 0.5,
    "show_keywords_line": True,
    "diversity_lambda": 0.7,
    # Cache de selección (P0.1): evita recalculcar embeddings + reranker
    # cuando se regenera la misma oferta. TTL en horas; la clave se deriva
    # de selection_config_fingerprint (ver abajo).
    "selection_cache_ttl_hours": 24,
    # Penalización de términos negados (P0.2): multiplicador de score para
    # bullets que matchean algo que el JD excluye explícitamente ("no se
    # requiere X"). < 1 baja el rank; 1.0 desactiva la penalización.
    "negation_penalty": 0.3,
    # Swaps de cobertura global (P0.3): cantidad máxima de intercambios
    # entre entradas que puede hacer _ensure_global_keyword_coverage para
    # que las keywords críticas del JD (frecuencia >= 2) queden cubiertas
    # por alguna entrada seleccionada. 0 desactiva la pasada.
    "max_global_coverage_swaps": 3,
}

# Claves de config que cambian el resultado de SelectionEngine.select() /
# select_section(). TODO parámetro que afecte la selección DEBE estar acá:
# es la única fuente de verdad para la clave del cache de selección y para
# el hash del singleton del motor (get_selection_engine en selection.py).
# Al agregar una clave de config que influya en el ranking/selección
# (ej. negation_penalty, custom_keywords, max_global_coverage_swaps,
# use_hyde), hay que sumarla a este set o el cache devolverá resultados
# stale.
_SELECTION_CONFIG_KEYS = (
    "dense_model",
    "cross_encoder_model",
    "use_reranker",
    "use_stemming",
    "max_experience_entries",
    "max_project_entries",
    "max_highlights_per_entry",
    "max_skill_categories",
    "max_education_extra",
    "max_keywords",
    "diversity_lambda",
    "keyword_boost_weight",
    "rrf_k",
    "sparse_weight",
    "dense_weight",
    "negation_penalty",
    "max_global_coverage_swaps",
)


def selection_config_fingerprint(config: Dict[str, Any]) -> str:
    """Hash de las claves de config que afectan la selección IR.

    Compartido por get_selection_engine (para reutilizar la instancia con
    modelos en memoria) y por el cache de selección (para invalidar
    resultados cuando el usuario toca un knob del ranking). Mismo criterio
    que IndexStore.build_fingerprint: JSON con sort_keys para ser inmune al
    orden de inserción.
    """
    hashable = json.dumps(
        {k: config.get(k) for k in _SELECTION_CONFIG_KEYS},
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(hashable.encode("utf-8")).hexdigest()


def load_config() -> Dict[str, Any]:
    """Lee config.json y lo completa con los defaults para cualquier clave
    faltante (así una versión vieja del archivo no rompe nada nuevo)."""
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                saved = json.load(f)
            if isinstance(saved, dict):
                return {**DEFAULTS, **saved}
        except (json.JSONDecodeError, OSError):
            pass
    return dict(DEFAULTS)


def save_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """Guarda la config (mergeada con defaults para no perder claves) y
    devuelve el resultado final guardado."""
    merged = {**DEFAULTS, **{k: v for k, v in config.items() if k in DEFAULTS}}
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2, ensure_ascii=False)
    return merged