"""Modelos pydantic de la API."""

from typing import Any, Dict, Optional

from pydantic import BaseModel

from src.merge import strip_internal_keys


class JobDescriptionIn(BaseModel):
    job_description: str
    manual_keywords: list[str] = []
    # Fuerza el recálculo completo de la fase IR, salteando el cache de
    # selección. Botón "Forzar regeneración" del frontend.
    force: bool = False


class RegenerateSectionIn(BaseModel):
    job_description: str
    section_name: str


class CVDocumentIn(BaseModel):
    cv: Dict[str, Any]
    design: Optional[Dict[str, Any]] = None
    run_id: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        data = {"cv": self.cv}
        if self.design is not None:
            data["design"] = self.design
        return strip_internal_keys(data)


class RunUpdateIn(BaseModel):
    offer_title: Optional[str] = None
    offer_link: Optional[str] = None
    application: Optional[Dict[str, Any]] = None


class ExtractFactsIn(BaseModel):
    # Texto del bullet legacy a estructurar (el frontend manda el texto
    # real en memoria, no un índice: el master del disco puede diferir de
    # lo que el usuario está editando sin guardar).
    text: str


class GenerateVariantIn(BaseModel):
    # Redacción asistida de variante. El frontend manda los
    # hechos y redacciones actuales del logro (mismo patrón que
    # ExtractFactsIn: el master del disco puede diferir de la edición en
    # memoria sin guardar); el servidor nunca replica el master.
    angle: str
    facts: Dict[str, Any] = {}
    variant_texts: list[str] = []
    current_text: str = ""
    jd_snippet: str = ""


class OnboardingAnswersIn(BaseModel):
    # Respuestas libres del onboarding conversacional: qué hiciste,
    # herramientas, resultados. Cada una puede venir vacía ("no sé / paso
    # esta pregunta" es válido) salvo work, que el router exige no vacío.
    work: str = ""
    tools: str = ""
    outcomes: str = ""


class ImportFileIn(BaseModel):
    # Un CV a importar: kind es "text" | "yaml" | "json" | "pdf".
    # Para pdf, `content` es el archivo en base64.
    name: str
    kind: str
    content: str


class ImportClusterizeIn(BaseModel):
    files: list[ImportFileIn]


class ImportResolveIn(BaseModel):
    cluster_id: str
    action: str  # "merge" | "split" | "discard"


class ImportOrphansIn(BaseModel):
    accept: bool = True


class ImportConfirmIn(BaseModel):
    cluster_id: str
