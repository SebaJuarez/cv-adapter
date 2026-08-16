"""Modelo de logros con variantes: compatibilidad y esquema.

Cubre `src/achievements.py` (slots, variante representativa, validación)
y su integración en merge/selection: el máster legacy sigue generando el
mismo target, los achievements se resuelven a su variante representativa,
el bloque `achievements` jamás llega al target, las variantes `pending`
nunca emiten texto, y el corpus ATS incluye hechos + variantes
aprobadas.
"""
import pytest
import yaml

from src.achievements import (
    apply_variant_usage,
    approved_variant_texts,
    entry_bullet_slots,
    facts_corpus_parts,
    index_text,
    normalize_angles,
    representative_variant,
    resolve_slot_text,
    resolve_slot_with_variant,
    resolve_variant,
    resolve_variant_text,
    validate_achievements_structure,
    variant_status,
)
from src.merge import (
    _apply_entry_selection,
    _build_verified_keywords,
    _master_cv_corpus,
    build_target_cv,
    extract_bullet_variants,
    validate_master_cv_structure,
)
from src.render_node import save_yaml
from src.selection import _extract_bullets_from_section


# ---------------------------------------------------------------------------
# Helpers de fixtures
# ---------------------------------------------------------------------------
def _variant(vid, text, status="approved", angle=None, used_count=0, created_at=None):
    variant = {"id": vid, "text": text, "used_count": used_count}
    if status != "approved":
        variant["status"] = status
    if angle is not None:
        variant["angle"] = angle
    if created_at is not None:
        variant["created_at"] = created_at
    return variant


def _achievement(aid, variants, facts=None):
    return {"id": aid, "variants": variants, "facts": facts or {}}


@pytest.fixture
def master_achievements():
    """Máster con una entrada en formato achievements + una legacy, para
    probar la convivencia de formatos en el MISMO archivo (la regla de un
    solo formato aplica por entrada, no por archivo)."""
    return {
        "cv": {
            "name": "Test User",
            "location": "Ciudad",
            "sections": {
                "summary": ["Ingeniero backend."],
                "experience": [
                    {
                        "company": "Empresa A",
                        "position": "Backend Developer",
                        "achievements": [
                            _achievement(
                                "ach_1",
                                [
                                    _variant(
                                        "var_1a",
                                        "Diseñé un sistema de facturación con Java y Spring Boot.",
                                        used_count=7,
                                        angle="impacto_tecnico",
                                        created_at="2024-01-10",
                                    ),
                                    _variant(
                                        "var_1b",
                                        "Lideré el diseño de un sistema de facturación con un equipo de 4 personas.",
                                        used_count=3,
                                        angle=["liderazgo", "escala"],
                                        created_at="2024-03-02",
                                    ),
                                    _variant(
                                        "var_1c",
                                        "Sistema de facturación sin verificar.",
                                        status="pending",
                                    ),
                                ],
                                facts={
                                    "action": "Diseñé y desplegué un sistema de facturación",
                                    "tools": ["Java", "Spring Boot", "PostgreSQL"],
                                },
                            ),
                            _achievement(
                                "ach_2",
                                [
                                    _variant(
                                        "var_2a",
                                        "Reduje incidentes en producción un 30%.",
                                        used_count=0,
                                    )
                                ],
                                facts={
                                    "action": "Reduje incidentes en producción",
                                    "outcomes": [
                                        {"metric": "incidentes", "value": "-30%"}
                                    ],
                                },
                            ),
                            _achievement(
                                "ach_3",
                                [
                                    _variant(
                                        "var_3a",
                                        "Desarrollé pipelines de CI/CD con GitHub Actions.",
                                        used_count=2,
                                        angle="calidad_testing",
                                    )
                                ],
                            ),
                        ],
                    },
                    {
                        "company": "Empresa B",
                        "position": "Legacy",
                        "highlights": ["Bullet legacy uno.", "Bullet legacy dos."],
                    },
                ],
            },
        },
        "design": {"theme": "engineeringresumes"},
    }


def _selection(highlight_order, keywords=None):
    return {
        "selected_experience": [
            {"index": 0, "highlight_order": highlight_order, "match_reason": "x"},
            {"index": 1, "highlight_order": [0], "match_reason": "x"},
        ],
        "selected_projects": [],
        "selected_skills_indices": [],
        "summary_index": 0,
        "keywords_detected": keywords or [],
    }


