"""Router de sistema: health check e índice de retrieval."""

from typing import Any, Dict

from fastapi import APIRouter, HTTPException

from src.config import load_config
from src.retrieval.store import IndexStore

router = APIRouter(tags=["system"])


@router.get("/api/health")
def health_check() -> Dict[str, Any]:
    import ollama

    status = {
        "ollama": {"ok": False, "model": None, "error": None},
        "embeddings": {
            "ok": False,
            "dense_model": None,
            "cross_encoder": None,
            "error": None,
        },
    }

    try:
        config = load_config()
        model = config["ollama_model"]
        models = ollama.list()
        available = any(m["model"] == model for m in models.get("models", []))
        status["ollama"]["ok"] = available
        status["ollama"]["model"] = model
        if not available:
            status["ollama"]["error"] = f"Modelo '{model}' no descargado. Ejecutá: ollama pull {model}"
    except Exception as e:
        status["ollama"]["error"] = str(e)

    try:
        from sentence_transformers import SentenceTransformer

        config = load_config()
        status["embeddings"]["dense_model"] = config.get("dense_model", "sentence-transformers/all-MiniLM-L6-v2")
        status["embeddings"]["cross_encoder"] = config.get("cross_encoder_model", "cross-encoder/ms-marco-MiniLM-L-6-v2")
        status["embeddings"]["ok"] = True
    except ImportError as e:
        status["embeddings"]["error"] = f"Librerías de embeddings no instaladas: {e}"

    all_ok = status["ollama"]["ok"] and status["embeddings"]["ok"]
    return {"ok": all_ok, **status}


@router.post("/api/clear-index")
def clear_retrieval_index() -> Dict[str, Any]:
    try:
        store = IndexStore()
        store.clear()
        return {
            "ok": True,
            "message": "Índices de retrieval eliminados. Se reconstruirán en la próxima generación.",
        }
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"No se pudieron eliminar los índices: {e}"
        )
