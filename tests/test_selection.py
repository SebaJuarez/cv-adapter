"""Regresión de selection: keywords_detected poblado (C1), hash del
singleton (M3) y smoke test del motor IR con índices en tmp (sin ensuciar
data/retrieval_index)."""
import pytest

from src.retrieval.store import IndexStore
from src.selection import SelectionEngine, get_selection_engine


@pytest.fixture
def engine(master_cv, config, tmp_path):
    """Motor con store propio en tmp_path (los índices del master sintético
    no deben pisar los índices reales de data/retrieval_index ni el cache
    de selección de data/selection_cache)."""
    e = SelectionEngine(config, cache_dir=tmp_path / "sel_cache")
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


def test_singleton_nuevo_si_cambia_use_stemming(config):
    e1 = get_selection_engine(config)
    e2 = get_selection_engine({**config, "use_stemming": False})
    assert e1 is not e2


def test_singleton_reutiliza_si_cambia_clave_irrelevante(config):
    e1 = get_selection_engine(config)
    e2 = get_selection_engine({**config, "ollama_model": "otro-modelo"})
    assert e1 is e2


# ---------------------------------------------------------------------------
# P0.2: penalización de términos negados del JD ("no se requiere X").
# Mismo JD y motor salvo negation_penalty (0.3 vs 1.0 = desactivado): la
# base de retrieval es idéntica, así que la comparación es exacta. El canal
# denso se excluye (dense_weight=0.0) y el reranker se apaga para no
# descargar modelos reales.
# ---------------------------------------------------------------------------
def test_select_penaliza_bullet_de_termino_negado(config, tmp_path):
    import numpy as np

    master = {
        "cv": {
            "name": "Test User",
            "sections": {
                "experience": [
                    {
                        "company": "Empresa A",
                        "position": "Backend Developer",
                        "start_date": "2021-01",
                        "end_date": "2024-12",
                        "highlights": [
                            "Brindé soporte técnico a clientes.",
                            "Desarrollé APIs REST en python.",
                            "Mantuve pipelines de CI/CD.",
                        ],
                    }
                ],
                "skills": [],
                "projects": [],
                "education": [],
            },
        },
        "design": {"theme": "engineeringresumes"},
    }
    jd = (
        "Buscamos dev con APIs REST en python y CI/CD. "
        "No se requiere experiencia en soporte técnico ni en frontend."
    )
    jd_sin_negacion = "Buscamos dev con APIs REST en python y CI/CD."

    class FakeDense:
        def encode(self, texts, **kwargs):
            return np.zeros((len(texts), 4))

    def build_engine(penalty, tag):
        e = SelectionEngine(
            {
                **config,
                "use_reranker": False,
                "dense_weight": 0.0,
                "negation_penalty": penalty,
            },
            cache_dir=tmp_path / f"sel_cache_{tag}",
        )
        e.store = IndexStore(tmp_path / f"idx_{tag}")
        e._get_dense_model = lambda: FakeDense()
        return e

    base = build_engine(1.0, "base")
    penalizado = build_engine(0.3, "pen")

    sel_base = base.select(master, jd)
    sel_pen = penalizado.select(master, jd)

    soporte_id = "experience_0_bullet_0"
    ci_id = "experience_0_bullet_2"

    # El término negado se detecta y se reporta en ambas selecciones.
    assert "soporte técnico" in sel_base["negated_terms"]
    assert "soporte técnico" in sel_pen["negated_terms"]
    # El bullet que NO matchea términos negados queda idéntico (la base de
    # retrieval es la misma; la penalización es selectiva por bullet).
    assert sel_pen["bullet_scores"][ci_id] == sel_base["bullet_scores"][ci_id]
    # El bullet de soporte técnico se multiplica por negation_penalty.
    assert sel_pen["bullet_scores"][soporte_id] == round(
        sel_base["bullet_scores"][soporte_id] * 0.3, 3
    )
    assert sel_pen["bullet_scores"][soporte_id] < sel_base["bullet_scores"][soporte_id]

    # Control: sin cláusula de negación, el penalty no cambia nada.
    sel_pen_pos = penalizado.select(master, jd_sin_negacion)
    sel_base_pos = base.select(master, jd_sin_negacion)
    assert sel_pen_pos["negated_terms"] == []
    assert (
        sel_pen_pos["bullet_scores"][soporte_id]
        == sel_base_pos["bullet_scores"][soporte_id]
    )