# ---------------------------------------------------------------------------
# src/achievements.py — unidades
# ---------------------------------------------------------------------------
def test_variant_status_ausente_es_approved():
    assert variant_status({}) == "approved"
    assert variant_status({"status": "pending"}) == "pending"
    assert variant_status({"status": "aprobado"}) == "approved"


def test_normalize_angles_acepta_str_y_lista():
    assert normalize_angles({"angle": "liderazgo"}) == ["liderazgo"]
    assert normalize_angles({"angle": ["liderazgo", "escala"]}) == ["liderazgo", "escala"]
    assert normalize_angles({}) == []
    assert normalize_angles({"angle": 42}) == []


def test_representative_variant_max_used_count():
    ach = _achievement(
        "a",
        [
            _variant("v0", "texto", used_count=2),
            _variant("v5", "texto", used_count=5),
            _variant("v1", "texto", used_count=1),
        ],
    )
    assert representative_variant(ach)["id"] == "v5"


def test_representative_variant_empate_por_created_at_mas_reciente():
    ach = _achievement(
        "a",
        [
            _variant("v_old", "texto", used_count=4, created_at="2024-01-01"),
            _variant("v_new", "texto", used_count=4, created_at="2024-05-01"),
        ],
    )
    assert representative_variant(ach)["id"] == "v_new"


def test_representative_variant_ignora_pending_y_deprecated():
    ach = _achievement(
        "a",
        [
            _variant("v_pending", "texto", status="pending", used_count=99),
            _variant("v_dep", "texto", status="deprecated", used_count=99),
            _variant("v_ok", "texto", used_count=1),
        ],
    )
    assert representative_variant(ach)["id"] == "v_ok"


def test_representative_variant_sin_approved_devuelve_none():
    ach = _achievement("a", [_variant("v", "texto", status="pending")])
    assert representative_variant(ach) is None


def test_index_text_cae_a_la_primera_variante_sin_approved():
    ach = _achievement("a", [_variant("v", "texto pending", status="pending")])
    assert index_text(ach) == "texto pending"


def test_index_text_vacio_sin_variantes():
    assert index_text(_achievement("a", [])) == ""


def test_resolve_variant_text_por_angulo_preferido():
    ach = _achievement(
        "a",
        [
            _variant("v_tecnico", "texto técnico", used_count=7, angle="impacto_tecnico"),
            _variant("v_lider", "texto liderazgo", used_count=3, angle="liderazgo"),
        ],
    )
    assert resolve_variant_text(ach, "liderazgo") == "texto liderazgo"
    assert resolve_variant_text(ach, "escala") == "texto técnico"  # sin match → representativa


def test_resolve_variant_text_sin_angulo_usa_representativa():
    ach = _achievement(
        "a",
        [
            _variant("v1", "texto uno", used_count=1),
            _variant("v2", "texto dos", used_count=9),
        ],
    )
    assert resolve_variant_text(ach) == "texto dos"


def test_resolve_variant_text_sin_approved_devuelve_none():
    ach = _achievement("a", [_variant("v", "texto", status="pending")])
    assert resolve_variant_text(ach) is None
    assert resolve_variant_text(ach, "liderazgo") is None


def test_approved_variant_texts_solo_aprobadas():
    ach = _achievement(
        "a",
        [
            _variant("v1", "aprobada", used_count=2),
            _variant("v2", "pendiente", status="pending"),
            _variant("v3", "deprecated", status="deprecated"),
        ],
    )
    assert approved_variant_texts(ach) == ["aprobada"]


def test_facts_corpus_parts_solo_action_y_tools():
    ach = _achievement(
        "a",
        [_variant("v", "texto")],
        facts={
            "action": "Diseñé un sistema",
            "tools": ["Java", "", 42, "PostgreSQL"],
            "scope": "equipo de 4",  # fuera del corpus
        },
    )
    assert facts_corpus_parts(ach) == ["Diseñé un sistema", "Java", "PostgreSQL"]


