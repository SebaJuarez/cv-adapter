"""Extracción y verificación ATS de keywords técnicas.

Extrae keywords técnicas del JD y verifica cuáles están presentes en el
CV maestro vs el CV generado (target). Usado por el endpoint /api/generate
para devolver un keyword_report al frontend.

Nuevas features:
- Frecuencia de cada keyword en el JD (para priorizar las más mencionadas).
- Bigramas dinámicos: detecta pares de palabras técnicas que aparecen juntas.
- ATS Impact Score: score ponderado por frecuencia (no solo conteo binario).
"""

import re
from typing import Any, Dict, List, Set, Tuple

from .sparse import get_synonym_variants, keyword_in_text

# Diccionario curado de términos técnicos para detectar en JDs.
TECH_KEYWORDS = {
    # Cloud & Infra
    "aws", "azure", "gcp", "google cloud", "docker", "kubernetes", "k8s",
    "terraform", "ansible", "jenkins", "github actions", "gitlab ci",
    "circleci", "travis", "ci/cd", "devops", "sre", "nginx", "apache",
    "linux", "unix", "windows server", "vmware", "vagrant", "puppet",
    "chef", "prometheus", "grafana", "datadog", "new relic", "splunk",
    "elk", "elasticsearch", "logstash", "kibana", "cloudflare", "cdn",
    "vpc", "subnet", "load balancer", "alb", "nlb", "ec2", "ecs", "eks",
    "lambda", "s3", "rds", "dynamodb", "sqs", "sns", "route53", "iam",
    "cloudformation", "pulumi", "heroku", "netlify", "vercel", "firebase",
    # Lenguajes
    "python", "java", "javascript", "typescript", "js", "ts", "go", "golang",
    "rust", "c++", "c#", "csharp", "ruby", "php", "scala", "kotlin",
    "swift", "objective-c", "dart", "flutter", "perl", "r", "matlab",
    "shell", "bash", "powershell", "sql", "pl/sql", "t-sql", "vba",
    # Frameworks & Web
    "react", "vue", "angular", "svelte", "next.js", "nuxt", "django",
    "flask", "fastapi", "spring", "spring boot", "hibernate", "jpa",
    "express", "nestjs", "rails", "laravel", "symfony", "asp.net",
    "blazor", "redux", "mobx", "zustand", "react query", "tanstack",
    "tailwind", "bootstrap", "material ui", "mui", "antd", "sass", "less",
    "webpack", "vite", "rollup", "parcel", "babel", "eslint", "prettier",
    # Bases de datos
    "postgresql", "postgres", "mysql", "mariadb", "sqlite", "mongodb",
    "redis", "cassandra", "couchdb", "neo4j", "dynamodb", "firebase",
    "oracle", "db2", "sql server", "clickhouse", "timescaledb", "influxdb",
    "elasticsearch", "solr", "rabbitmq", "kafka", "activemq", "mqtt",
    # Data & ML
    "pandas", "numpy", "scipy", "scikit-learn", "sklearn", "tensorflow",
    "tf", "pytorch", "keras", "xgboost", "lightgbm", "catboost", "mlflow",
    "kubeflow", "airflow", "prefect", "dagster", "spark", "pyspark",
    "hadoop", "hive", "presto", "trino", "dbt", "snowflake", "bigquery",
    "redshift", "tableau", "power bi", "looker", "metabase", "superset",
    "jupyter", "matplotlib", "seaborn", "plotly", "opencv", "nlp",
    "hugging face", "transformers", "llm", "langchain", "llamaindex",
    "openai", "anthropic", "vector db", "pinecone", "weaviate",
    "chroma", "faiss", "milvus", "qdrant",
    # Mobile
    "android", "ios", "react native", "ionic", "cordova", "capacitor",
    "xamarin", "unity", "unreal engine",
    # Testing & QA
    "jest", "mocha", "cypress", "playwright", "selenium", "junit",
    "testng", "pytest", "unittest", "cucumber", "gherkin", "tdd", "bdd",
    "sonarqube", "coverage", "integration testing", "e2e", "unit testing",
    # Metodologías & Soft
    "agile", "scrum", "kanban", "xp", "lean", "safe", "waterfall",
    "jira", "confluence", "trello", "notion", "miro", "figma",
    "git", "github", "gitlab", "bitbucket", "svn", "mercurial",
    "rest", "restful", "graphql", "grpc", "soap", "openapi", "swagger",
    "oauth", "oidc", "saml", "jwt", "ldap", "sso", "mfa", "2fa",
    "encryption", "tls", "ssl", "https", "penetration testing", "owasp",
    "microservices", "soa", "event-driven", "serverless", "monolith",
    "cqrs", "event sourcing", "ddd", "clean architecture", "hexagonal",
    "solid", "dry", "kiss", "design patterns", "oop", "functional programming",
    "concurrency", "parallelism", "async", "multithreading", "distributed systems",
    "high availability", "fault tolerance", "disaster recovery", "backup",
    "monitoring", "observability", "tracing", "logging", "metrics",
    "sla", "slo", "kpi", "okrs",
    # Otros
    "arduino", "raspberry pi", "iot", "blockchain", "ethereum", "solidity",
    "web3", "nft", "smart contracts", "helm", "istio",
    "linkerd", "consul", "vault", "etcd", "zookeeper",
}


