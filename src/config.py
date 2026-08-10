"""Configuración editable del pipeline.

Antes estos valores eran constantes hardcodeadas en merge.py y llm_node.py.
Ahora viven en config.json (raíz del proyecto), editable desde la UI web o
a mano. Si el archivo no existe todavía, se usan estos defaults — que son
los mismos valores que ya veníamos usando.
"""
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
    "dense_model": "sentence-transformers/all-MiniLM-L6-v2",
    "cross_encoder_model": "cross-encoder/ms-marco-MiniLM-L-6-v2",
    "keyword_boost_weight": 0.5,
    "show_keywords_line": True,
    "diversity_lambda": 0.7,
}


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