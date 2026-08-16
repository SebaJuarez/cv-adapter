"""Tests del router de generación asistida de variantes:

el endpoint recibe los hechos desde el frontend (no replica el master),
valida datos mínimos (422: ángulo desconocido no vacío, sin contenido),
propaga el fallo del proveedor como 502 con detalle legible y devuelve el
texto + términos no verificados. El ángulo vacío es válido y genera una
versión "genérica" (sin ángulo).
"""
import pytest
from fastapi.testclient import TestClient

from api.main import app


@pytest.fixture
def client():
    return TestClient(app)


def _payload(**over):
    base = {
        "angle": "escala",
        "facts": {
            "action": "Desarrollé APIs REST con python y docker.",
            "tools": ["python", "docker"],
            "scope": "",
            "outcomes": [],
        },
        "variant_texts": [],
        "current_text": "Desarrollé APIs REST con python y docker.",
        "jd_snippet": "",
    }
    base.update(over)
    return base


def test_genera_variante_200(monkeypatch, client):
    recibido = {}

    def fake_generate(angle, facts, variant_texts, current_text, jd_snippet, config):
        recibido["angle"] = angle
        recibido["facts"] = facts
        return {"text": "Escalé las APIs REST a producción.", "unverified_terms": []}

    monkeypatch.setattr("api.routers.variants.generate_variant_text", fake_generate)
    res = client.post("/api/variants/generate", json=_payload())
    assert res.status_code == 200
    body = res.json()
    assert body["text"] == "Escalé las APIs REST a producción."
    assert body["unverified_terms"] == []
    assert recibido["angle"] == "escala"
    assert recibido["facts"]["tools"] == ["python", "docker"]


def test_proveedor_caido_502_con_detalle(monkeypatch, client):
    def llm_roto(*args, **kwargs):
        raise RuntimeError("Ollama no responde")

    monkeypatch.setattr("api.routers.variants.generate_variant_text", llm_roto)
    res = client.post("/api/variants/generate", json=_payload())
    assert res.status_code == 502
    assert "Ollama no responde" in res.json()["detail"]


def test_angulo_vacio_genera_genérica(monkeypatch, client):
    recibido = {}

    def fake_generate(angle, facts, variant_texts, current_text, jd_snippet, config):
        recibido["angle"] = angle
        return {"text": "Redacción genérica.", "unverified_terms": []}

    monkeypatch.setattr("api.routers.variants.generate_variant_text", fake_generate)
    res = client.post(
        "/api/variants/generate",
        json=_payload(angle="  "),
    )
    assert res.status_code == 200
    assert recibido["angle"] == ""


def test_angulo_desconocido_422(client):
    res = client.post(
        "/api/variants/generate",
        json=_payload(angle="cualquiera"),
    )
    assert res.status_code == 422
    assert "Ángulo desconocido" in res.json()["detail"]
    assert "escala" in res.json()["detail"]


def test_sin_contenido_422(client):
    res = client.post(
        "/api/variants/generate",
        json={"angle": "escala", "facts": {}, "variant_texts": [], "current_text": "  "},
    )
    assert res.status_code == 422
    assert "no tiene contenido" in res.json()["detail"]


def test_falta_angle_en_schema_422(client):
    res = client.post("/api/variants/generate", json={"current_text": "algo"})
    assert res.status_code == 422