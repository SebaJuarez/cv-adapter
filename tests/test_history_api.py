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
    monkeypatch.setattr("src.history.RUN_CVS_DIR", tmp_path / "run_cvs")
    return TestClient(app)


def _fake_generate_cv(master_cv, job_description, manual_keywords=None, config=None, force=False):
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
    return target_cv, selection, report, {}


class TestHistoryRuns:
    def test_lista_vacia(self, client):
        res = client.get("/api/history/runs")
        assert res.status_code == 200
        body = res.json()
        assert body["runs"] == []
        assert body["total"] == 0
        assert body["status_counts"] == {}

    def test_patch_run_inexistente_404(self, client):
        res = client.patch("/api/history/runs/no-existe", json={"offer_title": "X"})
        assert res.status_code == 404

    def test_delete_run_inexistente_404(self, client):
        res = client.delete("/api/history/runs/no-existe")
        assert res.status_code == 404

    def test_get_run_inexistente_404(self, client):
        res = client.get("/api/history/runs/no-existe")
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
        body = client.get("/api/history/runs").json()
        assert body["runs"] == []
        assert body["total"] == 0


class TestListRunsFilters:
    def _add_run(self, title_line, path, status="pendiente"):
        report = {
            "all_keywords": [],
            "frequencies": {},
            "missing_in_target": [],
            "not_in_master": [],
            "ats_impact_score": 100,
            "critical_missing": [],
        }
        run = history_mod.add_run(title_line, report, path=path)
        if status != "pendiente":
            history_mod.update_run(
                run["run_id"], {"application": {"status": status}}, path=path
            )
        return run

    def test_filtro_por_texto(self, client, tmp_path):
        path = tmp_path / "run_history.json"
        self._add_run("Backend Engineer (Python)", path=path)
        self._add_run("Data Analyst (SQL)", path=path)

        res = client.get("/api/history/runs", params={"q": "backend"})
        body = res.json()
        assert body["total"] == 1
        assert body["runs"][0]["offer_title"] == "Backend Engineer (Python)"

    def test_filtro_por_rango_de_score(self, client, tmp_path):
        # P2.4: min_score/max_score filtran por ats_score (0-100).
        path = tmp_path / "run_history.json"
        self._add_run_con_score("Backend Engineer", 85, path=path)
        self._add_run_con_score("Data Analyst", 60, path=path)
        self._add_run_con_score("QA Engineer", 40, path=path)

        res = client.get("/api/history/runs", params={"min_score": 60})
        body = res.json()
        assert body["total"] == 2
        assert {r["offer_title"] for r in body["runs"]} == {
            "Backend Engineer", "Data Analyst",
        }

        res = client.get("/api/history/runs", params={"min_score": 50, "max_score": 70})
        body = res.json()
        assert body["total"] == 1
        assert body["runs"][0]["offer_title"] == "Data Analyst"

        # Los conteos de estado ignoran el filtro de score (mismos chips).
        res = client.get("/api/history/runs", params={"min_score": 80})
        assert res.json()["status_counts"] == {"pendiente": 3}

    def _add_run_con_score(self, title_line, score, path):
        report = {
            "all_keywords": [],
            "frequencies": {},
            "missing_in_target": [],
            "not_in_master": [],
            "ats_impact_score": score,
            "critical_missing": [],
        }
        return history_mod.add_run(title_line, report, path=path)

    def test_filtro_por_estado_y_status_counts(self, client, tmp_path):
        path = tmp_path / "run_history.json"
        self._add_run("Backend Engineer", status="aplicado", path=path)
        self._add_run("Data Analyst", status="entrevista", path=path)
        self._add_run("QA Engineer", status="aplicado", path=path)

        res = client.get("/api/history/runs")
        assert res.json()["status_counts"] == {"aplicado": 2, "entrevista": 1}

        res = client.get("/api/history/runs", params={"status": "aplicado"})
        body = res.json()
        assert body["total"] == 2
        assert all(r["application"]["status"] == "aplicado" for r in body["runs"])

    def test_paginacion(self, client, tmp_path):
        path = tmp_path / "run_history.json"
        for i in range(3):
            self._add_run(f"Oferta {i}", path=path)

        res = client.get("/api/history/runs", params={"limit": 2, "offset": 0})
        body = res.json()
        assert body["total"] == 3
        assert len(body["runs"]) == 2

        res = client.get("/api/history/runs", params={"limit": 2, "offset": 2})
        assert len(res.json()["runs"]) == 1


class TestRunDetail:
    def test_detalle_incluye_el_job_description(self, client, tmp_path):
        jd = "Buscamos un Backend Engineer\nRequisitos: python, docker."
        report = {
            "all_keywords": ["python"],
            "frequencies": {},
            "missing_in_target": [],
            "not_in_master": [],
            "ats_impact_score": 100,
            "critical_missing": [],
        }
        run = history_mod.add_run(jd, report, path=tmp_path / "run_history.json")

        # La lista no manda el JD (payload liviano), el detalle sí.
        listed = client.get("/api/history/runs").json()["runs"][0]
        assert "job_description" not in listed

        res = client.get(f"/api/history/runs/{run['run_id']}")
        assert res.status_code == 200
        assert res.json()["run"]["job_description"] == jd

    def test_cv_guardado_y_ausente(self, client, tmp_path):
        run = history_mod.add_run(
            "Oferta X",
            {
                "all_keywords": [],
                "frequencies": {},
                "missing_in_target": [],
                "not_in_master": [],
                "ats_impact_score": 100,
                "critical_missing": [],
            },
            path=tmp_path / "run_history.json",
        )

        res = client.get(f"/api/history/runs/{run['run_id']}/cv")
        assert res.status_code == 404

        history_mod.save_run_cv(run["run_id"], "name: X\nsections: {}\n")
        res = client.get(f"/api/history/runs/{run['run_id']}/cv")
        assert res.status_code == 200
        assert res.text == "name: X\nsections: {}\n"

    def test_cv_de_run_inexistente_404(self, client):
        res = client.get("/api/history/runs/no-existe/cv")
        assert res.status_code == 404


