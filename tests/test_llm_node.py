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


# ---------------------------------------------------------------------------
# P3.1: HyDE — _generate_hyde_query es defensiva por diseño (degrade a None).
# ---------------------------------------------------------------------------
def test_hyde_query_devuelve_texto_si_llm_ok(monkeypatch):
    from src.llm_node import _generate_hyde_query

    monkeypatch.setattr(
        "src.llm_node._call_llm",
        lambda *a, **k: {"hypothetical_document": "  CV hipotético del ideal  "},
    )
    assert (
        _generate_hyde_query("oferta", {"llm_provider": "ollama"})
        == "CV hipotético del ideal"
    )


def test_hyde_query_degrada_a_none_si_llm_falla(monkeypatch):
    from src.llm_node import _generate_hyde_query

    def llm_roto(*a, **k):
        raise RuntimeError("LLM caído")

    monkeypatch.setattr("src.llm_node._call_llm", llm_roto)
    assert _generate_hyde_query("oferta", {"llm_provider": "ollama"}) is None


def test_hyde_query_degrada_a_none_si_timeout(monkeypatch):
    from src.llm_node import _generate_hyde_query

    def llm_lento(*a, **k):
        import time

        time.sleep(2)
        return {"hypothetical_document": "tarde"}

    monkeypatch.setattr("src.llm_node._call_llm", llm_lento)
    assert _generate_hyde_query("oferta", {"llm_provider": "ollama"}, timeout=0.05) is None


def test_hyde_query_vacio_degrada_a_none(monkeypatch):
    from src.llm_node import _generate_hyde_query

    monkeypatch.setattr(
        "src.llm_node._call_llm",
        lambda *a, **k: {"hypothetical_document": "   "},
    )
    assert _generate_hyde_query("oferta", {"llm_provider": "ollama"}) is None


def test_use_hyde_invalida_fingerprint_de_seleccion():
    from src.config import DEFAULTS, _SELECTION_CONFIG_KEYS, selection_config_fingerprint

    base = {k: DEFAULTS[k] for k in _SELECTION_CONFIG_KEYS}
    assert selection_config_fingerprint({**base, "use_hyde": False}) != (
        selection_config_fingerprint({**base, "use_hyde": True})
    )


# ---------------------------------------------------------------------------
# P3.1: threading — use_hyde antepone el CV hipotético en el canal denso.
# ---------------------------------------------------------------------------
def _master_mini():
    return {
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


def test_select_con_use_hyde_antepone_query_hipotetica(
    monkeypatch, config, tmp_path
):
    import numpy as np

    from src.retrieval.store import IndexStore
    from src.selection import SelectionEngine

    class FakeDenseRecorder:
        def __init__(self):
            self.calls = []

        def encode(self, texts, **kwargs):
            self.calls.append(list(texts))
            return np.zeros((len(texts), 4))

    recorder = FakeDenseRecorder()
    engine = SelectionEngine(
        {**config, "use_reranker": False, "use_hyde": True},
        cache_dir=tmp_path / "sel_cache",
    )
    engine.store = IndexStore(tmp_path / "idx")
    engine._get_dense_model = lambda: recorder
    # El import es lazy dentro de select(); se parchea en llm_node.
    monkeypatch.setattr(
        "src.llm_node._generate_hyde_query",
        lambda jd, cfg: "CV hipotético del candidato ideal",
    )

    engine.select(_master_mini(), "Buscamos dev con python.")

    # La primera consulta del canal denso es la query HyDE (prefijo E5 query:).
    assert recorder.calls
    assert recorder.calls[0][0].startswith("query: CV hipotético del candidato ideal")


def test_select_sin_use_hyde_no_llama_al_llm(monkeypatch, config, tmp_path):
    import numpy as np

    from src.retrieval.store import IndexStore
    from src.selection import SelectionEngine

    class FakeDense:
        def encode(self, texts, **kwargs):
            return np.zeros((len(texts), 4))

    engine = SelectionEngine(
        {**config, "use_reranker": False, "use_hyde": False},
        cache_dir=tmp_path / "sel_cache",
    )
    engine.store = IndexStore(tmp_path / "idx")
    engine._get_dense_model = lambda: FakeDense()

    def no_debe_llamarse(*a, **k):
        raise AssertionError("use_hyde=False no debe generar query HyDE")

    monkeypatch.setattr("src.llm_node._generate_hyde_query", no_debe_llamarse)
    engine.select(_master_mini(), "Buscamos dev con python.")
