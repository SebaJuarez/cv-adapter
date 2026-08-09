"""Regresión de merge: keywords ATS verificadas, secciones custom
preservadas (M2), strip_internal_keys y validación de estructura."""
import yaml

from src.merge import (
    _build_verified_keywords,
    build_target_cv,
    strip_internal_keys,
    validate_master_cv_structure,
)
from src.render_node import save_yaml


# ---------------------------------------------------------------------------
# Invariante ATS: una keyword solo sobrevive si existe (o sinónima) en master
# Y en la oferta.
# ---------------------------------------------------------------------------
def test_verified_keywords_requieren_master_y_oferta(master_cv, config):
    candidatas = ["python", "php", "docker"]
    jd = "Buscamos python y docker."
    verificadas = _build_verified_keywords(master_cv, jd, candidatas, config["max_keywords"])
    assert verificadas == ["python", "docker"]


def test_verified_keywords_aceptan_variante_sinonima(master_cv, config):
    # master dice "postgresql", la oferta dice "postgres": misma keyword.
    verificadas = _build_verified_keywords(
        master_cv, "Buscamos expertos en postgres.", ["postgres"], config["max_keywords"]
    )
    assert verificadas == ["postgres"]


def test_verified_keywords_ignoran_no_strings_y_vacias(master_cv, config):
    assert _build_verified_keywords(master_cv, "python", ["", None, 42], 10) == []


def test_verified_keywords_respetan_max_keywords(master_cv, config):
    jd = "Buscamos python y docker."
    verificadas = _build_verified_keywords(master_cv, jd, ["python", "docker"], 1)
    assert len(verificadas) == 1


# ---------------------------------------------------------------------------
# M2: las secciones que el pipeline no maneja se preservan tal cual.
# ---------------------------------------------------------------------------
def test_build_target_cv_preserva_secciones_custom(master_cv, config, job_description):
    selection = {
        "selected_experience": [{"index": 0, "highlight_order": [0, 1], "match_reason": "x"}],
        "selected_projects": [{"index": 0, "highlight_order": [0], "match_reason": "x"}],
        "selected_skills_indices": [0],
        "summary_index": 0,
        "keywords_detected": ["python", "docker"],
    }
    target = build_target_cv(master_cv, selection, config, job_description=job_description)
    assert target["cv"]["sections"]["certifications"] == master_cv["cv"]["sections"]["certifications"]


def test_build_target_cv_linea_de_keywords_solo_con_verificadas(master_cv, config, job_description):
    selection = {
        "selected_experience": [{"index": 0, "highlight_order": [0], "match_reason": "x"}],
        "selected_projects": [],
        "selected_skills_indices": [],
        "summary_index": 0,
        "keywords_detected": ["python", "php"],  # php no está en la oferta
    }
    target = build_target_cv(master_cv, selection, config, job_description=job_description)
    assert target["cv"]["sections"]["keywords"] == ["Palabras clave: python"]


def test_build_target_cv_sin_keywords_no_genera_linea(master_cv, config, job_description):
    selection = {
        "selected_experience": [{"index": 0, "highlight_order": [0], "match_reason": "x"}],
        "selected_projects": [],
        "selected_skills_indices": [],
        "summary_index": 0,
        "keywords_detected": [],
    }
    target = build_target_cv(master_cv, selection, config, job_description=job_description)
    assert "keywords" not in target["cv"]["sections"]


def test_build_target_cv_summary_usa_indice_seleccionado(master_cv, config, job_description):
    selection = {
        "selected_experience": [],
        "selected_projects": [],
        "selected_skills_indices": [],
        "summary_index": 1,
        "keywords_detected": [],
    }
    target = build_target_cv(master_cv, selection, config, job_description=job_description)
    assert target["cv"]["sections"]["summary"] == [master_cv["cv"]["sections"]["summary"][1]]


def test_build_target_cv_summary_indice_invalido_cae_al_primero(master_cv, config, job_description):
    selection = {
        "selected_experience": [],
        "selected_projects": [],
        "selected_skills_indices": [],
        "summary_index": 999,
        "keywords_detected": [],
    }
    target = build_target_cv(master_cv, selection, config, job_description=job_description)
    assert target["cv"]["sections"]["summary"] == [master_cv["cv"]["sections"]["summary"][0]]


# ---------------------------------------------------------------------------
# Gotcha: claves internas del frontend fuera antes de guardar/renderizar.
# ---------------------------------------------------------------------------
def test_strip_internal_keys_quita_claves_con_guion_bajo():
    data = {
        "cv": {"sections": {"experience": [{"_src_section": "experience", "company": "X"}]}},
        "_src_index": 3,
        "normal": {"_a": 1, "b": 2},
    }
    limpio = strip_internal_keys(data)
    assert limpio == {"cv": {"sections": {"experience": [{"company": "X"}]}}, "normal": {"b": 2}}


def test_save_yaml_strippea_y_es_parseable(master_cv, config, job_description, tmp_path):
    selection = {
        "selected_experience": [{"index": 0, "highlight_order": [0, 1], "match_reason": "x"}],
        "selected_projects": [{"index": 0, "highlight_order": [0], "match_reason": "x"}],
        "selected_skills_indices": [0],
        "summary_index": 0,
        "keywords_detected": ["python"],
    }
    target = build_target_cv(master_cv, selection, config, job_description=job_description)
    target["cv"]["sections"]["experience"][0]["_src_section"] = "experience"
    target["cv"]["sections"]["experience"][0]["_src_index"] = 0

    path = tmp_path / "target.yaml"
    save_yaml(target, path)

    recargado = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert "_src_section" not in str(recargado)
    assert recargado["cv"]["sections"]["experience"][0]["company"] == "Empresa A"


# ---------------------------------------------------------------------------
# Gotcha YAML: un bullet con ": " sin comillas termina siendo un dict.
# ---------------------------------------------------------------------------
def test_validate_master_cv_structure_detecta_bullet_dict():
    roto = {
        "cv": {
            "sections": {
                "experience": [
                    {"company": "X", "highlights": [{"text": "esto: es un dict"}]}
                ]
            }
        }
    }
    errores = validate_master_cv_structure(roto)
    assert len(errores) == 1
    assert "highlights[0]" in errores[0]


def test_validate_master_cv_structure_master_valido_no_reporta(master_cv):
    assert validate_master_cv_structure(master_cv) == []
