"""Regresión de retrieval: tokenizador con sinónimos (C3), keywords con
separadores (C2) y delimitadores de sección del JD (M1)."""
import pytest

from src.retrieval.jd_processor import extract_negated_terms, extract_requirements_section
from src.retrieval.keywords import build_keyword_ranking, build_keyword_report, extract_keywords
from src.retrieval.sparse import (
    get_synonym_variants,
    keyword_in_text,
    set_stemming,
    tokenize_with_synonyms,
)


# ---------------------------------------------------------------------------
# C3: tokenize_with_synonyms NO debe destruir los "/" (ci/cd sigue existiendo
# como token propio y expande a sus sinónimos).
# ---------------------------------------------------------------------------
def test_tokenize_ci_cd_se_mantiene_como_token():
    tokens = tokenize_with_synonyms("pipelines de CI/CD con GitHub Actions")
    assert "ci/cd" in tokens


def test_tokenize_ci_cd_expande_sinonimos():
    # Los sinónimos expandidos pasan por stemming Snowball ("continuous" ->
    # "continu"), pero el token original con slash se preserva tal cual.
    tokens = tokenize_with_synonyms("manejo de CI/CD")
    for esperado in ("ci/cd", "continu", "integr", "deliveri", "deploy"):
        assert esperado in tokens


# ---------------------------------------------------------------------------
# Stemming Snowball ES/EN (use_stemming): generaliza variantes morfológicas
# en el canal BM25 sin tocar la verificación ATS literal (keyword_in_text).
# ---------------------------------------------------------------------------
def test_tokenize_stemming_es():
    tokens = tokenize_with_synonyms("trabajé desarrollando APIs REST")
    assert "trabaj" in tokens and "desarroll" in tokens


def test_tokenize_stemming_en():
    tokens = tokenize_with_synonyms("containerized deployments and testing")
    assert "container" in tokens and "deploy" in tokens


def test_tokenize_stemming_no_rompe_terminos_tecnicos():
    # Los tokens con separadores son términos técnicos exactos: el stemmer
    # de inglés mutila "next.js" -> "next.j", así que se excluyen del stemming.
    tokens = tokenize_with_synonyms("pipelines de ci/cd con c++ y next.js")
    for esperado in ("ci/cd", "c++", "next.js"):
        assert esperado in tokens


def test_tokenize_stemming_apagado_usa_forma_original():
    set_stemming(False)
    try:
        tokens = tokenize_with_synonyms("trabajé desarrollando")
        assert "trabajé" in tokens and "desarrollando" in tokens
    finally:
        set_stemming(True)


def test_tokenize_stopwords_se_filtran_antes_del_stemming():
    # Si se stemmea primero, "was" -> "wa" y se cuela como término vacío
    # al índice. El filtro de stopwords debe correr ANTES del stemming.
    tokens = tokenize_with_synonyms("was working with docker")
    assert "was" not in tokens and "wa" not in tokens
    assert "work" in tokens


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
# Prefijos E5 (intfloat/multilingual-e5-small): la query lleva "query: " y
# los documentos "passage: ". Solo se aplican a modelos e5; el resto queda
# intacto (los prefijos degradan los embeddings de otros modelos).
# ---------------------------------------------------------------------------
def test_prefixed_texts_e5_agrega_prefijos():
    from src.retrieval.dense import prefixed_texts

    assert prefixed_texts(
        ["hola mundo"], "query", "intfloat/multilingual-e5-small"
    ) == ["query: hola mundo"]
    assert prefixed_texts(
        ["hola mundo"], "passage", "intfloat/multilingual-e5-small"
    ) == ["passage: hola mundo"]


def test_prefixed_texts_no_e5_sin_prefijo():
    from src.retrieval.dense import prefixed_texts

    assert prefixed_texts(["hola"], "query", "sentence-transformers/all-MiniLM-L6-v2") == ["hola"]
    assert prefixed_texts(["hola"], "query", "") == ["hola"]
    assert prefixed_texts(["hola"], "query", None) == ["hola"]


def test_prefixed_texts_role_invalido_sin_prefijo():
    from src.retrieval.dense import prefixed_texts

    assert prefixed_texts(["hola"], "doc", "intfloat/multilingual-e5-small") == ["hola"]


