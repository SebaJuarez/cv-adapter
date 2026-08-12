"""Configuración editable del pipeline.

Antes estos valores eran constantes hardcodeadas en merge.py y llm_node.py.
Ahora viven en config.json (raíz del proyecto), editable desde la UI web o
a mano. Si el archivo no existe todavía, se usan estos defaults — que son
los mismos valores que ya veníamos usando.
"""
import hashlib
import json
import math
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
    # Líneas estimadas que caben en una página A4 (P1.4): presupuesto de la
    # heurística estimate_page_overflow en merge.py — un AVISO no bloqueante,
    # el render real lo hace Typst y varía por tema.
    "lines_per_page": 45,
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
    # Keywords ATS manuales (P1.3): el usuario fija términos que SIEMPRE
    # entran al CV aunque la oferta no los mencione. Se agregan a las
    # detectadas del JD (afectan keywords_detected, el ranking por
    # keywords y el reporte ATS).
    "custom_keywords": [],
    # HyDE (P3.1): con True, el LLM redacta un "CV hipotético" del candidato
    # ideal para la oferta y ese texto se antepone a los chunks del JD en el
    # canal denso (mejora el recall cuando el JD usa jerga que no aparece
    # literal en el master). Opt-in ESTRICTO y experimental: solo se mergea
    # si el eval harness (scripts/eval_retrieval.py --hyde) muestra mejora.
    "use_hyde": False,
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
    "custom_keywords",
    "use_hyde",
)


# ---------------------------------------------------------------------
# Validación de tipos/rangos del POST /api/config (08)
#
# Espeja las reglas de validateConfig del frontend (settings.js): enteros
# >= 1 para los límites de página, booleans, select del proveedor y strings
# no vacías. Los rangos de los knobs que la UI no expone (pesos del RRF,
# lambdas, TTL, swaps) se derivan de la semántica documentada en DEFAULTS:
# peso 0 = canal ignorado, lambda/penalty 1.0 = desactivado, TTL/swaps
# 0 = pasada desactivada.
# ---------------------------------------------------------------------
_INT_MIN_1 = frozenset(
    {
        "max_experience_entries",
        "max_project_entries",
        "max_highlights_per_entry",
        "max_skill_categories",
        "max_education_extra",
        "max_keywords",
        "rrf_k",
        "lines_per_page",
    }
)
_INT_MIN_0 = frozenset({"selection_cache_ttl_hours", "max_global_coverage_swaps"})
_FLOAT_MIN_0 = frozenset({"sparse_weight", "dense_weight", "keyword_boost_weight"})
_FLOAT_0_1 = frozenset({"diversity_lambda", "negation_penalty"})
_BOOL_KEYS = frozenset({"use_reranker", "use_stemming", "show_keywords_line", "use_hyde"})
_SELECT_KEYS = {"llm_provider": frozenset({"ollama", "openai"})}
_LIST_KEYS = frozenset({"custom_keywords"})
_STRING_REQUIRED = frozenset(
    {"ollama_model", "openai_model", "rendercv_theme", "dense_model", "cross_encoder_model"}
)
# openai_base_url puede quedar vacía (vacío = endpoint oficial de OpenAI).
_STRING_OPTIONAL = frozenset({"openai_api_key", "openai_base_url"})


class ConfigValidationError(ValueError):
    """Payload de config con tipos o rangos inválidos (POST /api/config → 400)."""


def _es_entero(valor: Any) -> bool:
    return (
        isinstance(valor, int)
        and not isinstance(valor, bool)
        or isinstance(valor, float)
        and valor.is_integer()
    )


def _es_numero_finito(valor: Any) -> bool:
    return isinstance(valor, (int, float)) and not isinstance(valor, bool) and math.isfinite(valor)


def validate_config(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Valida y normaliza un payload de config contra las reglas de DEFAULTS.

    Rechaza claves desconocidas, tipos equivocados y rangos fuera de lo
    esperado; normaliza strings (trim) y custom_keywords (lista de strings
    sin vacíos). Devuelve el payload listo para save_config.
    """
    unknown = set(payload) - set(DEFAULTS)
    if unknown:
        raise ConfigValidationError(f"Claves desconocidas: {sorted(unknown)}")

    validated: Dict[str, Any] = {}
    for key, value in payload.items():
        if key in _INT_MIN_1:
            if not _es_entero(value) or value < 1:
                raise ConfigValidationError(
                    f'Clave "{key}" debe ser un número entero mayor o igual a 1.'
                )
            validated[key] = int(value)
        elif key in _INT_MIN_0:
            if not _es_entero(value) or value < 0:
                raise ConfigValidationError(
                    f'Clave "{key}" debe ser un número entero mayor o igual a 0 (0 desactiva la pasada).'
                )
            validated[key] = int(value)
        elif key in _FLOAT_MIN_0:
            if not _es_numero_finito(value) or value < 0:
                raise ConfigValidationError(
                    f'Clave "{key}" debe ser un número mayor o igual a 0 (0 ignora el canal).'
                )
            validated[key] = float(value)
        elif key in _FLOAT_0_1:
            if not _es_numero_finito(value) or not 0 <= value <= 1:
                raise ConfigValidationError(
                    f'Clave "{key}" debe ser un número entre 0 y 1 (1.0 desactiva el ajuste).'
                )
            validated[key] = float(value)
        elif key in _BOOL_KEYS:
            if not isinstance(value, bool):
                raise ConfigValidationError(f'Clave "{key}" debe ser un booleano (true/false).')
            validated[key] = value
        elif key in _SELECT_KEYS:
            opciones = _SELECT_KEYS[key]
            if value not in opciones:
                raise ConfigValidationError(
                    f'Clave "{key}" debe ser uno de: {sorted(opciones)}.'
                )
            validated[key] = value
        elif key in _LIST_KEYS:
            if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
                raise ConfigValidationError(f'Clave "{key}" debe ser una lista de strings.')
            validated[key] = [v.strip() for v in value if v.strip() != ""]
        elif key in _STRING_OPTIONAL:
            if not isinstance(value, str):
                raise ConfigValidationError(f'Clave "{key}" debe ser un string.')
            validated[key] = value.strip()
        elif key in _STRING_REQUIRED:
            if not isinstance(value, str) or value.strip() == "":
                raise ConfigValidationError(f'Clave "{key}" no puede estar vacía.')
            validated[key] = value.strip()

    return validated


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