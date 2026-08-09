"""Regresión de retrieval: tokenizador con sinónimos (C3), keywords con
separadores (C2) y delimitadores de sección del JD (M1)."""
import pytest

from src.retrieval.jd_processor import extract_requirements_section
from src.retrieval.keywords import build_keyword_ranking, extract_keywords
from src.retrieval.sparse import get_synonym_variants, tokenize_with_synonyms


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