def test_entry_bullet_slots_orden_achievements_luego_legacy():
    entry = {
        "highlights": ["legacy uno", "legacy dos"],
        "achievements": [_achievement("a1", [_variant("v", "texto ach")])],
    }
    slots = entry_bullet_slots(entry)
    assert [s["kind"] for s in slots] == ["achievement", "legacy", "legacy"]
    assert slots[0]["text"] == "texto ach"
    assert slots[1]["text"] == "legacy uno"
    assert slots[2]["text"] == "legacy dos"


def test_entry_bullet_slots_ignora_highlights_no_strings_y_achievements_vacios():
    entry = {
        "highlights": ["ok", {"text": "roto"}, "", None],
        "achievements": ["no soy dict", _achievement("sin_variantes", [])],
    }
    slots = entry_bullet_slots(entry)
    assert [s["kind"] for s in slots] == ["legacy"]
    assert slots[0]["text"] == "ok"


def test_resolve_slot_text_por_kind():
    assert resolve_slot_text({"kind": "legacy", "text": "hola"}) == "hola"
    ach = _achievement("a", [_variant("v", "texto", used_count=5)])
    slot = {"kind": "achievement", "achievement": ach, "text": "texto"}
    assert resolve_slot_text(slot) == "texto"
    assert resolve_slot_text(slot, "liderazgo") == "texto"


# ---------------------------------------------------------------------------
# Validación de estructura
# ---------------------------------------------------------------------------
def test_validate_achievements_structure_master_valido(master_achievements):
    assert validate_master_cv_structure(master_achievements) == []


def test_validate_rechaza_highlights_y_achievements_juntos():
    master = {
        "cv": {
            "sections": {
                "experience": [
                    {
                        "company": "X",
                        "highlights": ["legacy"],
                        "achievements": [_achievement("a", [_variant("v", "texto")])],
                    }
                ]
            }
        }
    }
    errores = validate_master_cv_structure(master)
    assert len(errores) == 1
    assert "a la vez" in errores[0]


def test_validate_rechaza_status_y_angulos_invalidos():
    ach = _achievement(
        "a",
        [_variant("v", "texto", status="aprobado", angle=["liderazgo", "escala", "escala"])],
    )
    master = {"cv": {"sections": {"experience": [{"company": "X", "achievements": [ach]}]}}}
    errores = validate_achievements_structure(master)
    mensajes = " | ".join(errores)
    assert "status inválido" in mensajes
    assert "3 ángulos" in mensajes


def test_validate_rechaza_variante_sin_texto_y_sin_id():
    master = {
        "cv": {
            "sections": {
                "experience": [
                    {
                        "company": "X",
                        "achievements": [
                            {"variants": [{"used_count": -1}], "facts": "no dict"}
                        ],
                    }
                ]
            }
        }
    }
    errores = validate_achievements_structure(master)
    mensajes = " | ".join(errores)
    assert "falta el `id` (texto único" in mensajes
    assert "falta el `text`" in mensajes
    assert "falta el `id` de la variante" in mensajes
    assert "used_count" in mensajes
    assert "achievements[0] debe ser" not in mensajes  # el dict existe, el error es interno


# ---------------------------------------------------------------------------
# Merge: resolución de slots al target
# ---------------------------------------------------------------------------
def test_build_target_cv_resuelve_variante_representativa(master_achievements, config):
    target = build_target_cv(master_achievements, _selection([0]), config, job_description="")
    entrada = target["cv"]["sections"]["experience"][0]
    assert entrada["highlights"] == [
        "Diseñé un sistema de facturación con Java y Spring Boot."
    ]
    assert "achievements" not in entrada


def test_build_target_cv_preserva_orden_de_slots(master_achievements, config):
    target = build_target_cv(master_achievements, _selection([2, 0, 1]), config, job_description="")
    entrada = target["cv"]["sections"]["experience"][0]
    assert entrada["highlights"] == [
        "Desarrollé pipelines de CI/CD con GitHub Actions.",  # slot 2: ach_3
        "Diseñé un sistema de facturación con Java y Spring Boot.",  # slot 0: rep de ach_1
        "Reduje incidentes en producción un 30%.",  # slot 1: rep de ach_2
    ]


