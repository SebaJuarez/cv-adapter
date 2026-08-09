"""Regresión de retrieval: tokenizador con sinónimos (C3), keywords con
separadores (C2) y delimitadores de sección del JD (M1)."""
import pytest

from src.retrieval.jd_processor import extract_requirements_section
from src.retrieval.keywords import build_keyword_ranking, build_keyword_report, extract_keywords
from src.retrieval.sparse import get_synonym_variants, keyword_in_text, tokenize_with_synonyms


# ---------------------------------------------------------------------------
# C3: tokenize_with_synonyms NO debe destruir los "/" (ci/cd sigue existiendo
# como token propio y expande a sus sinónimos).
# ---------------------------------------------------------------------------
def test_tokenize_ci_cd_se_mantiene_como_token():
    tokens = tokenize_with_synonyms("pipelines de CI/CD con GitHub Actions")
    assert "ci/cd" in tokens


def test_tokenize_ci_cd_expande_sinonimos():
    tokens = tokenize_with_synonyms("manejo de CI/CD")
    for esperado in ("ci/cd", "continuous", "integration", "delivery", "deployment"):
        assert esperado in tokens


def test_get_synonym_variants_devuelve_grupo_completo():
    variantes = get_synonym_variants("CI/CD")
    assert variantes == {
        "ci/cd",
        "continuous integration",
        "continuous delivery",
        "continuous deployment",
    }


def test_get_synonym_variants_keyword_desconocida():
    assert get_synonym_variants("rust") == {"rust"}


# ---------------------------------------------------------------------------
# keyword_in_text: matching con límites de palabra + sinónimos. Evita el
# falso positivo del substring ("js" dentro de "jsp") que ponía chips
# amarillos sin bullets para traer.
# ---------------------------------------------------------------------------
def test_keyword_in_text_no_matchea_substring():
    assert not keyword_in_text("js", "trabajo con jsp y json")


def test_keyword_in_text_matchea_sinonimo():
    assert keyword_in_text("js", "desarrollo con JavaScript")


def test_keyword_in_text_matchea_termino_exacto():
    assert keyword_in_text("docker", "uso Docker en producción")


def test_keyword_in_text_respeta_separadores_como_limite():
    # "js" al final de "node.js" matchea: el "." es un límite válido.
    assert keyword_in_text("js", "armé dashboards con node.js")
    assert keyword_in_text("ci/cd", "pipelines de CI/CD en GCP")


def test_keyword_in_text_multi_palabra():
    assert keyword_in_text("github actions", "mantenía GitHub Actions")


# ---------------------------------------------------------------------------
# build_keyword_report: el reporte ubica dónde vive cada keyword en el
# master (bullets y texto sin bullets) y no alucina por substring.
# ---------------------------------------------------------------------------
def test_keyword_report_js_no_matchea_jsp():
    master = {
        "cv": {
            "sections": {
                "skills": [
                    {"label": "Lenguajes", "details": ["Java", "JSP"]},
                ]
            }
        }
    }
    report = build_keyword_report(master, master, "Buscamos dev con js")
    assert report["in_master"]["js"] is False


def test_keyword_report_locations_distingue_bullet_de_no_bullet():
    master = {
        "cv": {
            "sections": {
                "summary": ["Desarrollador con experiencia en JavaScript."],
                "experience": [
                    {
                        "company": "Empresa",
                        "highlights": [
                            "Mantuve una app en JavaScript.",
                            "Administré servidores.",
                        ],
                    }
                ],
            }
        }
    }
    report = build_keyword_report(master, {}, "Buscamos js")
    locs = report["locations"]["js"]
    assert report["in_master"]["js"] is True
    bullets = [l for l in locs if l["field"] == "highlights"]
    no_bullets = [l for l in locs if l["field"] != "highlights"]
    assert len(bullets) == 1
    assert bullets[0]["bullet_idx"] == 0
    assert bullets[0]["text"] == "Mantuve una app en JavaScript."
    assert len(no_bullets) == 1
    assert no_bullets[0]["section"] == "summary"
    assert no_bullets[0]["field"] is None


def test_keyword_report_keyword_variants_expone_sinonimos():
    master = {
        "cv": {
            "sections": {
                "skills": [{"label": "Lenguajes", "details": ["Java"]}],
            }
        }
    }
    report = build_keyword_report(master, {}, "Buscamos js")
    assert set(report["keyword_variants"]["js"]) == {"js", "javascript"}


# ---------------------------------------------------------------------------
# C2: keywords con separadores (+ # - . /) se detectan sobre el texto crudo.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "texto, esperadas",
    [
        ("Buscamos c++ y c#", {"c++", "c#"}),
        ("Experiencia con next.js y objective-c", {"next.js", "objective-c"}),
        ("Manejo de ci/cd en producción", {"ci/cd"}),
    ],
)
def test_extract_keywords_con_separadores(texto, esperadas):
    keywords, _ = extract_keywords(texto)
    assert esperadas.issubset(set(keywords))


def test_extract_keywords_normales_siguen_funcionando():
    keywords, _ = extract_keywords("Buscamos python y docker")
    assert {"python", "docker"}.issubset(set(keywords))


def test_extract_keywords_con_puntuacion_pegada_al_token():
    # Regresión: "docker." o "python," (el caso normal en un JD real) no
    # podían detectarse porque el token conservaba la puntuación pegada.
    keywords, _ = extract_keywords("Requisitos: docker, python. CI/CD; y next.js.")
    assert {"docker", "python", "ci/cd", "next.js"}.issubset(set(keywords))


def test_extract_keywords_bigram_con_puntuacion():
    keywords, _ = extract_keywords("Mantenía pipelines con github actions.")
    assert "github actions" in keywords


def test_build_keyword_ranking_matchea_cpp17():
    bullets = [
        {"id": "a", "text": "Programé en c++17 y creé APIs REST."},
        {"id": "b", "text": "Usé java para servicios batch."},
    ]
    ranking = build_keyword_ranking(bullets, "Se necesita c++")
    assert "a" in ranking


def test_build_keyword_ranking_case_insensitive_separadores():
    bullets = [
        {"id": "a", "text": "C# y Docker en Azure."},
        {"id": "b", "text": "Solo python."},
    ]
    ranking = build_keyword_ranking(bullets, "Requerimos c#")
    assert "a" in ranking


# ---------------------------------------------------------------------------
# M1: extract_requirements_section corta en los delimitadores ampliados.
# ---------------------------------------------------------------------------
def test_requirements_section_corta_en_beneficios():
    jd = "Requisitos:\nConocimientos de python y docker.\nBeneficios:\nObra social."
    assert extract_requirements_section(jd) == "Conocimientos de python y docker."


def test_requirements_section_corta_en_ofrecemos():
    jd = "Buscamos dev con python.\nOfrecemos:\nSalario competitivo."
    assert extract_requirements_section(jd) == "dev con python."


def test_requirements_section_corta_en_postulate():
    jd = "Buscamos dev con python.\nPostúlate enviando tu CV."
    assert extract_requirements_section(jd) == "dev con python."


def test_requirements_section_corta_en_salario():
    jd = "Requisitos:\nSaber python.\nSalario: 100k."
    assert extract_requirements_section(jd) == "Saber python."


def test_requirements_section_sin_marcadores_devuelve_jd_completo():
    jd = "Somos una empresa moderna buscando talento."
    assert extract_requirements_section(jd) == jd
