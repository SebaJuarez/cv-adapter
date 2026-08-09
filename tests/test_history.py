"""Tests del historial de corridas y seguimiento de aplicaciones.

Cubren las invariantes de la feature (AGENTS.md): el historial es metadata
determinística (sin LLM, sin tocar el YAML del CV), tolerante a archivos
ausentes/corruptos, y la agregación de keywords faltantes del master es
estable y ordenada.
"""
import json

import pytest

from src.history import (
    FALLBACK_OFFER_TITLE,
    MAX_OFFER_TITLE_LEN,
    VALID_STATUSES,
    add_run,
    aggregate_missing_keywords,
    build_report_and_add_run,
    delete_run,
    extract_offer_title,
    load_runs,
    save_runs,
    update_run,
)


@pytest.fixture
def history_path(tmp_path):
    return tmp_path / "run_history.json"


@pytest.fixture
def keyword_report():
    """Reporte ATS de una oferta que pide terraform y aws (no en el master)."""
    return {
        "all_keywords": ["python", "docker", "terraform", "aws"],
        "frequencies": {"python": 2, "docker": 1, "terraform": 3, "aws": 1},
        "in_master": {"python": True, "docker": True, "terraform": False, "aws": False},
        "in_target": {"python": True, "docker": True, "terraform": False, "aws": False},
        "missing_in_target": ["kubernetes"],
        "not_in_master": ["terraform", "aws"],
        "ats_impact_score": 72,
        "critical_missing": ["terraform"],
    }


@pytest.fixture
def jd():
    return "Backend Engineer (Terraform)\nRequisitos: terraform, aws.\n"


class TestExtractOfferTitle:
    def test_primera_linea_no_vacia(self):
        assert extract_offer_title("   \nBackend Engineer\nDetalles...") == "Backend Engineer"

    def test_trunca_a_max_len(self):
        long_title = "x" * (MAX_OFFER_TITLE_LEN + 50)
        assert len(extract_offer_title(long_title)) == MAX_OFFER_TITLE_LEN

    def test_vacio_devuelve_fallback(self):
        assert extract_offer_title("   \n\t\n") == FALLBACK_OFFER_TITLE
        assert extract_offer_title("") == FALLBACK_OFFER_TITLE


class TestLoadSaveRuns:
    def test_archivo_ausente_devuelve_vacio(self, history_path):
        assert load_runs(history_path) == []

    def test_roundtrip(self, history_path):
        runs = [{"run_id": "1", "offer_title": "X"}]
        save_runs(runs, history_path)
        assert load_runs(history_path) == runs

    def test_archivo_corrupto_se_respalda(self, history_path):
        history_path.write_text("{esto no es json", encoding="utf-8")
        assert load_runs(history_path) == []
        assert history_path.with_suffix(".json.bak").exists()

    def test_estructura_invalida_devuelve_vacio(self, history_path):
        history_path.write_text(json.dumps({"runs": "no-es-una-lista"}), encoding="utf-8")
        assert load_runs(history_path) == []


class TestAddRun:
    def test_crea_registro_completo(self, history_path, jd, keyword_report):
        run = add_run(jd, keyword_report, manual_keywords=["scrum"], path=history_path)

        assert run["offer_title"] == "Backend Engineer (Terraform)"
        assert run["ats_score"] == 72
        assert run["not_in_master"] == ["terraform", "aws"]
        assert run["not_in_master_frequencies"] == {"terraform": 3, "aws": 1}
        assert run["critical_missing"] == ["terraform"]
        assert run["missing_in_target"] == ["kubernetes"]
        assert run["manual_keywords"] == ["scrum"]
        assert run["pdf_path"] is None
        assert run["jd_hash"] == run["run_id"].split("-")[1]
        assert run["application"] == {"status": "pendiente", "applied_at": None, "notes": ""}

    def test_run_id_unico_por_corrida(self, history_path, jd, keyword_report):
        run1 = add_run(jd, keyword_report, path=history_path)
        run2 = add_run(jd, keyword_report, path=history_path)
        assert run1["run_id"] != run2["run_id"]

    def test_seleccion_sin_keywords_usa_el_report(self, history_path, jd, keyword_report):
        run = add_run(jd, keyword_report, selection={}, path=history_path)
        assert run["keywords_detected"] == ["python", "docker", "terraform", "aws"]

    def test_persistido_en_disco(self, history_path, jd, keyword_report):
        add_run(jd, keyword_report, path=history_path)
        saved = json.loads(history_path.read_text(encoding="utf-8"))
        assert len(saved["runs"]) == 1
        assert saved["runs"][0]["offer_title"] == "Backend Engineer (Terraform)"


