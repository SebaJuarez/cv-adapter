"""Router de configuración del pipeline."""

from typing import Any, Dict

from fastapi import APIRouter, HTTPException

from src.config import (
    ConfigValidationError,
    load_config,
    save_config,
    validate_config,
)

router = APIRouter(tags=["config"])


@router.get("/api/config")
def get_config() -> Dict[str, Any]:
    return load_config()


@router.post("/api/config")
def update_config(payload: Dict[str, Any]) -> Dict[str, Any]:
    try:
        validated = validate_config(payload)
    except ConfigValidationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return save_config(validated)