def test_dense_index_e5_prefija_bullets_al_indexar():
    import numpy as np

    from src.retrieval.dense import DenseIndex

    class FakeModel:
        def __init__(self):
            self.seen = None

        def encode(self, texts, **kwargs):
            self.seen = list(texts)
            return np.zeros((len(texts), 4))

    model = FakeModel()
    DenseIndex(model, "intfloat/multilingual-e5-small").build(
        [{"id": "a", "text": "Desarrollé APIs REST"}]
    )
    assert model.seen == ["passage: Desarrollé APIs REST"]


def test_dense_index_sin_e5_no_prefija():
    import numpy as np

    from src.retrieval.dense import DenseIndex

    class FakeModel:
        def __init__(self):
            self.seen = None

        def encode(self, texts, **kwargs):
            self.seen = list(texts)
            return np.zeros((len(texts), 4))

    model = FakeModel()
    DenseIndex(model, "sentence-transformers/all-MiniLM-L6-v2").build(
        [{"id": "a", "text": "Desarrollé APIs REST"}]
    )
    assert model.seen == ["Desarrollé APIs REST"]


# ---------------------------------------------------------------------------
# Fingerprint del índice: el cambio de modelo/flag de stemming invalida el
# índice persistido aunque el master no cambie (si no, se cargan embeddings
# stale, de otra dimensión cuando el modelo cambia).
# ---------------------------------------------------------------------------
def test_index_store_fingerprint_incluye_params(tmp_path):
    from src.retrieval.store import IndexStore

    store = IndexStore(tmp_path / "idx")
    master = "yaml: contenido"
    store.save_hash(master, {"dense_model": "modelo-a", "use_stemming": True})
    assert store.is_fresh(master, {"dense_model": "modelo-a", "use_stemming": True})
    assert not store.is_fresh(master, {"dense_model": "modelo-b", "use_stemming": True})
    assert not store.is_fresh(master, {"dense_model": "modelo-a", "use_stemming": False})
    assert not store.is_fresh(master)


def test_index_store_fingerprint_legacy_sin_params(tmp_path):
    from src.retrieval.store import IndexStore

    store = IndexStore(tmp_path / "idx")
    store.save_hash("yaml")
    assert store.is_fresh("yaml")
    assert not store.is_fresh("otro yaml")


# ---------------------------------------------------------------------------
# RRF: pesos de canales configurables (sparse_weight/dense_weight) y k.
# Con peso 0 en un canal, el otro decide el orden exacto; el conjunto de
# resultados se mantiene para cualquier k razonable.
# ---------------------------------------------------------------------------
def test_rrf_peso_sparse_cero_usa_solo_denso():
    from src.retrieval.hybrid import reciprocal_rank_fusion

    sparse = ["a", "b", "c"]
    dense = ["b", "c", "d"]
    fused = reciprocal_rank_fusion(sparse, dense, sparse_weight=0.0, dense_weight=1.0)
    assert fused == ["b", "c", "d"]


def test_rrf_peso_dense_cero_usa_solo_sparse():
    from src.retrieval.hybrid import reciprocal_rank_fusion

    sparse = ["a", "b", "c"]
    dense = ["b", "c", "d"]
    fused = reciprocal_rank_fusion(sparse, dense, sparse_weight=1.0, dense_weight=0.0)
    assert fused == ["a", "b", "c"]


def test_rrf_peso_sparse_dominante_prioriza_orden_sparse():
    from src.retrieval.hybrid import reciprocal_rank_fusion

    # "a" rank 1 en sparse; "b" rank 1 en dense. Con sparse_weight alto,
    # "a" gana aunque dense la tenga peor rankeada.
    fused = reciprocal_rank_fusion(
        ["a", "b"], ["b", "a"], sparse_weight=5.0, dense_weight=1.0
    )
    assert fused[0] == "a"


def test_rrf_distintos_k_preservan_conjunto_de_resultados():
    from src.retrieval.hybrid import reciprocal_rank_fusion

    sparse = ["a", "b", "c", "d"]
    dense = ["d", "c", "b"]
    for k in (1, 15, 60):
        fused = reciprocal_rank_fusion(sparse, dense, k=k)
        assert set(fused) == {"a", "b", "c", "d"}


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


# ---------------------------------------------------------------------------
# P1.3: keywords manuales del usuario (custom_keywords) entran SIEMPRE a la
# detección aunque no estén en el JD, sin duplicar el diccionario, y con
# frecuencia mínima 1 para que pesen en el ranking por keywords.
# ---------------------------------------------------------------------------
def test_extract_keywords_incluye_custom_fuera_del_jd():
    # "zurbark" no está en el JD ni en TECH_KEYWORDS: entra igual, con
    # frecuencia mínima 1 (si no, el canal de keywords lo ignoraría).
    keywords, frequencies = extract_keywords(
        "Buscamos python", custom_keywords=["zurbark", "  ZURBARK "]
    )
    assert "zurbark" in keywords
    assert frequencies["zurbark"] == 1
    # La lista se normaliza (minúsculas, sin duplicados, sin bordes).
    assert keywords.count("zurbark") == 1


