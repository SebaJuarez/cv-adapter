"""Paquete de la API web (FastAPI).

Estructura:
- main.py: arma la app (routers + mount estático del frontend).
- schemas.py: modelos de request/response (pydantic).
- deps.py: rutas del filesystem compartidas por los routers.
- routers/: un router por recurso (master_cv, config, generate, render, system).
"""
