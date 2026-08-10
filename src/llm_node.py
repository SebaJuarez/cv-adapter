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
from typing import Any, Dict, Optional

from .config import load_config
from .prompts import build_selection_schema, build_system_prompt
from .retrieval.keywords import _count_keyword_occurrences, extract_keywords
from .retrieval.sparse import get_synonym_variants
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

    selected_experience = []
    for item in ir_selection.get("selected_experience", []):
        idx = item.get("index")
        if idx is not None and 0 <= idx < len(sections.get("experience", [])):
            entry = sections["experience"][idx]
            highlights = entry.get("highlights", [])
            h_text = "\n    - ".join(h for h in highlights if isinstance(h, str))
            selected_experience.append(
                f"  [{idx}] {entry.get('company', '')} - {entry.get('position', '')}\n    - {h_text}"
            )

    selected_projects = []
    for item in ir_selection.get("selected_projects", []):
        idx = item.get("index")
        if idx is not None and 0 <= idx < len(sections.get("projects", [])):
            entry = sections["projects"][idx]
            highlights = entry.get("highlights", [])
            h_text = "\n    - ".join(h for h in highlights if isinstance(h, str))
            selected_projects.append(
                f"  [{idx}] {entry.get('name', '')}\n    - {h_text}"
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
        llm_reasons = {item["index"]: item.get("match_reason", "")
                       for item in llm_output.get(section_key, [])
                       if "index" in item}
        entries = sections_by_key.get(entries_key, [])
        for item in final_selection.get(section_key, []):
            idx = item["index"]
            if idx not in llm_reasons or not llm_reasons[idx]:
                continue
            highlights = entries[idx].get("highlights", []) if 0 <= idx < len(entries) else []
            bullet_text = " ".join(h for h in highlights if isinstance(h, str))
            if _verify_match_reason(llm_reasons[idx], bullet_text, job_description):
                item["match_reason"] = llm_reasons[idx]
            # si no pasa el guardarail, se deja el match_reason de IR intacto

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