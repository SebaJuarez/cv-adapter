"""Backend web local del editor de CV.

Corré con:
    uvicorn app:app --reload
y abrí http://127.0.0.1:8000 en el navegador.

No agrega lógica nueva de negocio: reusa exactamente las mismas funciones
que el pipeline CLI (main.py) — generate_selection, build_target_cv,
run_rendercv, save_yaml — así que las garantías anti-alucinación y el
presupuesto de una página son idénticos, uses la web o la consola.
"""
from pathlib import Path
from typing import Any, Dict, Optional

import yaml
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from src.config import DEFAULTS, load_config, save_config
from src.llm_node import generate_selection
from src.merge import build_target_cv, strip_internal_keys, validate_master_cv_structure
from src.render_node import run_rendercv, save_yaml

BASE_DIR = Path(__file__).resolve().parent
MASTER_CV_PATH = BASE_DIR / "data" / "master_cv.yaml"
TARGET_CV_PATH = BASE_DIR / "target_cv.yaml"
OUTPUT_DIR = BASE_DIR / "output"
FRONTEND_DIR = BASE_DIR / "frontend"

app = FastAPI(title="cv-adapter")


class JobDescriptionIn(BaseModel):
    job_description: str


class CVDocumentIn(BaseModel):
    cv: Dict[str, Any]
    design: Optional[Dict[str, Any]] = None

    def as_dict(self) -> Dict[str, Any]:
        data = {"cv": self.cv}
        if self.design is not None:
            data["design"] = self.design
        return strip_internal_keys(data)


# ---------------------------------------------------------------- master CV

@app.get("/api/master-cv")
def get_master_cv() -> Dict[str, Any]:
    if not MASTER_CV_PATH.exists():
        # Devolvemos un esqueleto vacío en vez de 404: la UI arranca desde
        # cero sin que el usuario tenga que crear el archivo a mano.
        return {
            "cv": {
                "name": "",
                "location": "",
                "email": "",
                "phone": "",
                "social_networks": [],
                "sections": {"summary": [], "experience": [], "projects": [], "skills": []},
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


# ------------------------------------------------------------------- config

@app.get("/api/config")
def get_config() -> Dict[str, Any]:
    return load_config()


@app.post("/api/config")
def update_config(payload: Dict[str, Any]) -> Dict[str, Any]:
    unknown = set(payload) - set(DEFAULTS)
    if unknown:
        raise HTTPException(status_code=400, detail=f"Claves desconocidas: {sorted(unknown)}")
    return save_config(payload)


# --------------------------------------------------------- generar / render

@app.post("/api/generate")
def generate(payload: JobDescriptionIn) -> Dict[str, Any]:
    if not MASTER_CV_PATH.exists():
        raise HTTPException(
            status_code=404,
            detail="Todavía no guardaste tu CV maestro. Completá la sección 'CV maestro' primero.",
        )
    if not payload.job_description.strip():
        raise HTTPException(status_code=400, detail="Pegá el texto de la oferta laboral.")

    with open(MASTER_CV_PATH, "r", encoding="utf-8") as f:
        master_cv = yaml.safe_load(f)

    config = load_config()
    try:
        selection = generate_selection(master_cv, payload.job_description, config)
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))

    target_cv = build_target_cv(master_cv, selection, config)
    return {"target_cv": target_cv, "selection": selection, "master_cv": master_cv}


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


# --------------------------------------------------------------- frontend

# Va al final: es un mount "catch-all" en "/", tiene que registrarse
# después de las rutas /api/* para no taparlas.
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")