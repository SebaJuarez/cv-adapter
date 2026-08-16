"""Tests del historial de corridas y seguimiento de aplicaciones.

Cubren las invariantes de la feature: el historial es metadata
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
    aggregate_variant_stats,
    delete_run,
    delete_run_cv,
    extract_offer_title,
    load_run_cv,
    load_runs,
    save_run_cv,
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

    def test_saca_prefijos_de_reclutamiento(self):
        assert extract_offer_title("Buscamos Backend Engineer") == "Backend Engineer"
        assert extract_offer_title("Estamos buscando un Data Analyst") == "Data Analyst"
        assert extract_offer_title("Job title: Frontend Developer") == "Frontend Developer"
        assert extract_offer_title("We are looking for a DevOps Engineer") == "DevOps Engineer"
        assert extract_offer_title("Hiring: QA Automation") == "QA Automation"

    def test_elige_segmento_de_titulo_entre_separadores(self):
        assert extract_offer_title("Backend Engineer | Acme Corp") == "Backend Engineer"
        assert extract_offer_title("Acme - Backend Engineer") == "Backend Engineer"
        assert extract_offer_title("Senior QA Engineer – Acme Inc.") == "Senior QA Engineer"
        assert extract_offer_title("Data Engineer · Acme Group") == "Data Engineer"

    def test_descarta_ubicacion_y_modalidad(self):
        assert extract_offer_title("Buenos Aires - Backend Engineer") == "Backend Engineer"
        assert extract_offer_title("Remote - Full Stack Developer") == "Full Stack Developer"

    def test_todo_junk_devuelve_la_linea_completa(self):
        line = "Buenos Aires - Remote"
        assert extract_offer_title(line) == line

    def test_colapsa_espacios_multiple(self):
        assert extract_offer_title("   Backend   Engineer   ") == "Backend Engineer"


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
        assert run["job_description"] == jd
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

    def test_persiste_traza_de_variantes_por_bullet(self, history_path, jd, keyword_report):
        # La traza solo se persiste si hay usos reales (runs legacy sin clave).
        bullet_variants = [
            {
                "section": "experience",
                "entry_index": 0,
                "ach_id": "ach_1",
                "variant_id": "var_1a",
                "angle": "impacto_tecnico",
                "text": "Diseñé un sistema de facturación.",
            }
        ]
        run = add_run(jd, keyword_report, bullet_variants=bullet_variants, path=history_path)
        assert run["bullet_variants"] == bullet_variants
        reloaded = load_runs(history_path)[0]
        assert reloaded["bullet_variants"] == bullet_variants

    def test_sin_bullet_variants_no_crea_la_clave(self, history_path, jd, keyword_report):
        run = add_run(jd, keyword_report, path=history_path)
        assert "bullet_variants" not in run
        assert "bullet_variants" not in load_runs(history_path)[0]


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

    def test_actualiza_pdf_path(self, history_path, jd, keyword_report):
        run = add_run(jd, keyword_report, path=history_path)
        updated = update_run(run["run_id"], {"pdf_path": "output/CV.pdf"}, path=history_path)
        assert updated["pdf_path"] == "output/CV.pdf"

    def test_rechaza_pdf_path_fuera_de_output(self, history_path, jd, keyword_report, tmp_path):
        run = add_run(jd, keyword_report, path=history_path)
        with pytest.raises(ValueError):
            update_run(
                run["run_id"],
                {"pdf_path": str(tmp_path / "afuera" / "CV.pdf")},
                path=history_path,
                output_dir=tmp_path / "output",
            )

    def test_rechaza_pdf_path_en_directorio_hermano(
        self, history_path, jd, keyword_report, tmp_path
    ):
        run = add_run(jd, keyword_report, path=history_path)
        for sibling in ("output-old", "output_backup"):
            with pytest.raises(ValueError):
                update_run(
                    run["run_id"],
                    {"pdf_path": str(tmp_path / sibling / "CV.pdf")},
                    path=history_path,
                    output_dir=tmp_path / "output",
                )

    def test_acepta_pdf_path_relativo_dentro_de_output(self, history_path, jd, keyword_report):
        run = add_run(jd, keyword_report, path=history_path)
        updated = update_run(run["run_id"], {"pdf_path": "output/sub/CV.pdf"}, path=history_path)
        assert updated["pdf_path"] == "output/sub/CV.pdf"


class TestDeleteRun:
    def test_borra_y_devuelve_true(self, history_path, jd, keyword_report):
        run = add_run(jd, keyword_report, path=history_path)
        assert delete_run(run["run_id"], path=history_path) is True
        assert load_runs(history_path) == []

    def test_inexistente_devuelve_false(self, history_path):
        assert delete_run("no-existe", path=history_path) is False

    def test_delete_files_borra_cv_y_pdf(self, history_path, jd, keyword_report, tmp_path):
        run = add_run(jd, keyword_report, pdf_path=str(tmp_path / "output" / "CV.pdf"), path=history_path)
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        (output_dir / "CV.pdf").write_text("x", encoding="utf-8")
        cvs_dir = tmp_path / "cvs"
        save_run_cv(run["run_id"], "cv: yaml", cvs_dir=cvs_dir)

        assert delete_run(
            run["run_id"], path=history_path, delete_files=True,
            cvs_dir=cvs_dir, output_dir=output_dir,
        ) is True
        assert load_run_cv(run["run_id"], cvs_dir=cvs_dir) is None
        assert not (output_dir / "CV.pdf").exists()

    def test_delete_files_no_toca_pdf_fuera_de_output(self, history_path, jd, keyword_report, tmp_path):
        run = add_run(jd, keyword_report, pdf_path=str(tmp_path / "afuera.pdf"), path=history_path)
        pdf = tmp_path / "afuera.pdf"
        pdf.write_text("x", encoding="utf-8")

        delete_run(
            run["run_id"], path=history_path, delete_files=True,
            cvs_dir=tmp_path / "cvs", output_dir=tmp_path / "output",
        )
        assert pdf.exists()

    @pytest.mark.parametrize("sibling", ["output-old", "output_backup"])
    def test_delete_files_no_toca_pdf_en_directorio_hermano(
        self, history_path, jd, keyword_report, tmp_path, sibling
    ):
        output_dir = tmp_path / "output"
        pdf = tmp_path / sibling / "CV.pdf"
        pdf.parent.mkdir()
        pdf.write_text("x", encoding="utf-8")
        run = add_run(jd, keyword_report, pdf_path=str(pdf), path=history_path)

        delete_run(
            run["run_id"], path=history_path, delete_files=True,
            cvs_dir=tmp_path / "cvs", output_dir=output_dir,
        )
        assert pdf.exists()

    def test_sin_delete_files_conserva_archivos(self, history_path, jd, keyword_report, tmp_path):
        run = add_run(jd, keyword_report, pdf_path=str(tmp_path / "CV.pdf"), path=history_path)
        cvs_dir = tmp_path / "cvs"
        save_run_cv(run["run_id"], "cv: yaml", cvs_dir=cvs_dir)

        delete_run(run["run_id"], path=history_path, cvs_dir=cvs_dir, output_dir=tmp_path)
        assert load_run_cv(run["run_id"], cvs_dir=cvs_dir) is not None


class TestRunCv:
    def test_roundtrip(self, tmp_path):
        cvs_dir = tmp_path / "cvs"
        save_run_cv("run-1", "name: X\nsections: {}\n", cvs_dir=cvs_dir)
        assert load_run_cv("run-1", cvs_dir=cvs_dir) == "name: X\nsections: {}\n"

    def test_inexistente_devuelve_none(self, tmp_path):
        assert load_run_cv("no-existe", cvs_dir=tmp_path / "cvs") is None

    def test_delete(self, tmp_path):
        cvs_dir = tmp_path / "cvs"
        save_run_cv("run-1", "name: X\n", cvs_dir=cvs_dir)
        assert delete_run_cv("run-1", cvs_dir=cvs_dir) is True
        assert delete_run_cv("run-1", cvs_dir=cvs_dir) is False


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


def test_estados_validos_estan_definidos():
    assert VALID_STATUSES == ("pendiente", "aplicado", "entrevista", "oferta", "rechazado")


def _bullet(ach_id, variant_id, text="", angle=""):
    return {"ach_id": ach_id, "variant_id": variant_id, "text": text, "angle": angle}


def _run_con_variantes(run_id, bullets, status="pendiente", created_at=""):
    return {
        "run_id": run_id,
        "created_at": created_at,
        "application": {"status": status},
        "bullet_variants": [_bullet(*b) for b in bullets],
    }


class TestAggregateVariantStats:
    def test_cuenta_corridas_y_exitos_por_variante(self):
        runs = [
            _run_con_variantes("r1", [("ach_1", "var_1a", "Redacción A", "liderazgo")], status="entrevista"),
            _run_con_variantes("r2", [("ach_1", "var_1a", "Redacción A", "liderazgo")], status="pendiente"),
            _run_con_variantes("r3", [("ach_1", "var_1b", "Redacción B")], status="oferta"),
        ]
        result = aggregate_variant_stats(runs)
        por_id = {v["variant_id"]: v for v in result}
        assert por_id["var_1a"]["runs"] == 2
        assert por_id["var_1a"]["successful_runs"] == 1
        assert por_id["var_1a"]["text"] == "Redacción A"
        assert por_id["var_1a"]["angle"] == "liderazgo"
        assert por_id["var_1b"]["runs"] == 1
        assert por_id["var_1b"]["successful_runs"] == 1

    def test_misma_variante_dos_bullets_en_un_run_cuenta_una_corrida(self):
        # La misma variante puede emitirse dos veces en un run (dos logros con
        # el mismo id no debería pasar, pero la agregación es por corrida).
        runs = [
            _run_con_variantes(
                "r1",
                [("ach_1", "var_1a"), ("ach_2", "var_1a")],
                status="entrevista",
            )
        ]
        result = aggregate_variant_stats(runs)
        assert result[0]["runs"] == 1
        assert result[0]["successful_runs"] == 1

    def test_ordena_por_corridas_luego_exitos(self):
        runs = [
            _run_con_variantes("r1", [("a", "v1")], status="pendiente"),
            _run_con_variantes("r2", [("a", "v1")], status="pendiente"),
            _run_con_variantes("r3", [("a", "v2")], status="entrevista"),
        ]
        result = aggregate_variant_stats(runs)
        assert [v["variant_id"] for v in result] == ["v1", "v2"]

    def test_ultima_uso_es_la_corrida_mas_reciente(self):
        runs = [
            _run_con_variantes("r1", [("a", "v1")], created_at="2026-07-01T00:00:00+00:00"),
            _run_con_variantes("r2", [("a", "v1")], created_at="2026-08-05T00:00:00+00:00"),
        ]
        result = aggregate_variant_stats(runs)
        assert result[0]["last_used"] == "2026-08-05T00:00:00+00:00"

    def test_runs_legacy_y_vacios_no_rompen(self):
        runs = [
            {"run_id": "legacy", "application": {"status": "pendiente"}},
            {"run_id": "r2", "application": {"status": "aplicado"}, "bullet_variants": []},
        ]
        assert aggregate_variant_stats(runs) == []

    def test_variante_sin_variant_id_ignorada(self):
        runs = [{"run_id": "r1", "application": {"status": "pendiente"},
                 "bullet_variants": [{"ach_id": "a", "variant_id": None, "text": "x"}]}]
        assert aggregate_variant_stats(runs) == []
