"""Modelos pydantic de la API."""

from typing import Any, Dict, Optional

from pydantic import BaseModel

from src.merge import strip_internal_keys


class JobDescriptionIn(BaseModel):
    job_description: str
    manual_keywords: list[str] = []
    # Fuerza el recálculo completo de la fase IR, salteando el cache de
    # selección (P0.1). Botón "Forzar regeneración" del frontend.
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
