"""Fixtures compartidos de la suite de tests.

Los tests cubren las invariantes del pipeline: el LLM nunca
redacta el YAML final, las keywords ATS se verifican contra master+oferta,
los límites de página se aplican con código, y las claves internas se
strippean antes de guardar.
"""
import pytest

from src.config import DEFAULTS


@pytest.fixture
def master_cv():
    """CV maestro mínimo y válido (formato RenderCV) para los tests.

    Incluye una sección custom (certifications) que el pipeline NO maneja
    y debe preservar tal cual en el target.
    """
    return {
        "cv": {
            "name": "Test User",
            "location": "Ciudad",
            "sections": {
                "summary": [
                    "Desarrollador backend con experiencia en python y docker.",
                    "Ingeniero de software orientado a APIs REST.",
                ],
                "experience": [
                    {
                        "company": "Empresa A",
                        "position": "Backend Developer",
                        "start_date": "2021-01",
                        "end_date": "2024-12",
                        "highlights": [
                            "Desarrollé APIs REST con python y docker.",
                            "Mantuve pipelines de CI/CD con GitHub Actions.",
                            "Diseñé esquemas en postgresql.",
                        ],
                    },
                    {
                        "company": "Empresa B",
                        "position": "Fullstack Developer",
                        "start_date": "2018-06",
                        "end_date": "2020-12",
                        "highlights": [
                            "Construí dashboards con next.js.",
                            "Automaticé deploys con ci/cd.",
                        ],
                    },
                ],
                "projects": [
                    {
                        "name": "Sistema X",
                        "description": "Plataforma de reportes internos.",
                        "highlights": [
                            "Desarrollé el backend en python.",
                            "Integré APIs REST de terceros.",
                        ],
                    },
                ],
                "education": [
                    {
                        "institution": "Universidad Nacional",
                        "degree": "Ingeniería en Sistemas",
                        "start_date": "2012-03",
                        "end_date": "2017-07",
                    },
                    {
                        "institution": "Curso Online",
                        "degree": "Docker Avanzado",
                        "start_date": "2020-01",
                        "end_date": "2020-06",
                    },
                ],
                "skills": [
                    {"name": "Lenguajes", "details": ["python", "typescript"]},
                    {"name": "Infra", "details": ["docker", "kubernetes"]},
                ],
                "languages": [{"name": "Español", "fluency": "Nativo"}],
                "certifications": [
                    {"name": "Certificación AWS", "issuer": "Amazon Web Services"}
                ],
            },
        },
        "design": {"theme": "engineeringresumes"},
    }


@pytest.fixture
def job_description():
    """Oferta corta sin marcadores de sección (cubre todo el JD como query)."""
    return (
        "Buscamos un backend developer con experiencia en python y docker. "
        "Valoramos CI/CD y next.js."
    )


@pytest.fixture
def config():
    """Config explícita (sin leer config.json) para tests determinísticos."""
    return {**DEFAULTS, "llm_provider": "ollama", "show_keywords_line": True}
