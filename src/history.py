"""Historial de corridas y seguimiento de aplicaciones.

Persiste cada generación de CV (web y CLI) en `data/run_history.json` con la
metadata del análisis ATS (keywords detectadas, faltantes del master/target) y
el estado del seguimiento de la aplicación. Todo determinístico: el LLM no
participa acá. El historial es solo metadata — nunca toca el YAML del CV ni
propone agregar nada al master automáticamente.
"""

import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .retrieval.keywords import build_keyword_report

BASE_DIR = Path(__file__).resolve().parent.parent
RUNS_PATH = BASE_DIR / "data" / "run_history.json"

# Estados posibles del seguimiento de la aplicación.
VALID_STATUSES = ("pendiente", "aplicado", "entrevista", "oferta", "rechazado")
DEFAULT_STATUS = "pendiente"

MAX_OFFER_TITLE_LEN = 80
FALLBACK_OFFER_TITLE = "Oferta sin título"

# Claves editables del run (las demás son datos de la corrida, inmutables).
_EDITABLE_RUN_FIELDS = ("offer_title", "offer_link")
_EDITABLE_APPLICATION_FIELDS = ("status", "applied_at", "notes")


def extract_offer_title(job_description: str) -> str:
    """Título tentativo de la oferta: primera línea no vacía, recortada.

    Heurística determinística (sin LLM). Si no hay nada aprovechable,
    devuelve un título de fallback.
    """
    for raw_line in job_description.splitlines():
        line = raw_line.strip()
        if line:
            return line[:MAX_OFFER_TITLE_LEN]
    return FALLBACK_OFFER_TITLE


def _jd_hash(job_description: str) -> str:
    return hashlib.sha1(job_description.encode("utf-8")).hexdigest()[:8]


