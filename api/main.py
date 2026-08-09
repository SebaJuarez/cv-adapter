"""App FastAPI: ensambla los routers y monta el frontend estático.

Entry point de uvicorn (mantiene el comando `uvicorn app:app --reload`
vía el re-export de app.py).
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .deps import FRONTEND_DIR
from .routers import config, generate, master_cv, render, system

app = FastAPI(title="cv-adapter")

app.include_router(master_cv.router)
app.include_router(config.router)
app.include_router(system.router)
app.include_router(generate.router)
app.include_router(render.router)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Red de seguridad: cualquier excepción no manejada devuelve un JSON
    legible en vez de un traceback crudo. Los HTTPException siguen pasando
    por su handler específico (más específico en el MRO de Starlette)."""
    return JSONResponse(
        status_code=500,
        content={"detail": f"Error interno del servidor: {exc}"},
    )


# El mount en "/" va después de los routers para que /api/* matchee primero.
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