def test_build_target_cv_metadata_variantes_por_bullet(master_achievements, config):
    target = build_target_cv(master_achievements, _selection([0, 1, 2]), config, job_description="")
    entrada = target["cv"]["sections"]["experience"][0]
    assert entrada["_src_slot_map"] == [0, 1, 2]
    assert entrada["_src_variant_map"] == {
        "0": {
            "ach_id": "ach_1",
            "variant_id": "var_1a",
            "angle": "impacto_tecnico",
            "text": "Diseñé un sistema de facturación con Java y Spring Boot.",
        },
        "1": {
            "ach_id": "ach_2",
            "variant_id": "var_2a",
            "angle": "",
            "text": "Reduje incidentes en producción un 30%.",
        },
        "2": {
            "ach_id": "ach_3",
            "variant_id": "var_3a",
            "angle": "calidad_testing",
            "text": "Desarrollé pipelines de CI/CD con GitHub Actions.",
        },
    }


def test_build_target_cv_metadata_respeta_orden_reordenado(master_achievements, config):
    target = build_target_cv(master_achievements, _selection([2, 0, 1]), config, job_description="")
    entrada = target["cv"]["sections"]["experience"][0]
    assert entrada["_src_slot_map"] == [2, 0, 1]
    assert entrada["_src_variant_map"]["2"]["ach_id"] == "ach_3"
    assert entrada["_src_variant_map"]["2"]["variant_id"] == "var_3a"
    assert entrada["_src_variant_map"]["0"]["variant_id"] == "var_1a"


def test_build_target_cv_metadata_omite_slots_sin_emitir(config):
    # El ach pending no emite texto -> no entra ni al slot_map ni al variant_map.
    master = {
        "cv": {
            "sections": {
                "experience": [
                    {
                        "company": "X",
                        "achievements": [
                            _achievement("ach_A", [_variant("var_a", "Aprobada.")]),
                            _achievement(
                                "ach_B",
                                [_variant("var_b", "No aprobada.", status="pending")],
                            ),
                        ],
                    }
                ]
            }
        }
    }
    target = build_target_cv(master, _selection([0, 1]), config, job_description="")
    entrada = target["cv"]["sections"]["experience"][0]
    assert entrada["highlights"] == ["Aprobada."]
    assert entrada["_src_slot_map"] == [0]
    assert entrada["_src_variant_map"] == {
        "0": {"ach_id": "ach_A", "variant_id": "var_a", "angle": "", "text": "Aprobada."}
    }


def test_build_target_cv_entrada_legacy_sin_metadata(master_achievements, config):
    target = build_target_cv(master_achievements, _selection([0, 1, 2]), config, job_description="")
    entrada_legacy = target["cv"]["sections"]["experience"][1]
    assert "_src_slot_map" not in entrada_legacy
    assert "_src_variant_map" not in entrada_legacy


def test_strip_internal_keys_limpia_metadata_de_variantes(master_achievements, config, tmp_path):
    target = build_target_cv(master_achievements, _selection([0, 1, 2]), config, job_description="")
    path = tmp_path / "target.yaml"
    save_yaml(target, path)
    recargado = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert "_src_slot_map" not in str(recargado)
    assert "_src_variant_map" not in str(recargado)


def test_build_target_cv_entrada_legacy_no_cambia(master_achievements, config):
    target = build_target_cv(master_achievements, _selection([0]), config, job_description="")
    entrada_legacy = target["cv"]["sections"]["experience"][1]
    assert entrada_legacy["highlights"] == ["Bullet legacy uno."]
    assert entrada_legacy["company"] == "Empresa B"


# ---------------------------------------------------------------------------
# Traza de variante por bullet (historial)
# ---------------------------------------------------------------------------
def test_extract_bullet_variants_traza_en_orden_efectivo(master_achievements, config):
    target = build_target_cv(master_achievements, _selection([2, 0, 1]), config, job_description="")
    records = extract_bullet_variants(target)
    assert records == [
        {
            "section": "experience",
            "entry_index": 0,
            "ach_id": "ach_3",
            "variant_id": "var_3a",
            "angle": "calidad_testing",
            "text": "Desarrollé pipelines de CI/CD con GitHub Actions.",
        },
        {
            "section": "experience",
            "entry_index": 0,
            "ach_id": "ach_1",
            "variant_id": "var_1a",
            "angle": "impacto_tecnico",
            "text": "Diseñé un sistema de facturación con Java y Spring Boot.",
        },
        {
            "section": "experience",
            "entry_index": 0,
            "ach_id": "ach_2",
            "variant_id": "var_2a",
            "angle": "",
            "text": "Reduje incidentes en producción un 30%.",
        },
    ]


