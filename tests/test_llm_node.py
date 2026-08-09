"""Regresión del nodo LLM: guardarail anti-alucinación de match_reason,
degradación elegante si el LLM falla, y merge que solo permite al LLM
mejorar match_reasons (nunca sobreescribir summary_index/keywords)."""
import pytest

from src.llm_node import _verify_match_reason, generate_selection
from src.retrieval.store import IndexStore
from src.selection import SelectionEngine


@pytest.fixture
def engine_con_store_tmp(master_cv, config, tmp_path):
    """Motor con índices en tmp para los tests que corren generate_selection
    sin tocar data/retrieval_index (que está hasheado contra el master real)."""
    e = SelectionEngine(config)
    e.store = IndexStore(tmp_path / "idx")
    return e


# ---------------------------------------------------------------------------
# Guardarail anti-alucinación (_verify_match_reason)
# ---------------------------------------------------------------------------
def test_verify_match_reason_rechaza_tecnologia_inventada():
    bullet = "Desarrollé APIs REST con python y docker."
    jd = "Buscamos python y docker."
    assert not _verify_match_reason("Experiencia con kubernetes y terraform", bullet, jd)


def test_verify_match_reason_acepta_tecnologia_del_bullet():
    bullet = "Desarrollé APIs REST con python y docker."
    jd = "Buscamos python y docker."
    assert _verify_match_reason("Manejo de docker en producción", bullet, jd)


def test_verify_match_reason_acepta_sinonimo_del_jd():
    bullet = "Diseñé esquemas en postgresql."
    jd = "Buscamos expertos en postgres."
    assert _verify_match_reason("Modelé datos con postgres", bullet, jd)


def test_verify_match_reason_sin_tecnologia_pasa_siempre():
    bullet = "Mantuve pipelines de CI/CD."
    jd = "Buscamos un dev."
    assert _verify_match_reason("Gran experiencia en el rol", bullet, jd)


# ---------------------------------------------------------------------------
# Degradación elegante: si el LLM falla, queda la selección IR pura.
# ---------------------------------------------------------------------------
def test_generate_selection_degrada_si_llm_falla(
    monkeypatch, master_cv, job_description, config, engine_con_store_tmp
):
    def llm_roto(*args, **kwargs):
        raise RuntimeError("LLM caído")

    monkeypatch.setattr("src.llm_node._call_llm", llm_roto)
    monkeypatch.setattr(
        "src.llm_node.get_selection_engine", lambda cfg: engine_con_store_tmp
    )
    sel = generate_selection(master_cv, job_description, config)
    assert "selected_experience" in sel
    assert "keywords_detected" in sel
    assert sel["summary_index"] in (0, 1)


# ---------------------------------------------------------------------------
# Merge: el LLM solo puede mejorar match_reasons.
# ---------------------------------------------------------------------------
def test_generate_selection_aplica_match_reason_verificado(
    monkeypatch, master_cv, job_description, config, engine_con_store_tmp
):
    razon_llm = "Experiencia con python y docker"

    def llm_ok(*args, **kwargs):
        return {
            "selected_experience": [{"index": 0, "match_reason": razon_llm}],
            "selected_projects": [],
        }

    monkeypatch.setattr("src.llm_node._call_llm", llm_ok)
    monkeypatch.setattr(
        "src.llm_node.get_selection_engine", lambda cfg: engine_con_store_tmp
    )
    sel = generate_selection(master_cv, job_description, config)
    razones = {item["index"]: item["match_reason"] for item in sel["selected_experience"]}
    assert razones[0] == razon_llm


def test_generate_selection_descarta_match_reason_alucinado(
    monkeypatch, master_cv, job_description, config, engine_con_store_tmp
):
    razon_alucinada = "Experiencia con kubernetes"  # ni bullet ni JD la mencionan

    def llm_miente(*args, **kwargs):
        return {
            "selected_experience": [{"index": 0, "match_reason": razon_alucinada}],
            "selected_projects": [],
        }

    monkeypatch.setattr("src.llm_node._call_llm", llm_miente)
    monkeypatch.setattr(
        "src.llm_node.get_selection_engine", lambda cfg: engine_con_store_tmp
    )
    sel = generate_selection(master_cv, job_description, config)
    razones = {item["index"]: item["match_reason"] for item in sel["selected_experience"]}
    assert razones[0] != razon_alucinada


def test_generate_selection_llm_no_puede_tocar_summary_ni_keywords(
    monkeypatch, master_cv, job_description, config, engine_con_store_tmp
):
    def llm_saboteador(*args, **kwargs):
        return {"summary_index": 999, "keywords_detected": ["php"]}

    monkeypatch.setattr("src.llm_node._call_llm", llm_saboteador)
    monkeypatch.setattr(
        "src.llm_node.get_selection_engine", lambda cfg: engine_con_store_tmp
    )
    sel = generate_selection(master_cv, job_description, config)
    assert sel["summary_index"] != 999
    assert "php" not in sel["keywords_detected"]
