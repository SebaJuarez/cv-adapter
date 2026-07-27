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


def _count_keyword_occurrences(text: str, keyword: str) -> int:
    """Cuenta cuántas veces aparece una keyword en el texto (como palabra completa)."""
    text = _normalize_text(text)
    kw = keyword.lower()
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
    words = normalized.split()
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

    # Ordenar por frecuencia descendente, luego alfabéticamente
    sorted_keywords = sorted(found, key=lambda k: (-frequencies.get(k, 0), k))
    return sorted_keywords, frequencies


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
        }
    """
    keywords, frequencies = extract_keywords(job_description)
    master_corpus = _corpus_text(master_cv)
    target_corpus = _corpus_text(target_cv)

    in_master = {}
    in_target = {}
    missing_in_target = []
    not_in_master = []
    critical_missing = []

    total_weight = 0
    covered_weight = 0

    for kw in keywords:
        kw_low = kw.lower()
        present_master = kw_low in master_corpus
        present_target = kw_low in target_corpus
        in_master[kw] = present_master
        in_target[kw] = present_target
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
    }