def _normalize_text(text: str) -> str:
    """Normaliza texto para búsqueda: minúsculas, reemplaza separadores."""
    text = text.lower()
    text = text.replace("-", " ").replace("/", " ").replace("+", " ")
    return text


def _separator_keyword_pattern(kw: str) -> str | None:
    """Devuelve un patrón regex para keywords con separadores (+ # - . /),
    o None si la keyword no tiene separadores.

    Estas keywords NO se pueden matchear sobre el texto normalizado (el
    normalizado destruye los separadores: "c++" -> "c"), así que se matchean
    sobre el texto crudo con bordes de palabra. El borde derecho se omite
    cuando la keyword termina en un no-alfanumérico ("c++" matchea también
    "c++17"; "next.js" termina en letra y NO matchea "next.jsx").
    """
    if not any(ch in kw for ch in "+#.-/"):
        return None
    left = r"(?<!\w)" if kw[0].isalnum() else ""
    right = r"(?!\w)" if kw[-1].isalnum() else ""
    return left + re.escape(kw) + right


def _count_keyword_occurrences(text: str, keyword: str) -> int:
    """Cuenta cuántas veces aparece una keyword en el texto (como palabra completa)."""
    kw = keyword.lower()
    sep_pattern = _separator_keyword_pattern(kw)
    if sep_pattern is not None:
        return len(re.findall(sep_pattern, text.lower()))
    text = _normalize_text(text)
    # Para bigramas
    if " " in kw:
        return text.count(kw)
    # Para unigramas: word boundary
    pattern = r"\b" + re.escape(kw) + r"\b"
    return len(re.findall(pattern, text))


