"""Historial de corridas y seguimiento de aplicaciones.

Persiste cada generación de CV (desde la web) en `data/run_history.json` con la
metadata del análisis ATS (keywords detectadas, faltantes del master/target) y
el estado del seguimiento de la aplicación. Todo determinístico: el LLM no
participa acá. El historial es solo metadata — nunca toca el YAML del CV ni
propone agregar nada al master automáticamente.
"""

import hashlib
import json
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

BASE_DIR = Path(__file__).resolve().parent.parent
RUNS_PATH = BASE_DIR / "data" / "run_history.json"
# CV generado por corrida: un YAML por run, para previsualizar/borrar después.
RUN_CVS_DIR = BASE_DIR / "data" / "run_cvs"
OUTPUT_DIR = BASE_DIR / "output"

# Estados posibles del seguimiento de la aplicación.
VALID_STATUSES = ("pendiente", "aplicado", "entrevista", "oferta", "rechazado")
DEFAULT_STATUS = "pendiente"

# Estados que cuentan como "éxito" para las estadísticas de variantes:
# la corrida llegó a entrevista o mejor.
SUCCESS_STATUSES = ("entrevista", "oferta")

MAX_OFFER_TITLE_LEN = 80
FALLBACK_OFFER_TITLE = "Oferta sin título"

# Claves editables del run (las demás son datos de la corrida, inmutables).
# `pdf_path` lo actualiza el sistema al renderizar, pero también es editable
# manualmente por si el usuario movió el PDF — siempre validado para que
# quede dentro del directorio de output (ver update_run).
_EDITABLE_RUN_FIELDS = ("offer_title", "offer_link", "pdf_path")
_EDITABLE_APPLICATION_FIELDS = ("status", "applied_at", "notes")

# Prefijos típicos de reclutamiento que se descartan del título (sin LLM).
_TITLE_PREFIXES = sorted(
    (
        "estamos buscando",
        "estamos reclutando",
        "we are looking for",
        "we're looking for",
        "we are hiring",
        "we're hiring",
        "se busca",
        "se necesita",
        "buscamos",
        "necesitamos",
        "reclutamos",
        "contratamos",
        "looking for",
        "empresa líder busca",
        "job title",
        "vacante",
        "posicion",
        "posición",
        "puesto",
        "hiring",
    ),
    key=len,
    reverse=True,
)

# Separadores típicos entre título y empresa ("Backend | Acme", "Acme - Backend").
_TITLE_SPLIT_RE = re.compile(r"\s+(?:\||·|–|—|-)\s+")

# Artículos que pueden seguir a un prefijo ("Estamos buscando un Data Analyst").
_LEADING_ARTICLES = ("un", "una", "unos", "unas", "el", "la", "los", "las", "a", "an", "the", "al", "del")

# Última palabra que delata una razón social (no parte del título).
_COMPANY_LAST_WORDS = {
    "inc", "llc", "ltd", "company", "corporation", "corp", "group",
    "consulting", "solutions", "technologies", "technology", "sa", "srl",
    "gmbh", "ag", "plc", "co", "labs", "studio", "studios", "digital",
}

# Palabras/expresiones que no son parte del título (ubicación, modalidad, etc.).
_JUNK_TITLE_WORDS = {
    "remoto", "remota", "remote", "hibrido", "hibrida", "hybrid",
    "presencial", "onsite", "on-site", "full time", "full-time",
    "part time", "part-time", "buenos aires", "montevideo", "caba",
    "argentina", "uruguay", "mexico", "ciudad de mexico", "cdmx",
    "madrid", "barcelona", "santiago", "lima", "colombia", "chile",
    "peru", "españa", "usa", "united states", "europe", "latam",
    "latin america", "spanish", "ingles", "english",
}


def _strip_recruiter_prefix(line: str) -> str:
    """Saca prefijos tipo 'Buscamos ', 'Job title:', 'Hiring: '... y artículos
    que los sigan ('Estamos buscando un Data Analyst' -> 'Data Analyst')."""
    lower = line.lower()
    for prefix in _TITLE_PREFIXES:
        if not lower.startswith(prefix):
            continue
        rest = line[len(prefix):].strip(" :,;|–—-")
        words = rest.split()
        while words and words[0].lower() in _LEADING_ARTICLES:
            words = words[1:]
        return " ".join(words)
    return line


def _looks_like_company(segment: str) -> bool:
    lower = segment.strip(" .,").lower()
    words = lower.split()
    if not words:
        return False
    if len(words) >= 3 and words[-2:] == ["de", "cv"]:
        return True
    return words[-1] in _COMPANY_LAST_WORDS


