"""Cache en disco de la selección IR.

El paso más caro del pipeline son los embeddings densos + el cross-encoder.
Cuando se regenera la misma oferta (o se pincha "Regenerar sección"
repetidas veces con el mismo JD), el resultado de `SelectionEngine.select()`
es idéntico al de la corrida anterior: no tiene sentido recalculcar nada.

La clave del cache combina:
- el hash del JD (mismo criterio que `src/history.jd_hash`),
- el hash del master_cv (json canónico),
- el fingerprint de config (selection_config_fingerprint, ver src/config.py):
  cualquier knob de retrieval (rrf_k, pesos, modelos, stems, budgets de
  sección, diversity_lambda...) que se cambie invalida la entrada.

El LLM estratégico NO participa acá: el cache guarda solo la selección IR,
y la fase LLM (match_reasons) corre después igual que siempre — la decisión
de qué texto entra al CV es 100% determinística y cacheable.

Seguridad: escritura atómica (tmp + rename) y lectura defensiva — un
archivo corrupto es un miss, nunca un error del pipeline (mismo patrón que
`load_runs` en history.py).
"""

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Dict, Optional

from ..config import selection_config_fingerprint
from ..history import jd_hash

# Directorio por defecto del cache (gitignored, igual que data/retrieval_index).
SELECTION_CACHE_DIR = (
    Path(__file__).resolve().parent.parent.parent / "data" / "selection_cache"
)


def get_cache_key(
    job_description: str,
    master_json: str,
    config: Dict[str, Any],
    section: str = "",
) -> str:
    """Clave del cache para una selección (full o de una sección).

    `master_json` es la serialización canónica del master (json.dumps con
    sort_keys), la misma que ya usa SelectionEngine para el fingerprint de
    IndexStore. `section` desambigua select() (full) de select_section().
    """
    payload = {
        "jd": jd_hash(job_description),
        "master": hashlib.sha256(master_json.encode("utf-8")).hexdigest(),
        "config": selection_config_fingerprint(config),
        "section": section,
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def load_cached_selection(
    cache_dir: Path,
    key: str,
    ttl_hours: float,
) -> Optional[Dict[str, Any]]:
    """Devuelve la selección cacheada o None (miss / corrupto / vencido).

    Un archivo corrupto o con formato inesperado es un miss silencioso: el
    pipeline corre normal y el próximo guardado lo pisa.
    """
    path = cache_dir / f"{key}.json"
    if not path.is_file():
        return None
    try:
        if ttl_hours > 0:
            age_hours = (time.time() - path.stat().st_mtime) / 3600
            if age_hours > ttl_hours:
                return None
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or "selection" not in data:
            return None
        return data["selection"]
    except (json.JSONDecodeError, OSError, KeyError, TypeError):
        return None


def save_cached_selection(
    cache_dir: Path,
    key: str,
    selection: Dict[str, Any],
) -> None:
    """Persiste la selección de forma atómica (tmp + rename).

    El rename evita que un proceso que esté leyendo a mitad de escritura
    vea un JSON a medias. El directorio se crea si no existe.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{key}.json"
    tmp_path = cache_dir / f"{key}.json.tmp"
    tmp_path.write_text(
        json.dumps({"selection": selection}, ensure_ascii=False),
        encoding="utf-8",
    )
    tmp_path.replace(path)


def clear_selection_cache(cache_dir: Optional[Path] = None) -> None:
    """Elimina todas las entradas del cache (usado por /api/clear-index)."""
    directory = cache_dir or SELECTION_CACHE_DIR
    if not directory.exists():
        return
    for path in directory.glob("*.json"):
        try:
            path.unlink()
        except OSError:
            pass
    for path in directory.glob("*.json.tmp"):
        try:
            path.unlink()
        except OSError:
            pass