class TestUpdateRun:
    def test_edita_campos_editables(self, history_path, jd, keyword_report):
        run = add_run(jd, keyword_report, path=history_path)
        updated = update_run(
            run["run_id"],
            {
                "offer_title": "Sr. Backend",
                "offer_link": "https://ejemplo.com/oferta",
                "application": {
                    "status": "aplicado",
                    "applied_at": "2026-08-10",
                    "notes": "Envié por LinkedIn.",
                },
            },
            path=history_path,
        )
        assert updated["offer_title"] == "Sr. Backend"
        assert updated["offer_link"] == "https://ejemplo.com/oferta"
        assert updated["application"]["status"] == "aplicado"
        assert updated["application"]["applied_at"] == "2026-08-10"
        assert updated["application"]["notes"] == "Envié por LinkedIn."

    def test_estado_invalido_es_rechazado(self, history_path, jd, keyword_report):
        run = add_run(jd, keyword_report, path=history_path)
        with pytest.raises(ValueError):
            update_run(run["run_id"], {"application": {"status": "ganado"}}, path=history_path)

    def test_no_modifica_datos_de_corrida(self, history_path, jd, keyword_report):
        run = add_run(jd, keyword_report, path=history_path)
        update_run(run["run_id"], {"ats_score": 100, "not_in_master": []}, path=history_path)
        reloaded = load_runs(history_path)[0]
        assert reloaded["ats_score"] == 72
        assert reloaded["not_in_master"] == ["terraform", "aws"]

    def test_run_inexistente_devuelve_none(self, history_path, jd, keyword_report):
        add_run(jd, keyword_report, path=history_path)
        assert update_run("no-existe", {"offer_title": "X"}, path=history_path) is None


class TestDeleteRun:
    def test_borra_y_devuelve_true(self, history_path, jd, keyword_report):
        run = add_run(jd, keyword_report, path=history_path)
        assert delete_run(run["run_id"], path=history_path) is True
        assert load_runs(history_path) == []

    def test_inexistente_devuelve_false(self, history_path):
        assert delete_run("no-existe", path=history_path) is False


class TestAggregateMissingKeywords:
    def _run(self, run_id, not_in_master, freqs, critical=(), created_at="", title="Oferta"):
        return {
            "run_id": run_id,
            "created_at": created_at,
            "offer_title": title,
            "not_in_master": list(not_in_master),
            "not_in_master_frequencies": {kw: freqs[kw] for kw in not_in_master},
            "critical_missing": list(critical),
        }

    def test_cuenta_ofertas_y_ordena(self):
        runs = [
            self._run("1", ["terraform", "aws"], {"terraform": 3, "aws": 1}, title="A"),
            self._run("2", ["terraform"], {"terraform": 2}, critical=["terraform"], title="B"),
        ]
        result = aggregate_missing_keywords(runs)
        assert [e["keyword"] for e in result] == ["terraform", "aws"]
        assert result[0]["count"] == 2
        assert result[0]["offer_titles"] == ["A", "B"]
        assert result[0]["total_frequency"] == 5
        assert result[0]["ever_critical"] is True
        assert result[1]["count"] == 1
        assert result[1]["total_frequency"] == 1

    def test_first_y_last_seen(self):
        runs = [
            self._run("1", ["aws"], {"aws": 1}, created_at="2026-07-01T00:00:00+00:00"),
            self._run("2", ["aws"], {"aws": 1}, created_at="2026-08-05T00:00:00+00:00"),
        ]
        result = aggregate_missing_keywords(runs)
        assert result[0]["first_seen"] == "2026-07-01T00:00:00+00:00"
        assert result[0]["last_seen"] == "2026-08-05T00:00:00+00:00"

    def test_vacio(self):
        assert aggregate_missing_keywords([]) == []


class TestBuildReportAndAddRun:
    def test_computa_report_y_registra(self, history_path, master_cv, job_description):
        target_cv = dict(master_cv)
        run = build_report_and_add_run(
            master_cv,
            target_cv,
            job_description,
            path=history_path,
        )
        assert run["ats_score"] == 100
        assert run["offer_title"] == job_description.splitlines()[0][:MAX_OFFER_TITLE_LEN]
        assert len(load_runs(history_path)) == 1


def test_estados_validos_estan_definidos():
    assert VALID_STATUSES == ("pendiente", "aplicado", "entrevista", "oferta", "rechazado")
