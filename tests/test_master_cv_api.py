"""Tests de API del CV maestro: guardado con achievements y
POST /api/master/extract-facts (enriquecer bullet)."""
import pytest
from fastapi.testclient import TestClient

from api.main import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    master_path = tmp_path / "master_cv.yaml"
    runs_path = tmp_path / "run_history.json"
    monkeypatch.setattr("api.deps.MASTER_CV_PATH", master_path)
    monkeypatch.setattr("api.routers.master_cv.MASTER_CV_PATH", master_path)
    # generate.py bindea MASTER_CV_PATH al importar (`from ..deps import ...`):
    # hay que parchear la copia del módulo, no solo la de deps.
    monkeypatch.setattr("api.routers.generate.MASTER_CV_PATH", master_path)
    monkeypatch.setattr("api.routers.master_cv.RUNS_PATH", runs_path)
    monkeypatch.setattr("api.routers.history.RUNS_PATH", runs_path)
    monkeypatch.setattr("api.deps.RUNS_PATH", runs_path)
    monkeypatch.setattr("api.routers.generate.RUNS_PATH", runs_path)
    return TestClient(app)


def _achievement_payload():
    return {
        "cv": {
            "name": "Test User",
            "sections": {
                "experience": [
                    {
                        "company": "Empresa A",
                        "achievements": [
                            {
                                "id": "ach_1",
                                "facts": {
                                    "action": "Diseñé un sistema de facturación",
                                    "tools": ["Java"],
                                    "scope": "",
                                    "outcomes": [],
                                },
                                "variants": [
                                    {
                                        "id": "var_1a",
                                        "text": "Diseñé un sistema de facturación en Java.",
                                        "angle": "impacto_tecnico",
                                        "status": "approved",
                                        "source": "manual",
                                        "used_count": 0,
                                    }
                                ],
                            }
                        ],
                    }
                ]
            },
        },
        "design": {"theme": "engineeringresumes"},
    }


# ---------------------------------------------------------------------------
# POST /api/master-cv: achievements sobreviven el round-trip completo
# ---------------------------------------------------------------------------
def test_master_cv_round_trip_con_achievements(client):
    respuesta = client.post("/api/master-cv", json=_achievement_payload())
    assert respuesta.status_code == 200
    assert respuesta.json() == {"ok": True, "variants_updated": 0}

    guardado = client.get("/api/master-cv").json()
    entry = guardado["cv"]["sections"]["experience"][0]
    assert entry["achievements"][0]["id"] == "ach_1"
    assert entry["achievements"][0]["variants"][0]["used_count"] == 0
    assert "highlights" not in entry


def test_master_cv_rechaza_highlights_y_achievements_juntos(client):
    payload = _achievement_payload()
    payload["cv"]["sections"]["experience"][0]["highlights"] = ["legacy"]
    respuesta = client.post("/api/master-cv", json=payload)
    assert respuesta.status_code == 400
    assert "a la vez" in respuesta.json()["detail"][0]


# ---------------------------------------------------------------------------
# POST /api/master/extract-facts
# ---------------------------------------------------------------------------
def test_extract_facts_devuelve_facts_del_llm(client, monkeypatch):
    def fake_extract(text, config):
        assert text == "Desarrollé un sistema de facturación en Java."
        return {
            "action": "Desarrollé un sistema de facturación en Java",
            "tools": ["Java"],
            "scope": "",
            "outcomes": [],
        }

    monkeypatch.setattr("api.routers.master_cv.extract_achievement_facts", fake_extract)
    respuesta = client.post(
        "/api/master/extract-facts", json={"text": "Desarrollé un sistema de facturación en Java."}
    )
    assert respuesta.status_code == 200
    assert respuesta.json() == {
        "facts": {
            "action": "Desarrollé un sistema de facturación en Java",
            "tools": ["Java"],
            "scope": "",
            "outcomes": [],
        }
    }


def test_extract_facts_texto_vacio_422(client, monkeypatch):
    def no_debe_llamarse(*a, **k):
        raise AssertionError("texto vacío no debe llamar al LLM")

    monkeypatch.setattr("api.routers.master_cv.extract_achievement_facts", no_debe_llamarse)
    respuesta = client.post("/api/master/extract-facts", json={"text": "   "})
    assert respuesta.status_code == 422
    assert "vacío" in respuesta.json()["detail"]


