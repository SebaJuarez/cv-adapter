"""Llamada al LLM (Ollama local o API remota compatible con OpenAI) con salida estructurada.

Ahora el pipeline tiene DOS fases:
1. Fase IR (Information Retrieval): SelectionEngine selecciona bullets/experiencias
   usando BM25 + embeddings + cross-encoder. Es rápido, determinístico, y corre local.
   También resuelve el summary_index y las keywords ATS candidatas.
2. Fase LLM Estratégica: el LLM solo recibe el JD + bullets ya seleccionados.
   Su única tarea es mejorar los match_reasons (redacción en lenguaje natural),
   siempre verificados contra bullet + JD (ver _verify_match_reason). El
   contexto se reduce de ~15K tokens a ~2K tokens.

Clave anti-alucinación: el LLM NUNCA genera el YAML final. Solo devuelve
índices que apuntan a contenido que YA existe en master_cv.yaml.

El proveedor se elige con config["llm_provider"]: "ollama" (modelo local) u
"openai" (cualquier API compatible con OpenAI: OpenAI, OpenRouter, Groq, etc.).
"""
import json
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

from .achievements import VALID_ANGLES, entry_bullet_slots
from .config import load_config
from .prompts import build_selection_schema, build_system_prompt
from .retrieval.keywords import _count_keyword_occurrences, extract_keywords
from .retrieval.sparse import get_synonym_variants, keyword_in_text
from .selection import get_selection_engine


def _verify_match_reason(llm_reason: str, bullet_text: str, jd_text: str) -> bool:
    """Guardarail anti-alucinación para el match_reason que redacta el LLM.

    A diferencia de las keywords ATS (que ya se verifican contra el master_cv
    en merge.py vía _build_verified_keywords), el texto libre de
    `match_reason` no pasaba por ningún chequeo — era la única superficie
    donde el LLM podía generar texto visible sin verificación, algo
    inconsistente con el resto del pipeline.

    Chequeo deliberadamente acotado: si el LLM menciona una tecnología/
    keyword técnica que NO está ni en el bullet ni en el JD (ni en alguna
    variante sinónima), se rechaza el texto completo y se usa el
    match_reason determinístico de IR en su lugar. No intenta validar
    matices de redacción, solo el riesgo real: que el LLM invente una
    tecnología o herramienta que el candidato nunca mencionó.
    """
    mentioned_keywords, _ = extract_keywords(llm_reason)
    if not mentioned_keywords:
        return True  # No menciona ninguna tecnología puntual, no hay nada que verificar

    # Texto crudo: _count_keyword_occurrences normaliza por dentro, pero los
    # términos con separadores (c++, next.js) necesitan el texto original.
    context = bullet_text + " " + jd_text
    for kw in mentioned_keywords:
        variants = get_synonym_variants(kw)
        if not any(_count_keyword_occurrences(context, v) > 0 for v in variants):
            return False
    return True


def _call_ollama(system_prompt: str, user_prompt: str, schema: Dict[str, Any], config: Dict[str, Any]) -> Dict[str, Any]:
    raw_content = ""
    try:
        # Import dentro del try: si el paquete no está instalado, el
        # ImportError se convierte en RuntimeError y el pipeline degrada
        # con gracia a la selección IR pura (ver generate_selection).
        import ollama

        response = ollama.chat(
            model=config["ollama_model"],
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            format=schema,
            options={"temperature": 0, "num_ctx": 8192},
        )
        raw_content = response["message"]["content"]
        return json.loads(raw_content)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"El LLM no devolvió JSON válido: {e}\nContenido crudo:\n{raw_content}") from e
    except Exception as e:
        raise RuntimeError(f"Error llamando a Ollama ({config['ollama_model']}): {e}") from e