def _looks_like_junk(segment: str) -> bool:
    lower = segment.strip(" .,").lower()
    return any(
        lower == junk or lower.endswith(" " + junk) or lower.endswith(", " + junk)
        for junk in _JUNK_TITLE_WORDS
    )


def _segment_score(segment: str) -> int:
    """Mayor = más probable que sea el título (heurística determinística)."""
    if _looks_like_company(segment) or _looks_like_junk(segment):
        return -1
    words = segment.split()
    score = len(words)
    if any(ch.isdigit() for ch in segment):
        score += 2
    score += sum(1 for w in words if w and w[0].isupper())
    return score


def _pick_title_segment(line: str) -> str:
    """Entre segmentos separados por ' | ', ' - ', etc., elige el más 'de título'.

    Si todos parecen empresa/ubicación, devuelve la línea original para no
    perder información.
    """
    parts = [p.strip() for p in _TITLE_SPLIT_RE.split(line) if p.strip()]
    if len(parts) <= 1:
        return line
    best = max(parts, key=_segment_score)
    return best if _segment_score(best) >= 0 else line


def extract_offer_title(job_description: str) -> str:
    """Título tentativo de la oferta: primera línea no vacía, limpiada.

    Heurística determinística (sin LLM): descarta prefijos de reclutamiento
    ('Buscamos…', 'Job title:…') y elige el segmento más 'de título' entre
    separadores comunes (|, -, –, ·, —). Si no hay nada aprovechable,
    devuelve un título de fallback.
    """
    for raw_line in job_description.splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip()
        if not line:
            continue
        line = _strip_recruiter_prefix(line)
        if not line:
            continue
        line = _pick_title_segment(line)
        if not line:
            continue
        return line[:MAX_OFFER_TITLE_LEN]
    return FALLBACK_OFFER_TITLE


