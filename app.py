"""Backend web local del editor de CV (entry point de uvicorn).

Corré con:
    uvicorn app:app --reload
y abrí http://127.0.0.1:8000 en el navegador.

La implementación vive en api/ (routers por recurso, schemas, deps) y src/
(dominio: storage, services, merge, retrieval, llm). Este archivo solo
re-exporta la app para no cambiar el comando de arranque.
"""

from api.main import app

__all__ = ["app"]