def _call_openai(system_prompt: str, user_prompt: str, schema: Dict[str, Any], config: Dict[str, Any]) -> Dict[str, Any]:
    """Llama a una API remota compatible con OpenAI.

    Usa structured outputs (response_format json_schema) si el proveedor los
    soporta; si los rechaza (400), reintenta con chat simple y parsea el JSON
    del contenido — el mismo contrato que Ollama. La API key se pasa como
    parámetro del cliente, sin tocar variables de entorno.
    """
    api_key = config.get("openai_api_key", "")
    if not api_key:
        raise RuntimeError(
            "No hay API key configurada. Andá a Configuración y completá 'API key de OpenAI' "
            "(o usá llm_provider=ollama para el modelo local)."
        )

    # Import dentro del try: si el paquete no está instalado, el ImportError
    # se convierte en RuntimeError y el pipeline degrada con gracia.
    try:
        from openai import OpenAI
    except ImportError as e:
        raise RuntimeError(
            "El paquete 'openai' no está instalado. Corré: pip install openai"
        ) from e

    base_url = config.get("openai_base_url", "") or None
    client = OpenAI(api_key=api_key, base_url=base_url)
    model = config["openai_model"]
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    def _parse(content: str) -> Dict[str, Any]:
        return json.loads(content)

    raw_content = ""
    try:
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0,
            response_format={
                "type": "json_schema",
                "json_schema": {"name": "selection", "schema": schema, "strict": False},
            },
        )
        raw_content = response.choices[0].message.content
        return _parse(raw_content)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"El LLM no devolvió JSON válido: {e}\nContenido crudo:\n{raw_content}") from e
    except Exception as e:
        # Algunos proveedores compatibles rechazan response_format (400);
        # reintento con chat simple y parseo el JSON como hace Ollama.
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0,
            )
            raw_content = response.choices[0].message.content
            return _parse(raw_content)
        except json.JSONDecodeError as e2:
            raise RuntimeError(
                f"El LLM no devolvió JSON válido: {e2}\nContenido crudo:\n{raw_content}"
            ) from e2
        except Exception as e2:
            raise RuntimeError(f"Error llamando a la API remota ({model}): {e2}") from e2


def _call_llm(system_prompt: str, user_prompt: str, schema: Dict[str, Any], config: Dict[str, Any]) -> Dict[str, Any]:
    """Despacha la llamada al LLM según config['llm_provider']."""
    provider = config.get("llm_provider", "ollama")
    if provider == "openai":
        return _call_openai(system_prompt, user_prompt, schema, config)
    return _call_ollama(system_prompt, user_prompt, schema, config)


# Schema mínimo para HyDE (P3.1): un solo campo de texto libre.
_HYDE_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {"hypothetical_document": {"type": "string"}},
    "required": ["hypothetical_document"],
}


def _generate_hyde_query(job_description: str, config: Dict[str, Any], timeout: float = 15.0) -> Optional[str]:
    """Redacta el CV hipotético del candidato ideal (HyDE, P3.1).

    El LLM escribe cómo sería el CV del candidato perfecto para la oferta:
    un texto con el vocabulario del JD que el canal denso puede comparar
    contra los bullets reales del master (que suelen decir lo mismo con
    otras palabras).

    Defensivo por diseño: cualquier fallo (proveedor caído, timeout, JSON
    inválido, campo vacío) devuelve None y el pipeline sigue con el JD real
    como única query. El timeout se aplica con un ThreadPoolExecutor porque
    ni Ollama ni OpenAI exponen timeout por llamada de forma portable.
    """
    system_prompt = (
        "Sos un redactor de CVs experto en ATS. Dada la oferta laboral, redactá "
        "el CV HIPOÉTICO del candidato ideal para ella: entre 6 y 10 bullets de "
        "experiencia y una lista de skills, usando exactamente el vocabulario y "
        "la jerga técnica de la oferta. No inventes nombres de empresas ni "
        "personas: solo habilidades y logros genéricos pero plausibles."
    )
    user_prompt = (
        "### oferta laboral ###\n"
        f"{job_description}\n\n"
        "Devolvé SOLO el JSON con el campo hypothetical_document: el texto del "
        "CV hipotético en texto plano (sin markdown ni listas con guiones)."
    )
    pool = None
    try:
        pool = ThreadPoolExecutor(max_workers=1)
        future = pool.submit(_call_llm, system_prompt, user_prompt, _HYDE_SCHEMA, config)
        result = future.result(timeout=timeout)
        text = (result or {}).get("hypothetical_document", "")
        return text.strip() or None
    except Exception:
        # Timeout, RuntimeError del proveedor, JSON inválido… todo degrada
        # con gracia: sin HyDE la selección es la de siempre.
        return None
    finally:
        if pool is not None:
            pool.shutdown(wait=False, cancel_futures=True)


