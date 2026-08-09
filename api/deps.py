"""Rutas del filesystem compartidas por los routers de la API."""

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
MASTER_CV_PATH = BASE_DIR / "data" / "master_cv.yaml"
TARGET_CV_PATH = BASE_DIR / "target_cv.yaml"
OUTPUT_DIR = BASE_DIR / "output"
FRONTEND_DIR = BASE_DIR / "frontend"
RUNS_PATH = BASE_DIR / "data" / "run_history.json"
