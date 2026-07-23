"""Guardar YAML, pausa humana (CLI) y ejecutar RenderCV.

`save_yaml()` y `run_rendercv()` son funciones "peladas" (sin LangGraph),
reutilizadas tanto por los nodos del grafo (CLI) como por el endpoint
/api/render de la app web.
"""
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional, Tuple

import yaml

from .merge import strip_internal_keys
from .state import CVState


def save_yaml(data: dict, path: Path) -> None:
    """Escribe un dict como YAML de forma segura (comillas donde hacen
    falta, sin las cuales ': ' dentro de un bullet rompe el parseo — ver
    validate_master_cv_structure en merge.py). Saca cualquier metadata
    interna ('_src_section', etc.) antes de guardar, porque RenderCV
    rechaza claves que no reconoce."""
    path.parent.mkdir(parents=True, exist_ok=True)
    clean_data = strip_internal_keys(data)
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(clean_data, f, allow_unicode=True, sort_keys=False, default_flow_style=False)


def run_rendercv(target_path: str, output_dir: Path) -> Tuple[bool, str, Optional[str]]:
    """Ejecuta `rendercv render target_path`. Devuelve (éxito, mensaje, pdf_path).

    Nota Windows: en algunas consolas (cp1252), la librería `rich` que usa
    RenderCV para imprimir el panel de éxito final puede tirar un
    UnicodeEncodeError al intentar escribir un tilde (✓), AUNQUE el PDF ya
    se haya generado correctamente. Por eso: (a) forzamos UTF-8/sin color
    en el subproceso, y (b) igual verificamos si el PDF quedó en disco
    antes de reportar error, como red de seguridad.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["NO_COLOR"] = "1"
    env["TERM"] = "dumb"

    def _pdf_was_generated() -> Optional[Path]:
        pdfs = list(output_dir.rglob("*.pdf"))
        return max(pdfs, key=lambda p: p.stat().st_mtime) if pdfs else None

    try:
        result = subprocess.run(
            [sys.executable, "-m", "rendercv", "render", target_path,
             "--output-folder", str(output_dir)],
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
            check=True,
            env=env,
        )
        return True, result.stdout, str(output_dir)

    except subprocess.CalledProcessError as e:
        generated_pdf = _pdf_was_generated()
        if generated_pdf:
            return True, (
                "RenderCV tiró un error al imprimir su mensaje final (probablemente "
                "un problema de encoding de consola en Windows), pero el PDF SÍ se "
                f"generó: {generated_pdf}"
            ), str(output_dir)
        return False, (
            "RenderCV falló al compilar el YAML (probablemente quedó mal formado o "
            f"no cumple el schema esperado).\n--- STDOUT ---\n{e.stdout}\n"
            f"--- STDERR ---\n{e.stderr}"
        ), None

    except subprocess.TimeoutExpired:
        return False, "RenderCV tardó demasiado en compilar (timeout de 180s).", None

    except FileNotFoundError:
        return False, (
            "No se encontró el comando 'rendercv'. ¿Está instalado en este entorno? "
            'Corré: pip install "rendercv[full]"'
        ), None


# ---- Wrappers para el grafo LangGraph (usados por main.py / CLI) ----

def save_target_cv_node(state: CVState) -> CVState:
    if state.get("error"):
        return state
    target_path = Path(state.get("target_cv_path") or "target_cv.yaml")
    try:
        save_yaml(state["target_cv_dict"], target_path)
    except yaml.YAMLError as e:
        state["error"] = f"No se pudo serializar target_cv.yaml: {e}"
        return state
    state["target_cv_path"] = str(target_path)
    return state


def human_review_node(state: CVState) -> CVState:
    """Pausa de seguridad: el humano revisa target_cv.yaml antes de gastar
    tiempo de CPU compilando un PDF potencialmente con alucinaciones."""
    if state.get("error"):
        print(f"\n⚠️  Hubo un error antes de llegar a esta etapa: {state['error']}")
        state["approved"] = False
        return state

    print("\n" + "=" * 60)
    print(f"✅ Revisá el archivo generado: {state['target_cv_path']}")
    print("   Confirmá que ninguna fecha, empresa o puesto fue alterado.")
    print("=" * 60)
    answer = input("¿Deseás generar el PDF con RenderCV? (y/n): ").strip().lower()
    state["approved"] = answer in ("y", "yes", "s", "si", "sí")
    return state


def route_after_review(state: CVState) -> str:
    return "render" if state.get("approved") else "end"


def render_pdf_node(state: CVState) -> CVState:
    ok, message, pdf_path = run_rendercv(state["target_cv_path"], Path("output"))
    if ok:
        print(message)
        state["output_pdf_path"] = pdf_path
        state["error"] = None
    else:
        state["error"] = message
        state["output_pdf_path"] = None
    return state