def jd_hash(job_description: str) -> str:
    """Hash corto del texto de la oferta (8 hex). Identifica corridas con el
    mismo JD en el historial y forma parte de la clave del cache de
    selección (src/retrieval/selection_cache.py)."""
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
    variant_usage: Optional[Dict[str, int]] = None,
    bullet_variants: Optional[List[Dict[str, Any]]] = None,
    path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Crea y persiste un registro de corrida. Devuelve el run creado.

    `keyword_report` es el resultado de `build_keyword_report` (lo computa
    `src/services/generation.py`). `variant_usage` mapea `id` de
    variante a usos en este run; se aplica al guardar el máster
    (`POST /api/master-cv`) y el run se marca `variant_usage_applied`.

    `bullet_variants` es la traza por bullet de qué variante emitió el
    merge (`extract_bullet_variants`): se persiste para que el historial
    muestre qué redacción se usó en cada bullet y siga siendo legible aunque
    la variante después se marque deprecated o se borre del master.
    """
    runs = load_runs(path)
    jd_hash_value = jd_hash(job_description)
    existing_ids = {r["run_id"] for r in runs}
    while True:
        run_id = f"{int(time.time() * 1000)}-{jd_hash_value}-{uuid.uuid4().hex[:8]}"
        if run_id not in existing_ids:
            break
    run = {
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "offer_title": extract_offer_title(job_description),
        "offer_link": None,
        "jd_hash": jd_hash_value,
        "job_description": job_description,
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
    if variant_usage:
        # Solo se persiste si hay usos reales (los runs legacy no tienen clave).
        run["variant_usage"] = dict(variant_usage)
    if bullet_variants:
        # Igual que variant_usage: solo si hay traza real (runs legacy sin clave).
        run["bullet_variants"] = [dict(b) for b in bullet_variants]
    runs.append(run)
    save_runs(runs, path)
    return run


def _pdf_path_is_safe(pdf_path: Any, output_dir: Optional[Path]) -> bool:
    """True si el pdf_path dado cae dentro del directorio de output.

    None está permitido (run sin PDF asociado). Resuelve symlinks y
    normaliza `..` para que un directorio hermano (`output-old/`) no pase.
    """
    if pdf_path is None:
        return True
    try:
        target = Path(pdf_path).resolve()
        out = (output_dir or OUTPUT_DIR).resolve()
        return target.is_relative_to(out)
    except (OSError, ValueError, TypeError):
        return False


def update_run(
    run_id: str,
    fields: Dict[str, Any],
    path: Optional[Path] = None,
    output_dir: Optional[Path] = None,
) -> Optional[Dict[str, Any]]:
    """Edita los campos editables de un run (título, link, aplicación, PDF).

    Valida `application.status` contra `VALID_STATUSES` y que `pdf_path`
    caiga dentro del directorio de output (el historial nunca apunta a
    archivos arbitrarios del filesystem). Devuelve el run actualizado o
    None si no existe. No permite tocar datos de la corrida.
    """
    runs = load_runs(path)
    for run in runs:
        if run["run_id"] != run_id:
            continue
        for key in _EDITABLE_RUN_FIELDS:
            if key in fields:
                if key == "pdf_path" and not _pdf_path_is_safe(fields[key], output_dir):
                    raise ValueError("pdf_path debe estar dentro del directorio de output.")
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


def delete_run(
    run_id: str,
    path: Optional[Path] = None,
    delete_files: bool = False,
    cvs_dir: Optional[Path] = None,
    output_dir: Optional[Path] = None,
) -> bool:
    """Borra un run del historial. Devuelve True si existía.

    Con `delete_files=True` borra también el CV guardado (`data/run_cvs/`) y
    el PDF asociado (solo si está dentro del directorio de output, por
    seguridad). Por defecto solo se borra la metadata, nunca archivos.
    """
    runs = load_runs(path)
    remaining = [r for r in runs if r["run_id"] != run_id]
    if len(remaining) == len(runs):
        return False
    if delete_files:
        for run in runs:
            if run["run_id"] == run_id:
                _delete_run_files(run, cvs_dir=cvs_dir, output_dir=output_dir)
                break
    save_runs(remaining, path)
    return True


def _delete_run_files(
    run: Dict[str, Any],
    cvs_dir: Optional[Path] = None,
    output_dir: Optional[Path] = None,
) -> None:
    """Borra los artefactos de un run: CV guardado y PDF (si es nuestro)."""
    delete_run_cv(run["run_id"], cvs_dir=cvs_dir)
    pdf_path = run.get("pdf_path")
    if not pdf_path:
        return
    try:
        target = Path(pdf_path).resolve()
        out = (output_dir or OUTPUT_DIR).resolve()
        if target.is_relative_to(out) and target.is_file():
            target.unlink()
    except (OSError, ValueError):
        pass


def save_run_cv(run_id: str, cv_yaml: str, cvs_dir: Optional[Path] = None) -> Path:
    """Persiste el YAML del CV generado para un run (para previsualizarlo)."""
    directory = cvs_dir or RUN_CVS_DIR
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{run_id}.yaml"
    path.write_text(cv_yaml, encoding="utf-8")
    return path


def load_run_cv(run_id: str, cvs_dir: Optional[Path] = None) -> Optional[str]:
    """Devuelve el texto del CV guardado de un run, o None si no existe."""
    path = (cvs_dir or RUN_CVS_DIR) / f"{run_id}.yaml"
    if not path.is_file():
        return None
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def delete_run_cv(run_id: str, cvs_dir: Optional[Path] = None) -> bool:
    """Borra el CV guardado de un run. Devuelve True si existía."""
    path = (cvs_dir or RUN_CVS_DIR) / f"{run_id}.yaml"
    if not path.is_file():
        return False
    try:
        path.unlink()
        return True
    except OSError:
        return False


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


def aggregate_variant_stats(runs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Agrega qué variantes se usaron a través de las corridas.

    Por variante (clave `ach_id` + `variant_id` de la traza `bullet_variants`
    persistida por `add_run`): cuántas corridas distintas la usaron, cuántas
    de esas llegaron a `entrevista` o más (`SUCCESS_STATUSES`, el estado lo
    carga el usuario en el seguimiento de aplicación) y la última vez usada.

    Ordenadas por corridas desc, luego éxitos desc, luego texto alfabético.
    Los runs legacy (sin `bullet_variants`) no aportan nada y no rompen.
    """
    by_variant: Dict[tuple, Dict[str, Any]] = {}
    seen: set = set()

    for run in runs:
        run_id = run.get("run_id")
        success = (run.get("application") or {}).get("status") in SUCCESS_STATUSES
        created_at = run.get("created_at") or ""
        for bullet in run.get("bullet_variants") or []:
            ach_id = bullet.get("ach_id")
            variant_id = bullet.get("variant_id")
            if not variant_id:
                continue
            key = (ach_id, variant_id)
            if run_id and (run_id, key) in seen:
                continue
            if run_id:
                seen.add((run_id, key))
            entry = by_variant.setdefault(
                key,
                {
                    "ach_id": ach_id,
                    "variant_id": variant_id,
                    "angle": bullet.get("angle") or "",
                    "text": bullet.get("text") or "",
                    "runs": 0,
                    "successful_runs": 0,
                    "last_used": "",
                },
            )
            entry["runs"] += 1
            if success:
                entry["successful_runs"] += 1
            if created_at and created_at > entry["last_used"]:
                entry["last_used"] = created_at

    result = sorted(
        by_variant.values(),
        key=lambda e: (-e["runs"], -e["successful_runs"], e["text"]),
    )
    return result