def test_extract_keywords_custom_no_duplica_diccionario():
    # "python" ya está en el JD y en TECH_KEYWORDS: la custom no lo duplica
    # y respeta la frecuencia real (1), no la mínima.
    keywords, frequencies = extract_keywords(
        "Buscamos python", custom_keywords=["python"]
    )
    assert keywords.count("python") == 1
    assert frequencies["python"] == 1


def test_extract_keywords_custom_string_separado_por_comas():
    # Defensivo: la config puede llegar como string crudo desde la UI.
    keywords, _ = extract_keywords("Buscamos python", custom_keywords="zurbark, zap")
    assert {"zurbark", "zap"}.issubset(set(keywords))


def test_extract_keywords_sin_custom_regresion():
    # Sin el parámetro, el comportamiento es idéntico al anterior.
    keywords, frequencies = extract_keywords("Buscamos python y docker")
    assert {"python", "docker"}.issubset(set(keywords))
    assert frequencies["python"] == 1


def test_build_keyword_ranking_incluye_bullets_de_custom():
    bullets = [
        {"id": "a", "text": "Administré clústeres zurbark."},
        {"id": "b", "text": "Usé python para servicios."},
    ]
    # Sin custom, "zurbark" no existe para el canal de keywords.
    assert "a" not in build_keyword_ranking(bullets, "Buscamos python")
    # Con custom, el bullet que la contiene entra al ranking.
    assert "a" in build_keyword_ranking(bullets, "Buscamos python", ["zurbark"])


def test_build_keyword_report_incluye_custom():
    master = {
        "cv": {
            "sections": {
                "skills": [{"label": "Lenguajes", "details": ["python", "zurbark"]}],
            }
        }
    }
    report = build_keyword_report(master, {}, "Buscamos python", ["zurbark"])
    assert "zurbark" in report["all_keywords"]
    assert report["in_master"]["zurbark"] is True


# ---------------------------------------------------------------------------
# P0.2: extract_negated_terms detecta exclusiones explícitas del JD
# ("no se requiere X"). Solo sobreviven términos presentes en el master
# (mismo doble chequeo que las open keywords) y se filtran palabras
# genéricas de ofertas ("experiencia", "conocimientos").
# ---------------------------------------------------------------------------
def test_extract_negated_terms_detecta_patron_es():
    jd = "No se requiere experiencia en soporte técnico ni en frontend."
    master = "Brindé soporte técnico a clientes. Desarrollo frontend con React."
    terms = extract_negated_terms(jd, master)
    assert {"soporte técnico", "frontend"}.issubset(terms)
    # "experiencia" es genérica de ofertas: no puede penalizar un bullet.
    assert "experiencia" not in terms


def test_extract_negated_terms_detecta_patron_en():
    # "zurbark" no está en TECH_KEYWORDS: el patrón inglés de open tokens
    # ("no experience with X") solo se prueba vía el doble chequeo con master.
    jd = "No experience with zurbark needed."
    master = "Monitoreo de clústeres con zurbark."
    assert "zurbark" in extract_negated_terms(jd, master)


def test_extract_negated_terms_sin_negaciones_devuelve_vacio():
    jd = "Buscamos un backend developer con python y docker."
    assert extract_negated_terms(jd, "Uso python y docker.") == set()


def test_extract_negated_terms_requiere_master_para_no_diccionario():
    jd = "No se requiere experiencia en frontend."
    # Sin master no hay cómo verificar que el término existe: vacío.
    assert extract_negated_terms(jd) == set()
    assert "frontend" in extract_negated_terms(jd, "Maqueté con frontend.")


def test_extract_negated_terms_jd_contradictorio_no_penaliza():
    # El mismo término mencionado en positivo gana sobre la negación:
    # penalizarlo sería un falso negativo agresivo.
    jd = "Se requiere soporte técnico. No se requiere experiencia en frontend."
    master = "Brindé soporte técnico a clientes. Desarrollo frontend con React."
    terms = extract_negated_terms(jd, master)
    assert "soporte técnico" not in terms
    assert "soporte" not in terms
    assert "frontend" in terms
