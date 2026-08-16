"""Tests del servicio de generación (capa de aplicación).

Acá se prueba el wiring de generate_cv: que las manual_keywords del
payload entren al keyword_report (bug fix: antes solo llegaban a
build_target_cv, así que el ATS score inicial no las reflejaba). El
IR/LLM se mockea — el pipeline real está cubierto por test_selection.py
y test_llm_node.py.
"""
import pytest

from src.services.generation import generate_cv


@pytest.fixture
def selection_falsa():
    return {
        "selected_experience": [],
        "selected_projects": [],
        "selected_skills_indices": [],
        "selected_education_indices": [],
        "summary_index": 0,
        "keywords_detected": ["python", "docker"],
    }


@pytest.fixture
def pipeline_mockeado(monkeypatch, selection_falsa):
    monkeypatch.setattr(
        "src.services.generation.generate_selection",
        lambda *a, **k: selection_falsa,
    )
    monkeypatch.setattr(
        "src.services.generation.build_target_cv",
        lambda *a, **k: dict(a[0]),
    )


# ---------------------------------------------------------------------------
# Bug fix: manual_keywords del payload deben entrar al keyword_report que
# el frontend muestra justo al generar (ATS score inicial).
# ---------------------------------------------------------------------------
def test_generate_cv_report_incluye_manual_keywords(
    pipeline_mockeado, master_cv, job_description, config
):
    _, _, report_sin_manual, _ = generate_cv(
        master_cv, job_description, config=config
    )
    assert "zurbark" not in report_sin_manual["all_keywords"]

    _, _, report_con_manual, _ = generate_cv(
        master_cv, job_description, manual_keywords=["zurbark"], config=config
    )
    assert "zurbark" in report_con_manual["all_keywords"]


def test_generate_cv_report_combina_custom_y_manual(
    pipeline_mockeado, master_cv, job_description, config
):
    """Las fuentes de settings (custom_keywords) y payload (manual_keywords)
    se combinan sin pisarse."""
    config["custom_keywords"] = ["terraform"]

    _, _, report, _ = generate_cv(
        master_cv,
        job_description,
        manual_keywords=["zurbark"],
        config=config,
    )
    assert {"terraform", "zurbark"}.issubset(set(report["all_keywords"]))