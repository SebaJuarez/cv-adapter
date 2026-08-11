"""Tests del onboarding conversacional (F4): structurize_achievement y
POST /api/onboarding/structurize.

Invariante de la fase: el endpoint solo devuelve el candidato; nada entra
al master sin confirmación del usuario (eso lo hace POST /api/master-cv,
ya cubierto en test_master_cv_api.py).
"""
import pytest
from fastapi.testclient import TestClient

from api.main import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    master_path = tmp_path / "master_cv.yaml"
    runs_path = tmp_path / "run_history.json"
    monkeypatch.setattr("api.deps.MASTER_CV_PATH", master_path)
    monkeypatch.setattr("api.routers.master_cv.MASTER_CV_PATH", master_path)
    monkeypatch.setattr("api.routers.master_cv.RUNS_PATH", runs_path)
    monkeypatch.setattr("api.routers.history.RUNS_PATH", runs_path)
    monkeypatch.setattr("api.deps.RUNS_PATH", runs_path)
    monkeypatch.setattr("api.routers.generate.RUNS_PATH", runs_path)
    return TestClient(app)


# ---------------------------------------------------------------------------
# structurize_achievement

def test_structurize_usa_el_llm_y_verifica_facts(monkeypatch, config):
    """Con el LLM ok, los facts se verifican contra el relato y la variante
    es la que redactó el modelo."""
    from src.onboarding import structurize_achievement

    def llm_ok(system_prompt, user_prompt, schema, cfg):
        assert "relato" in user_prompt
        assert set(schema["required"]) == {"facts", "variant_text"}
        return {
            "facts": {
                "action": "Desarrollé el backend de una app de delivery",
                "tools": ["Python", "Frambuesa"],  # Frambuesa NO está en el relato
                "scope": "app de delivery",
                "outcomes": [{"metric": "tiempo", "value": "40%"}, {"metric": "inventado", "value": "99"}],
            },
            "variant_text": "Desarrollé el backend de una app de delivery en Python.",
        }

    monkeypatch.setattr("src.onboarding._call_llm", llm_ok)
    candidate = structurize_achievement(
        {
            "work": "Desarrollé el backend de una app de delivery",
            "tools": "Python",
            "outcomes": "reduje el tiempo de respuesta un 40%",
        },
        config,
    )
    assert candidate["facts"]["action"] == "Desarrollé el backend de una app de delivery"
    # Solo lo verificable sobrevive: "Frambuesa" se descarta; "40%" está en el relato.
    assert candidate["facts"]["tools"] == ["Python"]
    assert candidate["facts"]["outcomes"][0] == {"metric": "tiempo", "value": "40%"}
    assert len(candidate["facts"]["outcomes"]) == 1
    assert candidate["variant_text"] == "Desarrollé el backend de una app de delivery en Python."


def test_structurize_degrada_con_llm_roto(monkeypatch, config):
    """Si el proveedor falla, el candidato crudo conserva el relato: nada
    se pierde y nada se inventa."""
    from src.onboarding import structurize_achievement

    def llm_roto(*args, **kwargs):
        raise RuntimeError("proveedor caído")

    monkeypatch.setattr("src.onboarding._call_llm", llm_roto)
    candidate = structurize_achievement(
        {"work": "Hice mantenimiento de servidores", "tools": "Linux", "outcomes": ""},
        config,
    )
    assert candidate["facts"]["action"] == "Hice mantenimiento de servidores"
    assert candidate["facts"]["tools"] == []
    assert "mantenimiento de servidores" in candidate["variant_text"]
    assert "Linux" in candidate["variant_text"]


def test_structurize_sin_work_devuelve_candidato_crudo(config):
    from src.onboarding import structurize_achievement

    candidate = structurize_achievement({"work": "", "tools": "", "outcomes": ""}, config)
    assert candidate["facts"]["action"] == ""
    assert candidate["variant_text"] == ""


def test_structurize_variante_vacia_cae_al_relato(monkeypatch, config):
    """Si el LLM devuelve la variante vacía, el relato original es el
    candidato de redacción — el chat nunca entrega una tarjeta en blanco."""
    from src.onboarding import structurize_achievement

    def llm_vacio(system_prompt, user_prompt, schema, cfg):
        return {"facts": {"action": "Diseñé una red", "tools": [], "scope": "", "outcomes": []}, "variant_text": "   "}

    monkeypatch.setattr("src.onboarding._call_llm", llm_vacio)
    candidate = structurize_achievement(
        {"work": "Diseñé una red", "tools": "Cisco", "outcomes": ""}, config
    )
    assert candidate["variant_text"] == "Diseñé una red Cisco"


# ---------------------------------------------------------------------------
# POST /api/onboarding/structurize

def test_endpoint_devuelve_candidato(client, monkeypatch):
    from src.onboarding import structurize_achievement

    def llm_ok(system_prompt, user_prompt, schema, cfg):
        return {
            "facts": {"action": "Diseñé un bot", "tools": ["Python"], "scope": "", "outcomes": []},
            "variant_text": "Diseñé un bot en Python.",
        }

    monkeypatch.setattr("src.onboarding._call_llm", llm_ok)
    resp = client.post("/api/onboarding/structurize", json={
        "work": "Diseñé un bot", "tools": "Python", "outcomes": "",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["facts"]["action"] == "Diseñé un bot"
    assert data["variant_text"] == "Diseñé un bot en Python."


def test_endpoint_rechaza_work_vacio(client, monkeypatch):
    resp = client.post("/api/onboarding/structurize", json={
        "work": "   ", "tools": "", "outcomes": "",
    })
    assert resp.status_code == 422


def test_endpoint_degrada_si_el_llm_falla(client, monkeypatch):
    def llm_roto(*args, **kwargs):
        raise RuntimeError("proveedor caído")

    monkeypatch.setattr("src.onboarding._call_llm", llm_roto)
    resp = client.post("/api/onboarding/structurize", json={
        "work": "Armé una landing", "tools": "", "outcomes": "",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["facts"]["action"] == "Armé una landing"
    assert data["variant_text"] == "Armé una landing"
