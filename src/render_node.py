"""Nodos LangGraph para:
  1. Guardar target_cv.yaml en disco (fin del tramo automático).
  2. Pausar y pedir confirmación humana por consola (safety gate).
  3. Ejecutar RenderCV para compilar el PDF final, con manejo de errores.
"""
import subprocess
import sys
from pathlib import Path

import yaml

from .state import CVState


def save_target_cv_node(state: CVState) -> CVState:
    """Escribe target_cv.yaml a disco. Justo después de este nodo el grafo
    corta en un edge condicional y espera la confirmación humana."""
    if state.get("error"):
        return state

    target_path = Path(state.get("target_cv_path") or "target_cv.yaml")
    target_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with open(target_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(
                state["target_cv_dict"],
                f,
                allow_unicode=True,
                sort_keys=False,
                default_flow_style=False,
            )
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
    """Edge condicional: decide si el grafo sigue a 'render' o corta en END."""
    return "render" if state.get("approved") else "end"


def render_pdf_node(state: CVState) -> CVState:
    """Ejecuta `rendercv render target_cv.yaml`. Si el YAML quedó mal
    formado o RenderCV no está instalado, se captura y reporta el error
    sin tirar abajo el proceso completo."""
    target_path = state["target_cv_path"]
    output_dir = Path("output")
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        result = subprocess.run(
            [
                sys.executable, "-m", "rendercv", "render",
                target_path,
                "--output-folder", str(output_dir),
            ],
            capture_output=True,
            text=True,
            timeout=180,
            check=True,
        )
        print(result.stdout)
        state["output_pdf_path"] = str(output_dir)
        state["error"] = None

    except subprocess.CalledProcessError as e:
        state["error"] = (
            "RenderCV falló al compilar el YAML (probablemente quedó mal "
            f"formado o no cumple el schema esperado).\n"
            f"--- STDOUT ---\n{e.stdout}\n--- STDERR ---\n{e.stderr}"
        )
        state["output_pdf_path"] = None

    except subprocess.TimeoutExpired:
        state["error"] = "RenderCV tardó demasiado en compilar (timeout de 180s)."
        state["output_pdf_path"] = None

    except FileNotFoundError:
        state["error"] = (
            "No se encontró el comando 'rendercv'. ¿Está instalado en este "
            "entorno? Corré: pip install rendercv"
        )
        state["output_pdf_path"] = None

    return state