def extract_keywords(job_description: str) -> Tuple[List[str], Dict[str, int]]:
    """Extrae keywords técnicas del JD usando el diccionario curado + bigramas dinámicos.

    Returns:
        (keywords_list, frequencies_dict)
    """
    normalized = _normalize_text(job_description)
    raw = (job_description or "").lower()
    # La normalización no saca la puntuación: "docker." no es "docker", y
    # un keyword seguido de punto/coma/paréntesis es el caso NORMAL en un
    # JD ("Requisitos: docker, python."). Se recortan los bordes no-alfanuméricos
    # de cada token antes de comparar contra el diccionario.
    words = [w.strip(".,;:!?()[]{}<>\"'¡¿…") for w in normalized.split()]
    found: Set[str] = set()
    frequencies: Dict[str, int] = {}

    # Bigramas del diccionario
    i = 0
    while i < len(words):
        if i + 1 < len(words):
            bigram = words[i] + " " + words[i + 1]
            if bigram in TECH_KEYWORDS:
                found.add(bigram)
                frequencies[bigram] = _count_keyword_occurrences(job_description, bigram)
                i += 2
                continue
        # Unigramas
        token = words[i]
        if token in TECH_KEYWORDS:
            found.add(token)
            frequencies[token] = _count_keyword_occurrences(job_description, token)
        i += 1

    # Términos con separadores (+ # - . /): el tokenizado normalizado los
    # destruye ("c++" -> "c", "next.js" -> "next js"), así que se matchean
    # sobre el texto crudo (ver _separator_keyword_pattern).
    for kw in TECH_KEYWORDS:
        if kw in found:
            continue
        pattern = _separator_keyword_pattern(kw)
        if pattern is not None and re.search(pattern, raw):
            found.add(kw)
            frequencies[kw] = _count_keyword_occurrences(job_description, kw)

    # Ordenar por frecuencia descendente, luego alfabéticamente
    sorted_keywords = sorted(found, key=lambda k: (-frequencies.get(k, 0), k))
    return sorted_keywords, frequencies


def build_keyword_ranking(
    bullets: List[Dict[str, Any]],
    job_description: str,
) -> List[str]:
    """Rankea bullets por peso de keywords técnicas del JD que contienen
    literalmente (o alguna variante sinónima), ponderado por la frecuencia
    de esa keyword en el JD.

    Este es el tercer canal que se fusiona en el RRF (junto a BM25 y dense),
    para asegurar que un bullet con la keyword exacta más importante de la
    oferta tenga prioridad EXPLÍCITA en el ranking, no solo la influencia
    indirecta que ya tiene vía BM25.

    Un bullet que no contiene ninguna keyword del JD simplemente no aparece
    en el resultado (igual que hacen sparse/dense con bullets sin match).

    Args:
        bullets: lista de dicts con al menos "id" y "text".
        job_description: texto completo de la oferta.

    Returns:
        Lista de bullet_ids ordenada por peso de keywords descendente.
    """
    from .sparse import get_synonym_variants

    jd_keywords, frequencies = extract_keywords(job_description)
    if not jd_keywords:
        return []

    # Variantes sinónimas de cada keyword del JD, precalculadas una vez.
    keyword_variants = {
        kw: get_synonym_variants(kw) for kw in jd_keywords
    }

    scored: List[tuple[str, float]] = []
    for b in bullets:
        # Se pasa el texto crudo: _count_keyword_occurrences normaliza por
        # dentro, pero los términos con separadores (c++, next.js) requieren
        # el texto original para poder matchear.
        raw_text = b.get("text", "")
        weight = 0.0
        for kw in jd_keywords:
            variants = keyword_variants[kw]
            if any(_count_keyword_occurrences(raw_text, v) > 0 for v in variants):
                weight += frequencies.get(kw, 1)
        if weight > 0:
            scored.append((b["id"], weight))

    scored.sort(key=lambda x: x[1], reverse=True)
    return [bid for bid, _ in scored]


def _corpus_text(doc: Dict[str, Any]) -> str:
    """Extrae todo el texto de un CV dict para búsqueda de keywords."""
    parts = []
    sections = doc.get("cv", {}).get("sections", {})
    for entries in sections.values():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if isinstance(entry, str):
                parts.append(entry)
            elif isinstance(entry, dict):
                for v in entry.values():
                    if isinstance(v, str):
                        parts.append(v)
                    elif isinstance(v, list):
                        for item in v:
                            if isinstance(item, str):
                                parts.append(item)
    return " ".join(parts).lower()