def test_extract_bullet_variants_omite_bullets_legacy(master_achievements, config):
    # La entrada 1 (Empresa B) es highlights legacy: no tiene variante y no
    # puede aparecer en la traza (los runs legacy no tienen clave bullet_variants).
    target = build_target_cv(master_achievements, _selection([0, 1, 2]), config, job_description="")
    records = extract_bullet_variants(target)
    assert [r["ach_id"] for r in records] == ["ach_1", "ach_2", "ach_3"]
    assert all(r["entry_index"] == 0 for r in records)


def test_extract_bullet_variants_sin_metadata_devuelve_vacio(config):
    target = {"cv": {"sections": {"experience": [{"company": "X", "highlights": ["a"]}]}}}
    assert extract_bullet_variants(target) == []


def test_build_target_cv_respeta_max_highlights_con_achievements(master_achievements, config):
    # La entrada 0 tiene 3 slots, pero el presupuesto de config es 2.
    selection = {
        "selected_experience": [
            {"index": 0, "highlight_order": [0, 1, 2], "match_reason": "x"},
        ],
        "selected_projects": [],
        "selected_skills_indices": [],
        "summary_index": 0,
        "keywords_detected": [],
    }
    target = build_target_cv(
        master_achievements,
        selection,
        {**config, "max_highlights_per_entry": 2},
        job_description="",
    )
    assert target["cv"]["sections"]["experience"][0]["highlights"] == [
        "Diseñé un sistema de facturación con Java y Spring Boot.",
        "Reduje incidentes en producción un 30%.",
    ]


def test_build_target_cv_achievement_solo_pending_se_ignora(master_achievements, config):
    master = {
        "cv": {
            "sections": {
                "experience": [
                    {
                        "company": "X",
                        "achievements": [
                            _achievement("a", [_variant("v", "no aprobada", status="pending")])
                        ],
                    }
                ]
            }
        }
    }
    target = build_target_cv(master, _selection([0]), config, job_description="")
    assert target["cv"]["sections"]["experience"][0]["highlights"] == []


def test_build_target_cv_order_invalido_cae_a_primeros_resolubles(master_achievements, config):
    # order apunta solo al slot pending (índice 3 no existe; el 0 es pending
    # en un master de un solo ach pending) -> fallback a los resolubles.
    master = {
        "cv": {
            "sections": {
                "experience": [
                    {
                        "company": "X",
                        "achievements": [
                            _achievement("a1", [_variant("v1", "resoluble", used_count=3)]),
                            _achievement("a2", [_variant("v2", "pending", status="pending")]),
                        ],
                    }
                ]
            }
        }
    }
    selection = {
        "selected_experience": [{"index": 0, "highlight_order": [1], "match_reason": "x"}],
        "selected_projects": [],
        "selected_skills_indices": [],
        "summary_index": 0,
        "keywords_detected": [],
    }
    target = build_target_cv(master, selection, config, job_description="")
    assert target["cv"]["sections"]["experience"][0]["highlights"] == ["resoluble"]


def test_apply_entry_selection_stripea_achievements_de_entradas_excluidas_por_max_entries(
    master_achievements, config
):
    result = _apply_entry_selection(
        master_achievements["cv"]["sections"]["experience"],
        [
            {"index": 0, "highlight_order": [0], "match_reason": "x"},
            {"index": 1, "highlight_order": [0], "match_reason": "x"},
            {"index": 0, "highlight_order": [0], "match_reason": "x"},
        ],
        max_entries=2,
        max_highlights=4,
        source_section="experience",
    )
    assert len(result) == 2
    assert all("achievements" not in e for e in result)


def test_save_yaml_persiste_achievements_sin_strippear(master_achievements, tmp_path):
    path = tmp_path / "master.yaml"
    save_yaml(master_achievements, path)
    recargado = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert recargado["cv"]["sections"]["experience"][0]["achievements"][0]["id"] == "ach_1"
    assert recargado["cv"]["sections"]["experience"][0]["achievements"][0]["variants"][0]["used_count"] == 7


