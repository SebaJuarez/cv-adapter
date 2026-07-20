"""Punto de entrada del pipeline.

Uso:
    python main.py --master data/master_cv.yaml --job data/job_description.txt

Requiere Ollama corriendo en local (`ollama serve`) con el modelo
descargado (`ollama pull llama3:8b`).
"""
import argparse
from pathlib import Path

import yaml
from langgraph.graph import END, StateGraph

from src.llm_node import generate_selection_node
from src.merge import build_target_cv
from src.render_node import (
    human_review_node,
    render_pdf_node,
    route_after_review,
    save_target_cv_node,
)
from src.state import CVState


def load_inputs_node(state: CVState) -> CVState:
    master_path = Path(state["master_cv_path"])
    jd_path = Path(state["job_description_path"])

    if not master_path.exists():
        state["error"] = f"No existe el archivo: {master_path}"
        return state
    if not jd_path.exists():
        state["error"] = f"No existe el archivo: {jd_path}"
        return state

    try:
        with open(master_path, "r", encoding="utf-8") as f:
            state["master_cv_raw"] = yaml.safe_load(f)
    except yaml.YAMLError as e:
        state["error"] = f"master_cv.yaml mal formado: {e}"
        return state

    with open(jd_path, "r", encoding="utf-8") as f:
        state["job_description"] = f.read()

    state["error"] = None
    return state


def merge_node(state: CVState) -> CVState:
    if state.get("error"):
        return state
    state["target_cv_dict"] = build_target_cv(
        state["master_cv_raw"], state["llm_selection"]
    )
    return state


def build_graph():
    graph = StateGraph(CVState)

    graph.add_node("load_inputs", load_inputs_node)
    graph.add_node("llm_selection", generate_selection_node)
    graph.add_node("merge", merge_node)
    graph.add_node("save_target", save_target_cv_node)
    graph.add_node("human_review", human_review_node)
    graph.add_node("render", render_pdf_node)

    graph.set_entry_point("load_inputs")
    graph.add_edge("load_inputs", "llm_selection")
    graph.add_edge("llm_selection", "merge")
    graph.add_edge("merge", "save_target")
    graph.add_edge("save_target", "human_review")
    graph.add_conditional_edges(
        "human_review",
        route_after_review,
        {"render": "render", "end": END},
    )
    graph.add_edge("render", END)

    return graph.compile()


def main():
    parser = argparse.ArgumentParser(
        description="Adaptador de CV local: LangGraph + Ollama + RenderCV (costo $0, 100% local)."
    )
    parser.add_argument("--master", default="data/master_cv.yaml", help="Path al CV maestro (YAML)")
    parser.add_argument("--job", default="data/job_description.txt", help="Path a la descripción del puesto")
    parser.add_argument("--target-out", default="target_cv.yaml", help="Path de salida del CV filtrado")
    args = parser.parse_args()

    app = build_graph()

    initial_state: CVState = {
        "master_cv_path": args.master,
        "job_description_path": args.job,
        "target_cv_path": args.target_out,
    }

    final_state = app.invoke(initial_state)

    if final_state.get("error"):
        print(f"\n❌ El pipeline terminó con un error: {final_state['error']}")
        return

    if final_state.get("output_pdf_path"):
        print(f"\n🎉 PDF generado correctamente en: {final_state['output_pdf_path']}")
    else:
        print("\n🛑 Proceso cancelado por vos en la revisión humana. No se generó ningún PDF.")


if __name__ == "__main__":
    main()