# Schema de extracción de hechos (botón "enriquecer este bullet", F2):
# facts estructurados a partir de un bullet legacy, con verificación
# contra el texto fuente (ver _verify_facts).
_FACTS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "action": {"type": "string"},
        "tools": {"type": "array", "items": {"type": "string"}},
        "scope": {"type": "string"},
        "outcomes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"metric": {"type": "string"}, "value": {"type": "string"}},
                "required": ["metric", "value"],
            },
        },
    },
    "required": ["action", "tools", "scope", "outcomes"],
}

_EMPTY_FACTS: Dict[str, Any] = {"action": "", "tools": [], "scope": "", "outcomes": []}


def _verify_facts(facts: Dict[str, Any], bullet_text: str) -> Dict[str, Any]:
    """Guardarail anti-alucinación de la extracción de facts (doc funcional §1):

    cada tecnología propuesta debe aparecer en el texto fuente del bullet
    (o una variante sinónima), y cada outcome debe tener su métrica o su
    valor presentes en el texto. Lo que no se puede verificar se descarta
    en silencio — el LLM estructura, jamás aporta hechos nuevos.

    `action` y `scope` son prosa y quedan como el LLM las redactó: el
    usuario las ve y edita antes de guardar (nunca se auto-guarda).
    """
    clean: Dict[str, Any] = {
        "action": "",
        "tools": [],
        "scope": "",
        "outcomes": [],
    }
    if not isinstance(facts, dict):
        return clean

    text = bullet_text or ""
    action = facts.get("action")
    if isinstance(action, str) and action.strip():
        clean["action"] = action.strip()
    scope = facts.get("scope")
    if isinstance(scope, str) and scope.strip():
        clean["scope"] = scope.strip()

    for tool in facts.get("tools", []):
        if isinstance(tool, str) and tool.strip() and keyword_in_text(tool.strip(), text):
            clean["tools"].append(tool.strip())

    text_low = text.lower()
    for outcome in facts.get("outcomes", []):
        if not isinstance(outcome, dict):
            continue
        metric = outcome.get("metric")
        value = outcome.get("value")
        metric_ok = (
            isinstance(metric, str) and metric.strip() and metric.strip().lower() in text_low
        )
        # El LLM suele normalizar el signo ("-60%" vs "en un 60%"): se
        # verifica el valor sin el signo inicial y se conserva el original.
        value_norm = (
            value.strip().lower().lstrip("+-") if isinstance(value, str) else ""
        )
        value_ok = bool(value_norm) and value_norm in text_low
        if metric_ok or value_ok:
            clean["outcomes"].append(
                {
                    "metric": metric.strip() if metric_ok else "",
                    "value": value.strip() if value_ok else "",
                }
            )

    return clean


