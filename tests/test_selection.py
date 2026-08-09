"""Regresión de selection: keywords_detected poblado (C1), hash del
singleton (M3) y smoke test del motor IR con índices en tmp (sin ensuciar
data/retrieval_index)."""
import pytest

from src.retrieval.store import IndexStore
from src.selection import SelectionEngine, get_selection_engine


@pytest.fixture
def engine(master_cv, config, tmp_path):
    """Motor con store propio en tmp_path (los índices del master sintético
    no deben pisar los índices reales de data/retrieval_index)."""
    e = SelectionEngine(config)
    e.store = IndexStore(tmp_path / "idx")
    return e


def test_select_poblado_keywords_detected(engine, master_cv, job_description):
    sel = engine.select(master_cv, job_description)
    assert isinstance(sel["keywords_detected"], list)
    assert "python" in sel["keywords_detected"]
    assert "docker" in sel["keywords_detected"]
    # Ninguna keyword puede venir de afuera de la oferta
    for kw in sel["keywords_detected"]:
        assert kw in job_description.lower()


def test_select_summary_index_deterministico(engine, master_cv, job_description):
    s1 = engine.select(master_cv, job_description)
    s2 = engine.select(master_cv, job_description)
    assert s1["summary_index"] == s2["summary_index"]
    assert s1["summary_index_mode"] in (
        "cross_encoder", "positional_fallback", "single_option", "none",
    )
    assert s1["summary_index"] in (0, 1)


def test_select_indices_validos(engine, master_cv, job_description):
    sel = engine.select(master_cv, job_description)
    master_exp = master_cv["cv"]["sections"]["experience"]
    for item in sel["selected_experience"]:
        assert 0 <= item["index"] < len(master_exp)
        assert all(0 <= h < len(master_exp[item["index"]]["highlights"]) for h in item["highlight_order"])


def test_select_sin_llm_no_depende_de_red(engine, master_cv, job_description):
    sel = engine.select(master_cv, job_description)
    assert "summary_index" in sel
    assert isinstance(sel.get("bullet_scores"), dict)


# ---------------------------------------------------------------------------
# M3: el hash del singleton incluye diversity_lambda y keyword_boost_weight.
# ---------------------------------------------------------------------------
def test_singleton_reutiliza_con_misma_config(config):
    e1 = get_selection_engine(config)
    e2 = get_selection_engine(config)
    assert e1 is e2


def test_singleton_nuevo_si_cambia_diversity_lambda(config):
    e1 = get_selection_engine(config)
    e2 = get_selection_engine({**config, "diversity_lambda": 0.2})
    assert e1 is not e2


def test_singleton_nuevo_si_cambia_keyword_boost_weight(config):
    e1 = get_selection_engine(config)
    e2 = get_selection_engine({**config, "keyword_boost_weight": 0.9})
    assert e1 is not e2


def test_singleton_reutiliza_si_cambia_clave_irrelevante(config):
    e1 = get_selection_engine(config)
    e2 = get_selection_engine({**config, "ollama_model": "otro-modelo"})
    assert e1 is e2
