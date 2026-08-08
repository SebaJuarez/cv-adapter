"""Persistencia YAML de los documentos (master y target).

Separa la lectura/escritura de archivos del resto de la lógica web, para
que ni los routers ni el pipeline tengan que abrir archivos a mano.
"""

from pathlib import Path
from typing import Any, Dict, Optional

import yaml

from .render_node import save_yaml


def load_master_cv(path: Path) -> Optional[Dict[str, Any]]:
    """Lee data/master_cv.yaml. Devuelve None si no existe todavía."""
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def save_master_cv(data: Dict[str, Any], path: Path) -> None:
    """Guarda el CV maestro aplicando strip_internal_keys (via save_yaml)."""
    save_yaml(data, path)