# ---------------------------------------------------------------------------
# Invariante ATS: el corpus del master incluye hechos + variantes aprobadas
# ---------------------------------------------------------------------------
def test_keywords_se_verifican_contra_variante_no_representativa(master_achievements, config):
    # "equipo" solo está en var_1b (aprobada, no representativa) y en la oferta.
    verificadas = _build_verified_keywords(
        master_achievements, "Buscamos liderazgo en equipo.", ["equipo"], 10
    )
    assert verificadas == ["equipo"]


def test_keywords_se_verifican_contra_facts_tools(master_achievements, config):
    # "postgres" matchea "PostgreSQL" de facts.tools vía sinónimos.
    verificadas = _build_verified_keywords(
        master_achievements, "Buscamos expertos en postgres.", ["postgres"], 10
    )
    assert verificadas == ["postgres"]


def test_keywords_de_variante_pending_no_entran_al_corpus():
    master = {
        "cv": {
            "sections": {
                "experience": [
                    {
                        "company": "X",
                        "achievements": [
                            _achievement(
                                "a",
                                [_variant("v", "Automaticé deploys con terraform.", status="pending")],
                            )
                        ],
                    }
                ]
            }
        }
    }
    verificadas = _build_verified_keywords(master, "Buscamos terraform.", ["terraform"], 10)
    assert verificadas == []


def test_corpus_de_master_incluye_action_y_variantes_aprobadas(master_achievements):
    corpus = _master_cv_corpus(master_achievements)
    assert "facturación" in corpus  # variante aprobada
    assert "postgresql" in corpus  # facts.tools
    assert "incidentes" in corpus  # action de ach_2
    assert "sin verificar" not in corpus  # variante pending


# ---------------------------------------------------------------------------
# Selection: indexación de la variante representativa con el mismo índice de slot
# ---------------------------------------------------------------------------
def test_extract_bullets_indexa_variante_representativa(master_achievements):
    bullets = _extract_bullets_from_section(master_achievements, "experience")
    por_id = {b.id: b for b in bullets}
    assert por_id["experience_0_bullet_0"].text == (
        "Diseñé un sistema de facturación con Java y Spring Boot."
    )
    assert por_id["experience_0_bullet_1"].text == "Reduje incidentes en producción un 30%."
    assert por_id["experience_0_bullet_2"].text == (
        "Desarrollé pipelines de CI/CD con GitHub Actions."
    )
    assert por_id["experience_1_bullet_0"].text == "Bullet legacy uno."
    assert por_id["experience_1_bullet_1"].text == "Bullet legacy dos."
    assert [b.bullet_index for b in bullets] == [0, 1, 2, 0, 1]


def test_selection_y_merge_comparten_indices_de_slot(master_achievements, config):
    # Lo que indexa selection como bullet N es exactamente lo que merge
    # resuelve como highlight N del target, en cualquier orden.
    bullets = _extract_bullets_from_section(master_achievements, "experience")
    entrada_0 = [b for b in bullets if b.entry_index == 0]
    order = [b.bullet_index for b in sorted(entrada_0, key=lambda b: len(b.text), reverse=True)]

    selection = {
        "selected_experience": [
            {"index": 0, "highlight_order": order, "match_reason": "x"},
            {"index": 1, "highlight_order": [0], "match_reason": "x"},
        ],
        "selected_projects": [],
        "selected_skills_indices": [],
        "summary_index": 0,
        "keywords_detected": [],
    }
    target = build_target_cv(master_achievements, selection, config, job_description="")
    esperado = [b.text for b in sorted(entrada_0, key=lambda b: len(b.text), reverse=True)]
    assert target["cv"]["sections"]["experience"][0]["highlights"] == esperado


def test_extract_bullets_legacy_sin_achievements_no_cambia(master_cv):
    bullets = _extract_bullets_from_section(master_cv, "experience")
    assert [b.id for b in bullets] == [
        "experience_0_bullet_0",
        "experience_0_bullet_1",
        "experience_0_bullet_2",
        "experience_1_bullet_0",
        "experience_1_bullet_1",
    ]