def _collect_master_texts(doc: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Itera las piezas de texto del master con su ubicación exacta.

    Cada pieza lleva {section, entry_idx, field, text, bullet_idx}. Los
    strings directos (summary) usan field=None; los highlights de una entrada
    usan field="highlights" y su índice en bullet_idx. Es el mismo barrido
    que _corpus_text, pero preservando dónde vive cada texto.
    """
    texts: List[Dict[str, Any]] = []
    sections = doc.get("cv", {}).get("sections", {})
    for section_name, entries in sections.items():
        if not isinstance(entries, list):
            continue
        for entry_idx, entry in enumerate(entries):
            if isinstance(entry, str):
                texts.append(
                    {
                        "section": section_name,
                        "entry_idx": entry_idx,
                        "field": None,
                        "text": entry,
                        "bullet_idx": None,
                    }
                )
            elif isinstance(entry, dict):
                for key, value in entry.items():
                    if isinstance(value, str):
                        texts.append(
                            {
                                "section": section_name,
                                "entry_idx": entry_idx,
                                "field": key,
                                "text": value,
                                "bullet_idx": None,
                            }
                        )
                    elif isinstance(value, list):
                        for bullet_idx, item in enumerate(value):
                            if isinstance(item, str):
                                texts.append(
                                    {
                                        "section": section_name,
                                        "entry_idx": entry_idx,
                                        "field": key,
                                        "text": item,
                                        "bullet_idx": bullet_idx,
                                    }
                                )
    return texts


def build_keyword_report(
    master_cv: Dict[str, Any],
    target_cv: Dict[str, Any],
    job_description: str,
) -> Dict[str, Any]:
    """Construye el keyword_report para el frontend.

    Returns:
        {
            "all_keywords": ["aws", "docker", ...],
            "frequencies": {"aws": 3, "docker": 1, ...},
            "in_master": {"aws": true, "docker": true, ...},
            "in_target": {"aws": true, "docker": true, ...},
            "missing_in_target": ["kubernetes"],
            "not_in_master": ["terraform"],
            "ats_impact_score": 72,  # 0-100, ponderado por frecuencia
            "critical_missing": ["kubernetes"],  # frecuencia >= 2 y missing
            "keyword_variants": {"js": ["js", "javascript"], ...},  # lowercase
            "locations": {"js": [{"section", "entry_idx", "field", "text",
                                   "bullet_idx"}], ...},  # dónde aparece en master
        }

    El matching usa keyword_in_text (variantes sinónimas + límites de
    palabra), el mismo criterio que la verificación ATS de merge.py: así el
    chip amarillo del frontend solo aparece cuando la keyword realmente está
    en el master, y `locations` le dice al click EXACTAMENTE dónde.
    """
    keywords, frequencies = extract_keywords(job_description)
    master_pieces = _collect_master_texts(master_cv)
    target_corpus = _corpus_text(target_cv)

    keyword_variants: Dict[str, List[str]] = {}
    locations: Dict[str, List[Dict[str, Any]]] = {}
    for kw in keywords:
        keyword_variants[kw] = sorted(get_synonym_variants(kw))
        locations[kw] = [
            piece for piece in master_pieces if keyword_in_text(kw, piece["text"])
        ]

    in_master = {kw: bool(locs) for kw, locs in locations.items()}
    in_target = {}
    missing_in_target = []
    not_in_master = []
    critical_missing = []

    total_weight = 0
    covered_weight = 0

    for kw in keywords:
        present_target = keyword_in_text(kw, target_corpus)
        in_target[kw] = present_target
        present_master = in_master[kw]
        freq = frequencies.get(kw, 1)
        weight = freq  # peso = frecuencia en el JD
        total_weight += weight
        if present_target:
            covered_weight += weight
        if present_master and not present_target:
            missing_in_target.append(kw)
            if freq >= 2:
                critical_missing.append(kw)
        if not present_master:
            not_in_master.append(kw)

    ats_impact_score = round((covered_weight / total_weight) * 100) if total_weight > 0 else 100

    return {
        "all_keywords": keywords,
        "frequencies": frequencies,
        "in_master": in_master,
        "in_target": in_target,
        "missing_in_target": missing_in_target,
        "not_in_master": not_in_master,
        "ats_impact_score": ats_impact_score,
        "critical_missing": critical_missing,
        "keyword_variants": keyword_variants,
        "locations": locations,
    }
