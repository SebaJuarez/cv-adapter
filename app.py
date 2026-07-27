"""Backend web local del editor de CV.

Corré con:
    uvicorn app:app --reload
y abrí http://127.0.0.1:8000 en el navegador.
"""

from pathlib import Path
from typing import Any, Dict, Optional

import yaml
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from src.config import DEFAULTS, load_config, save_config
from src.llm_node import generate_section_selection, generate_selection
from src.merge import (
    build_section_entries,
    build_target_cv,
    strip_internal_keys,
    validate_master_cv_structure,
)
from src.render_node import run_rendercv, save_yaml
from src.retrieval.keywords import build_keyword_report
from src.retrieval.store import IndexStore

BASE_DIR = Path(__file__).resolve().parent
MASTER_CV_PATH = BASE_DIR / "data" / "master_cv.yaml"
TARGET_CV_PATH = BASE_DIR / "target_cv.yaml"
OUTPUT_DIR = BASE_DIR / "output"
FRONTEND_DIR = BASE_DIR / "frontend"

app = FastAPI(title="cv-adapter")


class JobDescriptionIn(BaseModel):
    job_description: str
    manual_keywords: list[str] = []


class RegenerateSectionIn(BaseModel):
    job_description: str
    section_name: str


class CVDocumentIn(BaseModel):
    cv: Dict[str, Any]
    design: Optional[Dict[str, Any]] = None

    def as_dict(self) -> Dict[str, Any]:
        data = {"cv": self.cv}
        if self.design is not None:
            data["design"] = self.design
        return strip_internal_keys(data)


@app.get("/api/master-cv")
def get_master_cv() -> Dict[str, Any]:
    if not MASTER_CV_PATH.exists():
        return {
            "cv": {
                "name": "",
                "location": "",
                "email": "",
                "phone": "",
                "social_networks": [],
                "sections": {
                    "summary": [],
                    "experience": [],
                    "projects": [],
                    "skills": [],
                },
            },
            "design": {"theme": load_config()["rendercv_theme"]},
        }
    with open(MASTER_CV_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


@app.post("/api/master-cv")
def save_master_cv(payload: CVDocumentIn) -> Dict[str, Any]:
    data = payload.as_dict()
    errors = validate_master_cv_structure(data)
    if errors:
        raise HTTPException(status_code=400, detail=errors)
    save_yaml(data, MASTER_CV_PATH)
    return {"ok": True}


@app.get("/api/config")
def get_config() -> Dict[str, Any]:
    return load_config()


@app.post("/api/config")
def update_config(payload: Dict[str, Any]) -> Dict[str, Any]:
    unknown = set(payload) - set(DEFAULTS)
    if unknown:
        raise HTTPException(
            status_code=400, detail=f"Claves desconocidas: {sorted(unknown)}"
        )
    return save_config(payload)


@app.get("/api/health")
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


@app.post("/api/clear-index")
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


@app.post("/api/generate")
def generate(payload: JobDescriptionIn) -> Dict[str, Any]:
    if not MASTER_CV_PATH.exists():
        raise HTTPException(
            status_code=404,
            detail="Todavía no guardaste tu CV maestro. Completá la sección 'CV maestro' primero.",
        )
    if not payload.job_description.strip():
        raise HTTPException(
            status_code=400, detail="Pegá el texto de la oferta laboral."
        )

    with open(MASTER_CV_PATH, "r", encoding="utf-8") as f:
        master_cv = yaml.safe_load(f)

    config = load_config()
    try:
        selection = generate_selection(master_cv, payload.job_description, config)
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))

    target_cv = build_target_cv(
        master_cv,
        selection,
        config,
        job_description=payload.job_description,
        manual_keywords=payload.manual_keywords,
    )

    keyword_report = build_keyword_report(master_cv, target_cv, payload.job_description)

    return {
        "target_cv": target_cv,
        "selection": selection,
        "master_cv": master_cv,
        "keyword_report": keyword_report,
    }


@app.post("/api/regenerate-section")
def regenerate_section(payload: RegenerateSectionIn) -> Dict[str, Any]:
    if payload.section_name not in ("experience", "projects", "skills"):
        raise HTTPException(
            status_code=400, detail="Sección no soportada para regenerar."
        )
    if not MASTER_CV_PATH.exists():
        raise HTTPException(status_code=404, detail="No existe data/master_cv.yaml.")

    with open(MASTER_CV_PATH, "r", encoding="utf-8") as f:
        master_cv = yaml.safe_load(f)

    config = load_config()
    try:
        section_selection = generate_section_selection(
            master_cv, payload.job_description, payload.section_name, config
        )
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))

    entries = build_section_entries(
        master_cv, payload.section_name, section_selection, config
    )
    return {"entries": entries, "selection": section_selection}


@app.post("/api/render")
def render(payload: CVDocumentIn) -> Dict[str, Any]:
    data = payload.as_dict()
    config = load_config()
    data.setdefault("design", {})["theme"] = config["rendercv_theme"]

    errors = validate_master_cv_structure(data)
    if errors:
        raise HTTPException(status_code=400, detail=errors)

    save_yaml(data, TARGET_CV_PATH)
    ok, message, pdf_dir = run_rendercv(str(TARGET_CV_PATH), OUTPUT_DIR)
    if not ok:
        raise HTTPException(status_code=500, detail=message)
    return {"ok": True, "message": message, "output_dir": pdf_dir}


@app.get("/api/download-pdf")
def download_pdf() -> FileResponse:
    pdfs = list(OUTPUT_DIR.rglob("*.pdf"))
    if not pdfs:
        raise HTTPException(status_code=404, detail="Todavía no se generó ningún PDF.")
    latest = max(pdfs, key=lambda p: p.stat().st_mtime)
    return FileResponse(latest, media_type="application/pdf", filename=latest.name)


app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")