def test_extract_facts_degrada_con_facts_vacios(client, monkeypatch):
    # El LLM falla (proveedor caído): el endpoint sigue devolviendo 200 con
    # facts vacíos — el usuario los completa a mano, nunca se bloquea.
    def llm_roto(*a, **k):
        return {"action": "", "tools": [], "scope": "", "outcomes": []}

    monkeypatch.setattr("api.routers.master_cv.extract_achievement_facts", llm_roto)
    respuesta = client.post("/api/master/extract-facts", json={"text": "Hice cosas."})
    assert respuesta.status_code == 200
    assert respuesta.json() == {"facts": {"action": "", "tools": [], "scope": "", "outcomes": []}}


# ---------------------------------------------------------------------------
# used_count: el run registra las variantes emitidas y el guardado las aplica
# ---------------------------------------------------------------------------
def _fake_generate_cv(master_cv, job_description, manual_keywords=None, config=None, force=False):
    return (
        {"cv": {"name": "Test User", "sections": {}}},
        {"keywords_detected": []},
        {"ats_impact_score": 0, "all_keywords": [], "missing_in_target": [], "not_in_master": [], "frequencies": {}, "critical_missing": []},
        {"var_1a": 2},
    )


def test_generate_registra_variantes_usadas_en_el_run(client, monkeypatch):
    client.post("/api/master-cv", json=_achievement_payload())
    monkeypatch.setattr("api.routers.generate.generate_cv", _fake_generate_cv)
    respuesta = client.post("/api/generate", json={"job_description": "Buscamos devs."})
    assert respuesta.status_code == 200
    run_id = respuesta.json()["run_id"]
    runs = client.get("/api/history/runs").json()["runs"]
    run = next(r for r in runs if r["run_id"] == run_id)
    assert run["variant_usage"] == {"var_1a": 2}
    assert run.get("variant_usage_applied") is None


def test_save_master_aplica_usage_pendiente_y_marca_aplicado(client, monkeypatch):
    client.post("/api/master-cv", json=_achievement_payload())
    monkeypatch.setattr("api.routers.generate.generate_cv", _fake_generate_cv)
    client.post("/api/generate", json={"job_description": "Buscamos devs."})

    respuesta = client.post("/api/master-cv", json=_achievement_payload())
    assert respuesta.status_code == 200
    assert respuesta.json() == {"ok": True, "variants_updated": 1}

    guardado = client.get("/api/master-cv").json()
    entry = guardado["cv"]["sections"]["experience"][0]
    assert entry["achievements"][0]["variants"][0]["used_count"] == 2

    runs = client.get("/api/history/runs").json()["runs"]
    assert all(r.get("variant_usage_applied") is True for r in runs if r.get("variant_usage"))

    # Idempotencia: guardar de nuevo (con el master ya actualizado, como
    # haría el frontend tras recargar) no vuelve a sumar el mismo uso.
    respuesta2 = client.post("/api/master-cv", json=guardado)
    assert respuesta2.json() == {"ok": True, "variants_updated": 0}
    guardado2 = client.get("/api/master-cv").json()
    entry2 = guardado2["cv"]["sections"]["experience"][0]
    assert entry2["achievements"][0]["variants"][0]["used_count"] == 2


def test_save_master_ignora_usage_de_variante_borrada(client, monkeypatch):
    client.post("/api/master-cv", json=_achievement_payload())
    monkeypatch.setattr("api.routers.generate.generate_cv", _fake_generate_cv)
    client.post("/api/generate", json={"job_description": "Buscamos devs."})

    payload = _achievement_payload()
    payload["cv"]["sections"]["experience"][0]["achievements"][0]["variants"][0]["id"] = "var_renombrada"
    respuesta = client.post("/api/master-cv", json=payload)
    assert respuesta.status_code == 200
    assert respuesta.json() == {"ok": True, "variants_updated": 0}
    guardado = client.get("/api/master-cv").json()
    entry = guardado["cv"]["sections"]["experience"][0]
    assert entry["achievements"][0]["variants"][0]["used_count"] == 0