class TestDeleteWithFiles:
    def test_delete_files_1_llama_al_modulo_con_flag(self, client, tmp_path, monkeypatch):
        from src import history as history_mod

        run = history_mod.add_run(
            "Oferta X",
            {
                "all_keywords": [],
                "frequencies": {},
                "missing_in_target": [],
                "not_in_master": [],
                "ats_impact_score": 100,
                "critical_missing": [],
            },
            path=tmp_path / "run_history.json",
        )
        calls = []
        original = history_mod.delete_run

        def spy(run_id, path=None, delete_files=False, cvs_dir=None, output_dir=None):
            calls.append(delete_files)
            return original(run_id, path=path)

        monkeypatch.setattr(history_mod, "delete_run", spy)

        res = client.delete(
            f"/api/history/runs/{run['run_id']}", params={"delete_files": "1"}
        )
        assert res.status_code == 200
        assert calls == [True]

        res = client.delete(
            f"/api/history/runs/{run['run_id']}", params={"delete_files": "1"}
        )
        assert res.status_code == 404


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

        # P1.4: la respuesta incluye la estimación de página (aviso no bloqueante).
        assert isinstance(body["page_estimate"], dict)
        assert "estimated_lines" in body["page_estimate"]
        assert "page_budget_lines" in body["page_estimate"]
        assert isinstance(body["page_estimate"]["overflow"], bool)

    def test_generate_sin_jd_400(self, client):
        res = client.post("/api/generate", json={"job_description": "   "})
        assert res.status_code == 400


class TestPreviewKeywords:
    def test_preview_solo_extract_keywords_sin_pipeline(self, client, master_cv, monkeypatch):
        # P1.2: el preview es barato por diseño — nunca debe instanciar
        # SelectionEngine (eso cargaría los modelos de embeddings).
        from src.selection import SelectionEngine

        class _NuncaInstanciar:
            def __init__(self, *args, **kwargs):
                raise AssertionError(
                    "El preview de keywords no debe instanciar SelectionEngine"
                )

        monkeypatch.setattr("api.routers.generate.load_master_cv", lambda _p: master_cv)
        monkeypatch.setattr(SelectionEngine, "__init__", _NuncaInstanciar.__init__)

        jd = "Buscamos un backend developer con python y docker."
        res = client.post("/api/preview-keywords", json={"job_description": jd})
        assert res.status_code == 200
        body = res.json()
        assert isinstance(body["keywords_detected"], list)
        assert "python" in body["keywords_detected"]
        assert isinstance(body["in_master"], dict)
        assert body["in_master"].get("python") is True

    def test_preview_con_jd_corto_devuelve_vacio(self, client, master_cv, monkeypatch):
        monkeypatch.setattr("api.routers.generate.load_master_cv", lambda _p: master_cv)
        res = client.post("/api/preview-keywords", json={"job_description": "hola"})
        assert res.status_code == 200
        assert res.json()["keywords_detected"] == []

    def test_preview_incluye_custom_keywords_de_config_y_manuales(self, client, master_cv, monkeypatch):
        # Regresión: el preview en vivo solo pasaba payload.manual_keywords al
        # extractor y las fijas de Configuración (custom_keywords) solo
        # aparecían en /api/generate real — el preview no coincidía.
        monkeypatch.setattr("api.routers.generate.load_master_cv", lambda _p: master_cv)
        monkeypatch.setattr(
            "api.routers.generate.load_config",
            lambda: {"custom_keywords": ["zurbark"]},
        )
        jd = "Buscamos un backend developer con python y docker."
        res = client.post(
            "/api/preview-keywords",
            json={"job_description": jd, "manual_keywords": ["otra-manual"]},
        )
        assert res.status_code == 200
        body = res.json()
        assert "zurbark" in body["keywords_detected"]
        assert "otra-manual" in body["keywords_detected"]

    def test_preview_sin_master_404(self, client, monkeypatch):
        monkeypatch.setattr(
            "api.routers.generate.load_master_cv", lambda _p: None
        )
        res = client.post("/api/preview-keywords", json={"job_description": "python"})
        assert res.status_code == 404


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

    def test_inline_usa_content_disposition_inline(self, client, output_dir):
        pdf = output_dir / "CV.pdf"
        pdf.write_text("x", encoding="utf-8")
        res = client.get("/api/download-pdf", params={"path": str(pdf), "inline": "1"})
        assert res.status_code == 200
        assert "inline" in res.headers.get("content-disposition", "")

        res = client.get("/api/download-pdf", params={"path": str(pdf)})
        assert "attachment" in res.headers.get("content-disposition", "")

    def test_head_pdf_200(self, client, output_dir):
        # El frontend usa HEAD para saber si el PDF sigue existiendo sin
        # descargarlo (botón PDF y preview).
        pdf = output_dir / "CV.pdf"
        pdf.write_text("x", encoding="utf-8")
        res = client.head("/api/download-pdf", params={"path": str(pdf)})
        assert res.status_code == 200

        res = client.head("/api/download-pdf", params={"path": str(output_dir / "no.pdf")})
        assert res.status_code == 404
