"""Router de render: compilar el PDF con RenderCV y descargarlo."""

from typing import Any, Dict

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from src.config import load_config
from src.merge import validate_master_cv_structure
from src.render_node import run_rendercv, save_yaml

from ..deps import OUTPUT_DIR, TARGET_CV_PATH
from ..schemas import CVDocumentIn

router = APIRouter(tags=["render"])


@router.post("/api/render")
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


@router.get("/api/download-pdf")
def download_pdf() -> FileResponse:
    pdfs = list(OUTPUT_DIR.rglob("*.pdf"))
    if not pdfs:
        raise HTTPException(status_code=404, detail="Todavía no se generó ningún PDF.")
    latest = max(pdfs, key=lambda p: p.stat().st_mtime)
    return FileResponse(latest, media_type="application/pdf", filename=latest.name)
