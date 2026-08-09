"""Router de configuración del pipeline."""

from typing import Any, Dict

from fastapi import APIRouter, HTTPException

from src.config import DEFAULTS, load_config, save_config

router = APIRouter(tags=["config"])


@router.get("/api/config")
def get_config() -> Dict[str, Any]:
    return load_config()


@router.post("/api/config")
def update_config(payload: Dict[str, Any]) -> Dict[str, Any]:
    unknown = set(payload) - set(DEFAULTS)
    if unknown:
        raise HTTPException(
            status_code=400, detail=f"Claves desconocidas: {sorted(unknown)}"
        )
    return save_config(payload)