def extract_achievement_facts(
    bullet_text: str, config: Dict[str, Any], timeout: float = 10.0
) -> Dict[str, Any]:
    """Estructura un bullet legacy en `facts` (acción, herramientas, alcance,
    resultados medibles) para el botón "enriquecer este bullet" (F2).

    Defensivo por diseño: cualquier fallo (proveedor caído, timeout, JSON
    inválido) devuelve facts vacíos y el usuario completa los campos a mano
    — nunca se inventa contenido, y nunca se bloquea el editor.
    """
    if not bullet_text or not bullet_text.strip():
        return dict(_EMPTY_FACTS)

    system_prompt = (
        "Sos un estructurador de logros de CV. Dado un bullet, separás los "
        "HECHOS verificables: qué se hizo, con qué herramientas, a qué "
        "alcance y qué resultados medibles. Regla inquebrantable: SOLO podés "
        "usar información que aparezca textualmente en el bullet. NUNCA "
        "inventes tecnologías, métricas, equipos ni clientes. Si algo no "
        "aparece en el texto, dejalo vacío."
    )
    user_prompt = (
        "### bullet ###\n"
        f"{bullet_text}\n\n"
        "Devolvé SOLO el JSON con: action = qué hiciste en una frase (verbo + "
        "objeto); tools = tecnologías/herramientas mencionadas en el texto; "
        "scope = alcance (personas, clientes, sistema, proceso); outcomes = "
        "resultados medibles del texto como lista de {metric, value} (metric = "
        "qué se midió, value = el número/unidad tal cual aparece)."
    )
    pool = None
    try:
        pool = ThreadPoolExecutor(max_workers=1)
        future = pool.submit(_call_llm, system_prompt, user_prompt, _FACTS_SCHEMA, config)
        result = future.result(timeout=timeout)
        return _verify_facts(result or {}, bullet_text)
    except Exception:
        # Timeout, RuntimeError del proveedor, JSON inválido… todo degrada
        # con gracia: el editor queda con los campos vacíos para completar.
        return dict(_EMPTY_FACTS)
    finally:
        if pool is not None:
            pool.shutdown(wait=False, cancel_futures=True)


