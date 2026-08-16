"""Regresión del cache de selección por hash de JD.

El cache evita recalcular embeddings + cross-encoder cuando se regenera la
misma oferta. Acá se prueba que: (a) el hit devuelve el mismo resultado sin
volver a correr el reranker, (b) cambiar config relevante o el master
invalida la entrada, (c) force saltea el cache, y (d) un archivo corrupto
es un miss silencioso (nunca rompe el pipeline).
"""
import json
import time

import pytest

from src.retrieval.selection_cache import (
    get_cache_key,
    load_cached_selection,
    save_cached_selection,
)
from src.retrieval.store import IndexStore
from src.selection import SelectionEngine


@pytest.fixture
def engine(master_cv, config, tmp_path):
    """Motor con store e índice propios en tmp_path (nunca toca los
    datos reales de data/retrieval_index ni data/selection_cache)."""
    e = SelectionEngine(config, cache_dir=tmp_path / "sel_cache")
    e.store = IndexStore(tmp_path / "idx")
    return e


class CountingReranker:
    """Fake del cross-encoder que cuenta las llamadas a rerank.

    Sirve para verificar que un cache hit NO vuelve a correr el paso caro:
    si se llamó al reranker cero veces en la segunda select(), el cache
    funcionó. `total_calls` acumula TODAS las llamadas (summary + secciones).
    """

    def __init__(self):
        self.total_calls = 0

    def rerank(self, query, candidates, top_k=30):
        self.total_calls += 1
        # Devolver el orden original como score decreciente: irrelevante
        # para el test (solo interesa cuántas veces se llama).
        n = len(candidates)
        return [(c["id"], (n - i) / n) for i, c in enumerate(candidates)]


def _with_counting_reranker(engine, monkeypatch):
    reranker = CountingReranker()
    monkeypatch.setattr(engine, "_get_reranker", lambda: reranker)
    return reranker


# ---------------------------------------------------------------------------
# Hit: dos llamadas con el mismo JD/config deben devolver el mismo resultado
# y NO volver a llamar al reranker la segunda vez.
# ---------------------------------------------------------------------------
def test_select_usa_cache_si_mismo_jd_y_config(
    engine, master_cv, job_description, monkeypatch
):
    reranker = _with_counting_reranker(engine, monkeypatch)

    s1 = engine.select(master_cv, job_description)
    calls_after_first = reranker.total_calls
    assert calls_after_first > 0  # el primer cómputo sí corrió el reranker

    s2 = engine.select(master_cv, job_description)
    assert s2 == s1
    assert reranker.total_calls == calls_after_first  # hit: no recalculó


def test_select_section_usa_cache_si_mismo_jd_y_config(
    engine, master_cv, job_description, monkeypatch
):
    reranker = _with_counting_reranker(engine, monkeypatch)

    engine.select_section(master_cv, job_description, "experience")
    calls_after_first = reranker.total_calls

    engine.select_section(master_cv, job_description, "experience")
    assert reranker.total_calls == calls_after_first

    # Una sección DISTINTA no puede tener hit con la clave de la otra:
    # la sección forma parte de la clave del cache.
    engine.select_section(master_cv, job_description, "projects")
    assert reranker.total_calls > calls_after_first


# ---------------------------------------------------------------------------
# Invalidación: la clave incluye la config de retrieval y el master, así que
# cambiar cualquiera de los dos fuerza un miss (y por lo tanto el reranker
# vuelve a correr).
# ---------------------------------------------------------------------------
def test_select_invalida_cache_si_cambia_config_relevante(
    engine, master_cv, job_description, monkeypatch
):
    reranker = _with_counting_reranker(engine, monkeypatch)

    engine.select(master_cv, job_description)
    calls_after_first = reranker.total_calls

    other = SelectionEngine(
        {**engine.config, "rrf_k": 30}, cache_dir=engine.cache_dir
    )
    other.store = engine.store
    monkeypatch.setattr(other, "_get_reranker", lambda: reranker)
    other.select(master_cv, job_description)

    assert reranker.total_calls > calls_after_first


def test_select_invalida_cache_si_cambia_master(
    engine, master_cv, job_description, monkeypatch
):
    reranker = _with_counting_reranker(engine, monkeypatch)

    engine.select(master_cv, job_description)
    calls_after_first = reranker.total_calls

    otro_master = json.loads(json.dumps(master_cv))
    otro_master["cv"]["name"] = "Otro Candidato"
    engine.select(otro_master, job_description)

    assert reranker.total_calls > calls_after_first


# ---------------------------------------------------------------------------
# Force: use_cache=False saltea el cache aunque exista un hit válido.
# ---------------------------------------------------------------------------
def test_force_regeneracion_ignora_cache(
    engine, master_cv, job_description, monkeypatch
):
    reranker = _with_counting_reranker(engine, monkeypatch)

    engine.select(master_cv, job_description)
    calls_after_first = reranker.total_calls

    engine.select(master_cv, job_description, use_cache=False)
    assert reranker.total_calls > calls_after_first


# ---------------------------------------------------------------------------
# Defensa: un archivo de cache corrupto (JSON inválido, o un dict sin la
# clave "selection") es un miss silencioso — jamás un error del pipeline.
# ---------------------------------------------------------------------------
def test_cache_corrupto_trata_miss(engine, master_cv, job_description, monkeypatch):
    import json as json_mod

    from src.history import jd_hash

    master_json = json_mod.dumps(master_cv, ensure_ascii=False, sort_keys=True)
    key = get_cache_key(job_description, master_json, engine.config)
    engine.cache_dir.mkdir(parents=True, exist_ok=True)
    (engine.cache_dir / f"{key}.json").write_text("esto no es json {", encoding="utf-8")

    reranker = _with_counting_reranker(engine, monkeypatch)
    sel = engine.select(master_cv, job_description)
    assert reranker.total_calls > 0  # corrió normal, trató el cache como miss
    assert "summary_index" in sel


def test_cache_vencido_trata_miss(tmp_path):
    key = "clave-test"
    save_cached_selection(tmp_path, key, {"summary_index": 0})
    path = tmp_path / f"{key}.json"
    # Envejecer el archivo más allá del TTL: el miss no depende del reloj
    # del test, se fuerza mtime viejo directamente.
    old = time.time() - 25 * 3600
    import os

    os.utime(path, (old, old))
    assert load_cached_selection(tmp_path, key, ttl_hours=24) is None
    assert load_cached_selection(tmp_path, key, ttl_hours=0) == {"summary_index": 0}


def test_cache_guardado_se_lee_igual(tmp_path):
    key = "clave-test"
    sel = {"summary_index": 1, "selected_experience": []}
    save_cached_selection(tmp_path, key, sel)
    assert load_cached_selection(tmp_path, key, ttl_hours=24) == sel


def test_get_cache_key_distingue_secciones(tmp_path, config):
    master_json = "{}"
    full = get_cache_key("jd", master_json, config, section="")
    exp = get_cache_key("jd", master_json, config, section="experience")
    proj = get_cache_key("jd", master_json, config, section="projects")
    assert full != exp != proj
    assert get_cache_key("jd", master_json, config, "experience") == exp
    assert get_cache_key("jd", master_json, config, "experience") != get_cache_key(
        "jd-otro", master_json, config, "experience"
    )