def load_runs(path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Lee el historial desde disco.

    Si el archivo no existe devuelve []. Si está corrupto, lo respalda como
    `run_history.json.bak` y devuelve [] para no romper la app.
    """
    path = path or RUNS_PATH
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get("runs"), list):
            return data["runs"]
        return []
    except (json.JSONDecodeError, OSError):
        backup = path.with_suffix(path.suffix + ".bak")
        try:
            path.replace(backup)
        except OSError:
            pass
        return []


def save_runs(runs: List[Dict[str, Any]], path: Optional[Path] = None) -> None:
    """Persiste el historial. Las claves internas del frontend no aplican acá
    (JSON plano, nunca YAML de RenderCV)."""
    path = path or RUNS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"runs": runs}, f, ensure_ascii=False, indent=2)


def add_run(
    job_description: str,
    keyword_report: Dict[str, Any],
    selection: Optional[Dict[str, Any]] = None,
    pdf_path: Optional[str] = None,
    manual_keywords: Optional[List[str]] = None,
    path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Crea y persiste un registro de corrida. Devuelve el run creado.

    `keyword_report` es el resultado de `build_keyword_report` (la web ya lo
    computa; el CLI lo construye con `build_keyword_report` antes de llamar).
    """
    runs = load_runs(path)
    jd_hash = _jd_hash(job_description)
    run = {
        "run_id": f"{int(time.time() * 1000)}-{jd_hash}",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "offer_title": extract_offer_title(job_description),
        "offer_link": None,
        "jd_hash": jd_hash,
        "ats_score": keyword_report.get("ats_impact_score", 0),
        "keywords_detected": (
            (selection or {}).get("keywords_detected")
            or keyword_report.get("all_keywords")
            or []
        ),
        "missing_in_target": keyword_report.get("missing_in_target", []),
        "not_in_master": keyword_report.get("not_in_master", []),
        "not_in_master_frequencies": {
            kw: keyword_report.get("frequencies", {}).get(kw, 1)
            for kw in keyword_report.get("not_in_master", [])
        },
        "critical_missing": keyword_report.get("critical_missing", []),
        "manual_keywords": list(manual_keywords or []),
        "pdf_path": pdf_path,
        "application": {
            "status": DEFAULT_STATUS,
            "applied_at": None,
            "notes": "",
        },
    }
    runs.append(run)
    save_runs(runs, path)
    return run


def update_run(
    run_id: str,
    fields: Dict[str, Any],
    path: Optional[Path] = None,
) -> Optional[Dict[str, Any]]:
    """Edita los campos editables de un run (título, link, aplicación).

    Valida `application.status` contra `VALID_STATUSES`. Devuelve el run
    actualizado o None si no existe. No permite tocar datos de la corrida.
    """
    runs = load_runs(path)
    for run in runs:
        if run["run_id"] != run_id:
            continue
        for key in _EDITABLE_RUN_FIELDS:
            if key in fields:
                run[key] = fields[key]
        application = fields.get("application")
        if application is not None:
            if not isinstance(application, dict):
                raise ValueError("application debe ser un objeto.")
            status = application.get("status", run["application"]["status"])
            if status not in VALID_STATUSES:
                raise ValueError(
                    f"Estado inválido: {status!r}. Válidos: {', '.join(VALID_STATUSES)}."
                )
            for key in _EDITABLE_APPLICATION_FIELDS:
                if key in application:
                    run["application"][key] = application[key]
        save_runs(runs, path)
        return run
    return None


def delete_run(run_id: str, path: Optional[Path] = None) -> bool:
    """Borra un run del historial. Devuelve True si existía."""
    runs = load_runs(path)
    remaining = [r for r in runs if r["run_id"] != run_id]
    if len(remaining) == len(runs):
        return False
    save_runs(remaining, path)
    return True


def aggregate_missing_keywords(runs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Agrega las keywords ausentes del master a través de todas las corridas.

    Por keyword: cuántas ofertas la pidieron (`count`), primera/última vez
    vista, títulos de las ofertas, frecuencia acumulada y si alguna vez fue
    crítica (frecuencia >= 2 en una oferta). Ordenadas por `count` desc,
    luego frecuencia acumulada desc, luego alfabéticamente.
    """
    aggregated: Dict[str, Dict[str, Any]] = {}
    for run in runs:
        title = run.get("offer_title") or FALLBACK_OFFER_TITLE
        created_at = run.get("created_at") or ""
        for kw in run.get("not_in_master", []):
            entry = aggregated.setdefault(
                kw,
                {
                    "keyword": kw,
                    "count": 0,
                    "first_seen": created_at,
                    "last_seen": created_at,
                    "offer_titles": [],
                    "total_frequency": 0,
                    "ever_critical": False,
                },
            )
            entry["count"] += 1
            entry["offer_titles"].append(title)
            if created_at:
                if not entry["first_seen"] or created_at < entry["first_seen"]:
                    entry["first_seen"] = created_at
                if created_at > entry["last_seen"]:
                    entry["last_seen"] = created_at
            entry["total_frequency"] += run.get("not_in_master_frequencies", {}).get(kw, 1)
            if kw in run.get("critical_missing", []):
                entry["ever_critical"] = True

    result = sorted(
        aggregated.values(),
        key=lambda e: (-e["count"], -e["total_frequency"], e["keyword"]),
    )
    return result


def build_report_and_add_run(
    master_cv: Dict[str, Any],
    target_cv: Dict[str, Any],
    job_description: str,
    selection: Optional[Dict[str, Any]] = None,
    pdf_path: Optional[str] = None,
    manual_keywords: Optional[List[str]] = None,
    path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Conveniencia: computa el keyword_report y registra la corrida.

    Es el hook compartido por la web (que ya tiene master/target) y el CLI.
    """
    keyword_report = build_keyword_report(master_cv, target_cv, job_description)
    return add_run(
        job_description,
        keyword_report,
        selection=selection,
        pdf_path=pdf_path,
        manual_keywords=manual_keywords,
        path=path,
    )
