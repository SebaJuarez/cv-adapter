"""Router de sistema: health check e índice de retrieval."""

from typing import Any, Dict

from fastapi import APIRouter, HTTPException

from src.config import load_config
from src.retrieval.selection_cache import clear_selection_cache
from src.retrieval.store import IndexStore

router = APIRouter(tags=["system"])


@router.get("/api/health")
def health_check() -> Dict[str, Any]:
    config = load_config()
    provider = config.get("llm_provider", "ollama")

    status = {
        "llm": {"ok": False, "provider": provider, "model": None, "error": None},
        "embeddings": {
            "ok": False,
            "dense_model": None,
            "cross_encoder": None,
            "error": None,
        },
    }

    if provider == "openai":
        _check_openai_health(status["llm"], config)
    else:
        _check_ollama_health(status["llm"], config)

    try:
        from sentence_transformers import SentenceTransformer

        config = load_config()
        status["embeddings"]["dense_model"] = config.get("dense_model", "intfloat/multilingual-e5-small")
        status["embeddings"]["cross_encoder"] = config.get("cross_encoder_model", "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1")
        status["embeddings"]["ok"] = True
    except ImportError as e:
        status["embeddings"]["error"] = f"Librerías de embeddings no instaladas: {e}"

    all_ok = status["llm"]["ok"] and status["embeddings"]["ok"]
    return {"ok": all_ok, **status}


def _check_ollama_health(llm_status: Dict[str, Any], config: Dict[str, Any]) -> None:
    try:
        import ollama
    except ImportError:
        llm_status["error"] = (
            "El paquete 'ollama' no está instalado. Corré: pip install ollama"
        )
        return

    model = config["ollama_model"]
    llm_status["model"] = model
    try:
        models = ollama.list()
        available = any(m["model"] == model for m in models.get("models", []))
        llm_status["ok"] = available
        if not available:
            llm_status["error"] = f"Modelo '{model}' no descargado. Ejecutá: ollama pull {model}"
    except Exception as e:
        llm_status["error"] = str(e)


def _check_openai_health(llm_status: Dict[str, Any], config: Dict[str, Any]) -> None:
    model = config["openai_model"]
    llm_status["model"] = model
    api_key = config.get("openai_api_key", "")
    if not api_key:
        llm_status["error"] = (
            "No hay API key configurada. Andá a Configuración y completá 'API key de OpenAI', "
            "o volvé a llm_provider=ollama para el modelo local."
        )
        return
    try:
        from openai import OpenAI

        base_url = config.get("openai_base_url", "") or None
        client = OpenAI(api_key=api_key, base_url=base_url)
        client.models.list()
        llm_status["ok"] = True
    except Exception as e:
        llm_status["error"] = str(e)


@router.post("/api/clear-index")
def clear_retrieval_index() -> Dict[str, Any]:
    try:
        store = IndexStore()
        store.clear()
        # El cache de selección (P0.1) también deriva del master/config:
        # si el usuario limpia los índices, espera resetear todo el estado
        # derivado, no solo el corpus BM25/embeddings.
        clear_selection_cache()
        return {
            "ok": True,
            "message": "Índices de retrieval eliminados. Se reconstruirán en la próxima generación.",
        }
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"No se pudieron eliminar los índices: {e}"
        )
