"""App FastAPI: ensambla los routers y monta el frontend estático.

Entry point de uvicorn (mantiene el comando `uvicorn app:app --reload`
vía el re-export de app.py).
"""

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .deps import FRONTEND_DIR
from .routers import config, generate, master_cv, render, system

app = FastAPI(title="cv-adapter")

app.include_router(master_cv.router)
app.include_router(config.router)
app.include_router(system.router)
app.include_router(generate.router)
app.include_router(render.router)

# El mount en "/" va después de los routers para que /api/* matchee primero.
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
