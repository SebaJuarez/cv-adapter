"""Regresión de la generación asistida de variantes:

el LLM redacta SOLO con los hechos del logro, los términos declarados se
verifican contra el corpus (con sinónimos), los no respaldados se listan
(no se descartan en silencio) y los errores del proveedor se propagan con
mensaje legible — la UX muestra toast + enlace a Configuración en vez de
silenciar como hace extract_achievement_facts.
"""
import time

import pytest

from src.llm_node import generate_variant_text


FACTS_PYTHON = {
    "action": "Desarrollé APIs REST con python y docker.",
    "tools": ["python", "docker"],
    "scope": "equipo backend",
    "outcomes": [{"metric": "latencia", "value": "-40%"}],
}


def _llm_ok(result):
    """Mock de _call_llm que devuelve un resultado fijo."""
    return lambda *args, **kwargs: result


# ---------------------------------------------------------------------------
# Verificación de términos contra el corpus del logro
# ---------------------------------------------------------------------------
def test_verifica_terminos_y_lista_los_no_respaldados(monkeypatch, config):
    monkeypatch.setattr(
        "src.llm_node._call_llm",
        _llm_ok(
            {
                "text": "Reduje la latencia 40% con python y kubernetes.",
                "tech_terms": ["python", "kubernetes"],
            }
        ),
    )
    out = generate_variant_text(
        angle="escala", facts=FACTS_PYTHON, variant_texts=[], config=config
    )
    assert out["text"] == "Reduje la latencia 40% con python y kubernetes."
    assert out["unverified_terms"] == ["kubernetes"]


def test_sin_terminos_no_verificados(monkeypatch, config):
    monkeypatch.setattr(
        "src.llm_node._call_llm",
        _llm_ok({"text": "APIs REST con python en producción.", "tech_terms": ["python"]}),
    )
    out = generate_variant_text(
        angle="impacto_tecnico", facts=FACTS_PYTHON, variant_texts=["texto viejo con docker"], config=config
    )
    assert out["unverified_terms"] == []


def test_acepta_sinonimo_del_corpus(monkeypatch, config):
    """Un término que solo aparece como sinónimo en el corpus también vale."""
    monkeypatch.setattr(
        "src.llm_node._call_llm",
        _llm_ok({"text": "Modelé datos con postgres.", "tech_terms": ["postgres"]}),
    )
    out = generate_variant_text(
        angle="impacto_tecnico", facts={}, variant_texts=[], current_text="Diseñé esquemas en postgresql.", config=config
    )
    assert out["unverified_terms"] == []


def test_sin_tech_terms_no_hay_nada_que_verificar(monkeypatch, config):
    monkeypatch.setattr(
        "src.llm_node._call_llm",
        _llm_ok({"text": "Coordiné el equipo para entregar a tiempo.", "tech_terms": []}),
    )
    out = generate_variant_text(
        angle="liderazgo", facts=FACTS_PYTHON, variant_texts=[], config=config
    )
    assert out["unverified_terms"] == []


# ---------------------------------------------------------------------------
# Guardarraíl anti-alucinación y degradación
# ---------------------------------------------------------------------------
def test_error_del_proveedor_se_propaga_con_mensaje(monkeypatch, config):
    def llm_roto(*args, **kwargs):
        raise RuntimeError("Ollama no responde")

    monkeypatch.setattr("src.llm_node._call_llm", llm_roto)
    with pytest.raises(RuntimeError, match="Ollama no responde"):
        generate_variant_text(
            angle="escala", facts=FACTS_PYTHON, variant_texts=[], config=config
        )


def test_texto_vacio_es_un_fallo(monkeypatch, config):
    monkeypatch.setattr(
        "src.llm_node._call_llm", _llm_ok({"text": "  ", "tech_terms": []})
    )
    with pytest.raises(RuntimeError, match="redacción vacía"):
        generate_variant_text(
            angle="escala", facts=FACTS_PYTHON, variant_texts=[], config=config
        )


def test_angulo_invalido_no_llama_al_llm(monkeypatch, config):
    llamado = []

    def llm_espia(*args, **kwargs):
        llamado.append(True)
        return {"text": "x", "tech_terms": []}

    monkeypatch.setattr("src.llm_node._call_llm", llm_espia)
    with pytest.raises(RuntimeError, match="Ángulo desconocido"):
        generate_variant_text(
            angle="magia", facts=FACTS_PYTHON, variant_texts=[], config=config
        )
    assert not llamado


def test_sin_contenido_no_redacta(monkeypatch, config):
    monkeypatch.setattr(
        "src.llm_node._call_llm",
        _llm_ok({"text": "algo", "tech_terms": []}),
    )
    with pytest.raises(RuntimeError, match="no tiene contenido para redactar"):
        generate_variant_text(
            angle="escala", facts={}, variant_texts=[], config=config
        )


def test_timeout_degrada_con_mensaje_claro(monkeypatch, config):
    def llm_lento(*args, **kwargs):
        time.sleep(0.5)
        return {"text": "tarde", "tech_terms": []}

    monkeypatch.setattr("src.llm_node._call_llm", llm_lento)
    with pytest.raises(RuntimeError, match="tardó demasiado"):
        generate_variant_text(
            angle="escala", facts=FACTS_PYTHON, variant_texts=[], config=config, timeout=0.05
        )