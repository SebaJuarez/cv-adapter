"""Tests de API de configuración: validación de tipos/rangos en POST
/api/config (08)."""
import pytest
from fastapi.testclient import TestClient

from api.main import app
from src.config import DEFAULTS, load_config


@pytest.fixture
def client(tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    monkeypatch.setattr("src.config.CONFIG_PATH", config_path)
    return TestClient(app)


def _payload_valido():
    return {"max_experience_entries": 3, "use_stemming": False}


# ---------------------------------------------------------------------------
# 08: tipos y rangos inválidos -> 400 con mensaje claro en detail.
# ---------------------------------------------------------------------------
def test_config_rechaza_string_en_int(client):
    r = client.post("/api/config", json={"max_experience_entries": "hola"})
    assert r.status_code == 400
    assert "max_experience_entries" in r.json()["detail"]


def test_config_rechaza_entero_negativo(client):
    r = client.post("/api/config", json={"max_experience_entries": -5})
    assert r.status_code == 400
    assert "max_experience_entries" in r.json()["detail"]


def test_config_rechaza_bool_en_int(client):
    # En Python True es int: no debe colarse como entero válido.
    r = client.post("/api/config", json={"max_experience_entries": True})
    assert r.status_code == 400


def test_config_rechaza_bool_mal_escrito(client):
    r = client.post("/api/config", json={"use_stemming": "si"})
    assert r.status_code == 400
    assert "use_stemming" in r.json()["detail"]


def test_config_rechaza_proveedor_invalido(client):
    r = client.post("/api/config", json={"llm_provider": "gemini"})
    assert r.status_code == 400
    assert "llm_provider" in r.json()["detail"]


def test_config_rechaza_custom_keywords_no_lista(client):
    r = client.post("/api/config", json={"custom_keywords": "docker, k8s"})
    assert r.status_code == 400
    assert "custom_keywords" in r.json()["detail"]


def test_config_rechaza_modelo_vacio(client):
    r = client.post("/api/config", json={"openai_model": "  "})
    assert r.status_code == 400
    assert "openai_model" in r.json()["detail"]


def test_config_rechaza_peso_negativo(client):
    r = client.post("/api/config", json={"keyword_boost_weight": -1})
    assert r.status_code == 400
    assert "keyword_boost_weight" in r.json()["detail"]


def test_config_rechaza_lambda_fuera_de_rango(client):
    r = client.post("/api/config", json={"diversity_lambda": 1.5})
    assert r.status_code == 400
    assert "diversity_lambda" in r.json()["detail"]


def test_config_rechaza_clave_desconocida(client):
    r = client.post("/api/config", json={"clave_inexistente": 1})
    assert r.status_code == 400
    assert "desconocidas" in r.json()["detail"]


# ---------------------------------------------------------------------------
# 08: payload válido -> 200, normalizado y persistido.
# ---------------------------------------------------------------------------
def test_config_acepta_payload_valido(client):
    r = client.post("/api/config", json=_payload_valido())
    assert r.status_code == 200
    saved = load_config()
    assert saved["max_experience_entries"] == 3
    assert saved["use_stemming"] is False


def test_config_acepta_peso_cero_ignora_canal(client):
    r = client.post("/api/config", json={"sparse_weight": 0})
    assert r.status_code == 200
    assert load_config()["sparse_weight"] == 0


def test_config_normaliza_custom_keywords(client):
    r = client.post("/api/config", json={"custom_keywords": [" docker ", "", "k8s"]})
    assert r.status_code == 200
    assert load_config()["custom_keywords"] == ["docker", "k8s"]


def test_config_normaliza_strings_con_espacios(client):
    r = client.post("/api/config", json={"openai_model": "  gpt-4o-mini  "})
    assert r.status_code == 200
    assert load_config()["openai_model"] == "gpt-4o-mini"


def test_config_mergea_con_defaults_y_no_pierde_claves(client):
    r = client.post("/api/config", json=_payload_valido())
    assert r.status_code == 200
    saved = r.json()
    for key, default in DEFAULTS.items():
        assert key in saved