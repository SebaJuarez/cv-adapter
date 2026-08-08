"""Modelos pydantic de la API."""

from typing import Any, Dict, Optional

from pydantic import BaseModel

from src.merge import strip_internal_keys


class JobDescriptionIn(BaseModel):
    job_description: str
    manual_keywords: list[str] = []


class RegenerateSectionIn(BaseModel):
    job_description: str
    section_name: str


class CVDocumentIn(BaseModel):
    cv: Dict[str, Any]
    design: Optional[Dict[str, Any]] = None

    def as_dict(self) -> Dict[str, Any]:
        data = {"cv": self.cv}
        if self.design is not None:
            data["design"] = self.design
        return strip_internal_keys(data)
