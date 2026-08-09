"""Tests de la API de historial (routers + hooks de generate/render).

Usan TestClient con el RUNS_PATH apuntando a un tmp_path para no ensuciar
`data/run_history.json`. El pipeline de generación se mockea: acá se prueba
el wiring de la API, no el IR/LLM (ya cubierto por otros tests).
"""
import pytest
from fastapi.testclient import TestClient

from api.main import app
from src import history as history_mod


@pytest.fixture
def client(tmp_path, monkeypatch):
    runs_path = tmp_path / "run_history.json"
    monkeypatch.setattr("api.deps.RUNS_PATH", runs_path)
    monkeypatch.setattr("api.routers.history.RUNS_PATH", runs_path)
    monkeypatch.setattr("api.routers.generate.RUNS_PATH", runs_path)
    monkeypatch.setattr("api.routers.render.RUNS_PATH", runs_path)
    return TestClient(app)


def _fake_generate_cv(master_cv, job_description, manual_keywords=None, config=None):
    from src.retrieval.keywords import build_keyword_report

    target_cv = dict(master_cv)
    report = build_keyword_report(master_cv, target_cv, job_description)
    selection = {
        "selected_experience": [],
        "selected_projects": [],
        "selected_skills_indices": [],
        "selected_education_indices": [],
        "summary_index": None,
        "keywords_detected": report["all_keywords"],
    }
    return target_cv, selection, report


class TestHistoryRuns:
    def test_lista_vacia(self, client):
        res = client.get("/api/history/runs")
        assert res.status_code == 200
        assert res.json() == {"runs": []}

    def test_patch_run_inexistente_404(self, client):
        res = client.patch("/api/history/runs/no-existe", json={"offer_title": "X"})
        assert res.status_code == 404

    def test_delete_run_inexistente_404(self, client):
        res = client.delete("/api/history/runs/no-existe")
        assert res.status_code == 404

    def test_stats_sin_corridas(self, client):
        res = client.get("/api/history/stats/keywords")
        assert res.status_code == 200
        assert res.json() == {"keywords": []}

    def test_flujo_completo_edicion_y_estadisticas(self, client, tmp_path):
        jd = "Backend Engineer (Terraform)\nRequisitos: terraform, aws."
        report = {
            "all_keywords": ["terraform", "aws"],
            "frequencies": {"terraform": 3, "aws": 1},
            "missing_in_target": [],
            "not_in_master": ["terraform", "aws"],
            "ats_impact_score": 50,
            "critical_missing": ["terraform"],
        }
        run = history_mod.add_run(
            jd, report, path=tmp_path / "run_history.json"
        )

        res = client.get("/api/history/runs")
        assert res.status_code == 200
        assert res.json()["runs"][0]["run_id"] == run["run_id"]

        res = client.patch(
            f"/api/history/runs/{run['run_id']}",
            json={
                "offer_title": "Sr. Backend",
                "application": {"status": "aplicado", "notes": "vía LinkedIn"},
            },
        )
        assert res.status_code == 200
        assert res.json()["run"]["application"]["status"] == "aplicado"

        res = client.patch(
            f"/api/history/runs/{run['run_id']}",
            json={"application": {"status": "ganado"}},
        )
        assert res.status_code == 400

        res = client.get("/api/history/stats/keywords")
        assert res.status_code == 200
        assert res.json()["keywords"][0]["keyword"] == "terraform"
        assert res.json()["keywords"][0]["count"] == 1

        res = client.delete(f"/api/history/runs/{run['run_id']}")
        assert res.status_code == 200
        assert client.get("/api/history/runs").json() == {"runs": []}


class TestGenerateHook:
    def test_generate_crea_run_y_devuelve_run_id(self, client, master_cv, monkeypatch):
        from api.routers import generate as generate_router

        monkeypatch.setattr(
            "api.routers.generate.generate_cv", _fake_generate_cv
        )
        monkeypatch.setattr(
            "api.routers.generate.load_master_cv", lambda _p: master_cv
        )

        jd = "Buscamos un backend developer con python y docker."
        res = client.post("/api/generate", json={"job_description": jd})
        assert res.status_code == 200
        body = res.json()
        assert body["run_id"]
        assert client.get("/api/history/runs").json()["runs"][0]["run_id"] == body["run_id"]

    def test_generate_sin_jd_400(self, client):
        res = client.post("/api/generate", json={"job_description": "   "})
        assert res.status_code == 400


class TestRenderHook:
    def test_render_actualiza_pdf_path_del_run(self, client, tmp_path, monkeypatch):
        from api.routers import render as render_router

        jd = "Backend Engineer (Terraform)"
        report = {
            "all_keywords": [],
            "frequencies": {},
            "missing_in_target": [],
            "not_in_master": [],
            "ats_impact_score": 100,
            "critical_missing": [],
        }
        run = history_mod.add_run(jd, report, path=tmp_path / "run_history.json")

        monkeypatch.setattr("api.routers.render.save_yaml", lambda _data, _path: None)
        monkeypatch.setattr(
            "api.routers.render.run_rendercv",
            lambda _src, _out: (True, "ok", "output/CV.pdf"),
        )

        payload = {"cv": {"name": "X", "sections": {}}, "run_id": run["run_id"]}
        res = client.post("/api/render", json=payload)
        assert res.status_code == 200
        updated = history_mod.load_runs(tmp_path / "run_history.json")[0]
        assert updated["pdf_path"] == "output/CV.pdf"

    def test_render_sin_run_id_no_rompe(self, client, monkeypatch):
        monkeypatch.setattr("api.routers.render.save_yaml", lambda _data, _path: None)
        monkeypatch.setattr(
            "api.routers.render.run_rendercv",
            lambda _src, _out: (True, "ok", "output/CV.pdf"),
        )
        payload = {"cv": {"name": "X", "sections": {}}}
        res = client.post("/api/render", json=payload)
        assert res.status_code == 200


class TestDownloadPdf:
    @pytest.fixture
    def output_dir(self, tmp_path, monkeypatch):
        out = tmp_path / "output"
        out.mkdir()
        monkeypatch.setattr("api.deps.OUTPUT_DIR", out)
        monkeypatch.setattr("api.routers.render.OUTPUT_DIR", out)
        return out

    def test_path_fuera_de_output_400(self, client, output_dir, tmp_path):
        pdf = tmp_path / "fuera.pdf"
        pdf.write_text("x", encoding="utf-8")
        res = client.get("/api/download-pdf", params={"path": str(pdf)})
        assert res.status_code == 400

    def test_pdf_inexistente_404(self, client, output_dir):
        pdf = output_dir / "no_existe.pdf"
        res = client.get("/api/download-pdf", params={"path": str(pdf)})
        assert res.status_code == 404

    def test_pdf_valido_200(self, client, output_dir):
        pdf = output_dir / "CV.pdf"
        pdf.write_text("x", encoding="utf-8")
        res = client.get("/api/download-pdf", params={"path": str(pdf)})
        assert res.status_code == 200
        assert res.content == b"x"