# F6 (doc §6.6): la generación de variantes devuelve `text` + `tech_terms`
# (los términos que el modelo usó en su redacción, para verificar contra el
# logro). Schema estricto: si el modelo no lista términos, no se rompe nada;
# si inventa término sin respaldo, se marca, jamás se descarta en silencio.
_VARIANT_GEN_SCHEMA = {
    "type": "object",
    "properties": {
        "text": {"type": "string"},
        "tech_terms": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["text", "tech_terms"],
    "additionalProperties": False,
}


def _format_facts_for_prompt(facts: Dict[str, Any]) -> str:
    """Facts de un logro como texto legible para el prompt de redacción."""
    parts = []
    if not isinstance(facts, dict):
        return "(sin hechos estructurados)"
    action = facts.get("action")
    if isinstance(action, str) and action.strip():
        parts.append(f"Acción: {action.strip()}")
    tools = facts.get("tools")
    if isinstance(tools, list) and tools:
        parts.append(
            "Herramientas: "
            + ", ".join(t for t in tools if isinstance(t, str) and t.strip())
        )
    scope = facts.get("scope")
    if isinstance(scope, str) and scope.strip():
        parts.append(f"Alcance: {scope.strip()}")
    for outcome in facts.get("outcomes") or []:
        if not isinstance(outcome, dict):
            continue
        metric = outcome.get("metric")
        value = outcome.get("value")
        if isinstance(metric, str) and metric.strip():
            line = f"Resultado: {metric.strip()}"
            if isinstance(value, str) and value.strip():
                line += f" {value.strip()}"
            parts.append(line)
        elif isinstance(value, str) and value.strip():
            parts.append(f"Resultado: {value.strip()}")
    return "\n".join(parts) if parts else "(sin hechos estructurados)"


def _facts_corpus(facts: Dict[str, Any]) -> List[str]:
    """Partes de `facts` que respaldan términos técnicos (action + tools)."""
    parts = []
    if not isinstance(facts, dict):
        return parts
    action = facts.get("action")
    if isinstance(action, str) and action.strip():
        parts.append(action.strip())
    tools = facts.get("tools")
    if isinstance(tools, list):
        parts.extend(t.strip() for t in tools if isinstance(t, str) and t.strip())
    return parts


def generate_variant_text(
    angle: str,
    facts: Dict[str, Any],
    variant_texts: List[str],
    current_text: str = "",
    jd_snippet: str = "",
    config: Optional[Dict[str, Any]] = None,
    timeout: float = 30.0,
) -> Dict[str, Any]:
    """Genera una redacción nueva orientada a `angle` para un logro (F6).

    El LLM reescribe SOLO a partir de los hechos del logro (facts + variantes
    existentes + texto actual); el snippet del JD es contexto de énfasis,
    jamás una fuente de hechos. Devuelve `{text, unverified_terms}`: los
    términos técnicos que el modelo declara se verifican con
    `keyword_in_text` contra el corpus del logro (mismo verificador que las
    keywords ATS, soporta sinónimos); los que no están respaldados se listan
    para que el frontend los resalte — la variante jamás entra al master sin
    aprobación humana explícita.

    A diferencia de `extract_achievement_facts` (que degrada a vacío), acá los
    errores se propagan con mensaje legible: la UX pide mostrar el error del
    proveedor (toast con enlace a Configuración), no silenciarlo.
    """
    config = config or load_config()
    angle = (angle or "").strip().lower()
    if angle not in VALID_ANGLES:
        raise RuntimeError(
            f"Ángulo desconocido: '{angle}'. Válidos: {', '.join(VALID_ANGLES)}."
        )

    variant_texts = [t for t in (variant_texts or []) if isinstance(t, str) and t.strip()]
    corpus_parts = _facts_corpus(facts) + variant_texts
    if isinstance(current_text, str) and current_text.strip():
        corpus_parts.append(current_text.strip())
    if not corpus_parts:
        raise RuntimeError(
            "Este logro no tiene contenido para redactar (hechos y redacciones "
            "vacíos). Completá sus hechos en el editor de logros."
        )
    corpus_text = " ".join(corpus_parts)

    system_prompt = (
        "Sos un redactor de logros de CV. Reescribís el logro de un candidato "
        f"orientado al ángulo '{angle}', conservando exactamente los mismos hechos.\n"
        "Reglas inquebrantables:\n"
        "- SOLO podés usar información que aparezca en los HECHOS del logro o en sus "
        "redacciones existentes. NUNCA inventes tecnologías, métricas, equipos ni clientes.\n"
        "- El contexto de la oferta es solo para énfasis y tono; no es fuente de hechos.\n"
        "- En tech_terms listá cada tecnología o herramienta que menciones en tu "
        "redacción (incluidas las ya presentes en los hechos), para poder verificarlas."
    )
    user_prompt = (
        "### hechos del logro ###\n"
        f"{_format_facts_for_prompt(facts)}\n\n"
        "### redacciones existentes del logro ###\n"
        + ("\n".join(f"- {t}" for t in variant_texts) if variant_texts else "(ninguna)")
        + "\n\n### texto actual ###\n"
        + (current_text.strip() if isinstance(current_text, str) and current_text.strip() else "(ninguno)")
        + (
            "\n\n### contexto de la oferta (para énfasis, no para inventar hechos) ###\n"
            + jd_snippet.strip()
            if isinstance(jd_snippet, str) and jd_snippet.strip()
            else ""
        )
        + f"\n\nRedactá una variante orientada al ángulo '{angle}'. Devolvé SOLO el "
        "JSON: text = la redacción (una frase de 1 a 3 líneas, en español, sin "
        "viñeta); tech_terms = lista de tecnologías/herramientas mencionadas en "
        "tu redacción."
    )

    pool = None
    try:
        pool = ThreadPoolExecutor(max_workers=1)
        try:
            result = pool.submit(
                _call_llm, system_prompt, user_prompt, _VARIANT_GEN_SCHEMA, config
            ).result(timeout=timeout)
        except TimeoutError:
            raise RuntimeError(
                f"El proveedor tardó demasiado en generar la redacción ({int(timeout)}s). "
                "Probá de nuevo o cambiá de proveedor en Configuración."
            ) from None
    finally:
        if pool is not None:
            pool.shutdown(wait=False, cancel_futures=True)

    text = result.get("text")
    if not isinstance(text, str) or not text.strip():
        raise RuntimeError("El modelo devolvió una redacción vacía. Probá de nuevo.")
    terms = result.get("tech_terms")
    unverified = [
        t.strip()
        for t in terms
        if isinstance(t, str) and t.strip() and not keyword_in_text(t.strip(), corpus_text)
    ] if isinstance(terms, list) else []
    # Dedupe preservando orden (el modelo puede repetir términos).
    unverified = list(dict.fromkeys(unverified))
    return {"text": text.strip(), "unverified_terms": unverified}


def _build_strategic_prompt(
    master_cv: Dict[str, Any],
    job_description: str,
    ir_selection: Dict[str, Any],
    config: Dict[str, Any],
) -> str:
    """Construye el user prompt para la fase estratégica del LLM.

    El LLM ya no recibe TODO el CV. Solo recibe:
    - El JD completo.
    - Los bullets ya seleccionados por IR (resumen).
    """
    # Extraer bullets seleccionados para mostrar al LLM
    sections = master_cv.get("cv", {}).get("sections", {})

    def _format_entry_slots(entry: Dict[str, Any]) -> str:
        """Slots unificados con su índice (mismo orden que indexa IR y que
        resuelve merge). Los logros se marcan con su id para que el LLM
        pueda referir ángulos precisos (F2, preferred_angles)."""
        lines = []
        for slot_index, slot in enumerate(entry_bullet_slots(entry)):
            if not slot["text"]:
                continue
            if slot.get("kind") == "achievement":
                ach_id = (slot.get("achievement") or {}).get("id", "?")
                lines.append(f"    slot[{slot_index}] (logro {ach_id}) {slot['text']}")
            else:
                lines.append(f"    slot[{slot_index}] {slot['text']}")
        return "\n".join(lines)

    selected_experience = []
    for item in ir_selection.get("selected_experience", []):
        idx = item.get("index")
        if idx is not None and 0 <= idx < len(sections.get("experience", [])):
            entry = sections["experience"][idx]
            # Bullets unificados: highlights legacy o variante representativa
            # de cada achievement (mismo texto que indexa IR — D4).
            selected_experience.append(
                f"  [{idx}] {entry.get('company', '')} - {entry.get('position', '')}\n"
                + _format_entry_slots(entry)
            )

    selected_projects = []
    for item in ir_selection.get("selected_projects", []):
        idx = item.get("index")
        if idx is not None and 0 <= idx < len(sections.get("projects", [])):
            entry = sections["projects"][idx]
            selected_projects.append(
                f"  [{idx}] {entry.get('name', '')}\n" + _format_entry_slots(entry)
            )

    selected_skills = []
    for idx in ir_selection.get("selected_skills_indices", []):
        if 0 <= idx < len(sections.get("skills", [])):
            s = sections["skills"][idx]
            selected_skills.append(f"  [{idx}] {s.get('label', '')}: {s.get('details', '')}")

    return (
        "### job_description ###\n"
        f"{job_description}\n\n"
        "### experiencias seleccionadas por el motor de búsqueda ###\n"
        f"{'\n'.join(selected_experience)}\n\n"
        "### proyectos seleccionados por el motor de búsqueda ###\n"
        f"{'\n'.join(selected_projects)}\n\n"
        "### skills seleccionadas por el motor de búsqueda ###\n"
        f"{'\n'.join(selected_skills)}\n\n"
        "### ángulos válidos de logro (para preferred_angles) ###\n"
        f"{', '.join(VALID_ANGLES)}\n\n"
        "Devolvé SOLO el JSON de ajustes estratégicos según el schema."
    )


def generate_selection(
    master_cv: Dict[str, Any],
    job_description: str,
    config: Optional[Dict[str, Any]] = None,
    force: bool = False,
) -> Dict[str, Any]:
    """Pipeline completo: IR + LLM estratégico.

    1. SelectionEngine hace retrieval híbrido (rápido, determinístico) y
       resuelve summary_index + keywords ATS candidatas.
    2. LLM estratégico mejora los match_reasons (verificado anti-alucinación).
    3. Merge de ambas salidas: los índices de IR son inmutables.

    Con `force=True` se saltea el cache de selección (P0.1); la fase LLM
    estratégica corre igual en ambos casos (el cache guarda solo la fase IR).
    """
    config = config or load_config()

    # --- Fase 1: IR (rápido, determinístico) ---
    engine = get_selection_engine(config)
    ir_selection = engine.select(master_cv, job_description, use_cache=not force)

    # --- Fase 2: LLM Estratégico (liviano) ---
    system_prompt = build_system_prompt(config)
    schema = build_selection_schema(config)
    user_prompt = _build_strategic_prompt(master_cv, job_description, ir_selection, config)

    try:
        llm_output = _call_llm(system_prompt, user_prompt, schema, config)
    except RuntimeError:
        # Si el LLM falla, usamos solo la selección IR (graceful degradation)
        llm_output = {}

    # --- Merge: IR + LLM ---
    # El LLM SOLO puede mejorar los match_reasons; NUNCA puede sobreescribir
    # summary_index, keywords_detected ni los índices de
    # experiencia/proyectos/skills (todo eso lo determinó IR y es inmutable).
    final_selection = dict(ir_selection)

    # Match reasons: el LLM puede mejorar los que ya tiene IR, pero solo si
    # pasan el guardarail anti-alucinación (ver _verify_match_reason). Si
    # el LLM inventa una tecnología no presente ni en el bullet ni en el
    # JD, se descarta silenciosamente y queda el match_reason de IR.
    sections_by_key = master_cv.get("cv", {}).get("sections", {})
    for section_key, entries_key in [
        ("selected_experience", "experience"),
        ("selected_projects", "projects"),
    ]:
        llm_items = {item["index"]: item for item in llm_output.get(section_key, [])
                     if "index" in item}
        entries = sections_by_key.get(entries_key, [])
        for item in final_selection.get(section_key, []):
            idx = item["index"]
            llm_item = llm_items.get(idx)
            if not llm_item:
                continue
            llm_reason = llm_item.get("match_reason", "")
            highlights = entries[idx].get("highlights", []) if 0 <= idx < len(entries) else []
            bullet_text = " ".join(h for h in highlights if isinstance(h, str))
            if llm_reason and _verify_match_reason(llm_reason, bullet_text, job_description):
                item["match_reason"] = llm_reason
            # si no pasa el guardarail, se deja el match_reason de IR intacto

            # Ángulos preferidos por logro (F2): merge determinístico, el
            # LLM no puede elegir qué texto ver — solo el ángulo. Ángulos
            # inválidos o slots que no sean logros se descartan en silencio
            # (merge total: si nada sobrevive, no se setea la clave).
            preferred_angles = {}
            entry = entries[idx] if 0 <= idx < len(entries) else None
            for proposed in llm_item.get("preferred_angles") or []:
                if not isinstance(proposed, dict):
                    continue
                slot_index = proposed.get("slot_index")
                angle = proposed.get("angle")
                if (
                    isinstance(slot_index, int)
                    and isinstance(angle, str)
                    and angle in VALID_ANGLES
                    and entry is not None
                ):
                    slots = entry_bullet_slots(entry)
                    if 0 <= slot_index < len(slots) and slots[slot_index].get("kind") == "achievement":
                        preferred_angles[str(slot_index)] = angle
            if preferred_angles:
                item["preferred_angles"] = preferred_angles

    return final_selection


def generate_section_selection(
    master_cv: Dict[str, Any],
    job_description: str,
    section_name: str,
    config: Optional[Dict[str, Any]] = None,
    force: bool = False,
) -> Dict[str, Any]:
    """Igual que generate_selection, pero acotado a UNA sola sección.

    Usado por el botón 'Regenerar esta sección' de la UI.
    Ahora usa SelectionEngine.select_section() en vez del LLM para retrieval.
    Con `force=True` se saltea el cache de selección (P0.1).
    """
    config = config or load_config()

    # Fase IR para una sola sección (singleton, reutiliza modelos en memoria)
    engine = get_selection_engine(config)
    return engine.select_section(
        master_cv, job_description, section_name, use_cache=not force
    )