# ---------------------------------------------------------------------------
# used_count: la variante que merge emite se registra
# ---------------------------------------------------------------------------
def test_resolve_variant_es_la_misma_eleccion_que_resolve_variant_text():
    ach = _achievement(
        "a",
        [
            _variant("v0", "texto técnico", used_count=1, angle="impacto_tecnico"),
            _variant("v1", "texto liderazgo", used_count=5, angle="liderazgo"),
        ],
    )
    # Sin ángulo preferido → representativa (mayor used_count).
    assert resolve_variant(ach)["id"] == "v1"
    assert resolve_variant_text(ach) == "texto liderazgo"
    # Con ángulo preferido → la que matchea, aunque no sea la representativa.
    assert resolve_variant(ach, "impacto_tecnico")["id"] == "v0"
    assert resolve_variant_text(ach, "impacto_tecnico") == "texto técnico"
    # Sin approved → None.
    solo_pending = _achievement("b", [_variant("v2", "sin revisar", status="pending")])
    assert resolve_variant(solo_pending) is None
    assert resolve_slot_text({"kind": "achievement", "achievement": solo_pending}) is None


def test_resolve_slot_with_variant_reporta_el_id_emitido():
    ach = _achievement("a", [_variant("v1", "texto", used_count=1), _variant("v2", "otro", used_count=9)])
    texto, variante = resolve_slot_with_variant({"kind": "achievement", "achievement": ach})
    assert texto == "otro"
    assert variante["id"] == "v2"
    # Legacy: nunca reporta variante.
    texto2, variante2 = resolve_slot_with_variant({"kind": "legacy", "text": "bullet"})
    assert texto2 == "bullet"
    assert variante2 is None


def test_apply_variant_usage_suma_solo_variantes_existentes():
    master = {
        "cv": {
            "sections": {
                "experience": [
                    {
                        "company": "X",
                        "achievements": [
                            _achievement("a", [_variant("v_activa", "texto", used_count=2)]),
                        ],
                    }
                ]
            }
        }
    }
    actualizadas = apply_variant_usage(master, {"v_activa": 3, "v_borrada": 5})
    variant = master["cv"]["sections"]["experience"][0]["achievements"][0]["variants"][0]
    assert variant["used_count"] == 5
    assert actualizadas == 1


def test_build_target_cv_registra_variantes_emitidas(master_achievements, config):
    usage: dict = {}
    selection = _selection([0, 1, 2])
    target = build_target_cv(
        master_achievements, selection, config, job_description="", variant_usage=usage
    )
    # Cada achievement de la entrada 0 emite su variante representativa.
    assert usage == {"var_1a": 1, "var_2a": 1, "var_3a": 1}
    assert target["cv"]["sections"]["experience"][1]["highlights"] == ["Bullet legacy uno."]


def test_build_target_cv_sin_usage_no_cambia_comportamiento(master_achievements, config):
    selection = _selection([0, 1, 2])
    target = build_target_cv(master_achievements, selection, config, job_description="")
    assert "highlights" in target["cv"]["sections"]["experience"][0]


def test_build_target_cv_usa_preferred_angle_del_item(master_achievements, config):
    # ach_1 tiene var_1a (impacto_tecnico, usada 7) y var_1b (liderazgo,
    # usada 3): con ángulo preferido "liderazgo" el target emite var_1b.
    selection = _selection([0, 1, 2])
    selection["selected_experience"][0]["preferred_angles"] = {"0": "liderazgo"}
    target = build_target_cv(master_achievements, selection, config, job_description="")
    highlights = target["cv"]["sections"]["experience"][0]["highlights"]
    assert "Lideré el diseño" in highlights[0]
    assert "Diseñé un sistema de facturación con Java" not in highlights[0]


def test_build_target_cv_angulo_sin_match_cae_a_representativa(master_achievements, config):
    # Sin variante con ese ángulo -> fallback a la representativa.
    usage: dict = {}
    selection = _selection([0, 1, 2])
    selection["selected_experience"][0]["preferred_angles"] = {"0": "vision_producto"}
    target = build_target_cv(
        master_achievements, selection, config, job_description="", variant_usage=usage
    )
    highlights = target["cv"]["sections"]["experience"][0]["highlights"]
    assert "Diseñé un sistema de facturación con Java" in highlights[0]
    assert usage["var_1a"] == 1  # el fallback también registra el id emitido