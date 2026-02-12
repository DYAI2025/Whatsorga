"""Beziehungs-Radar API — main FastAPI application."""

import logging

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse

from app.storage.database import init_db
from app.analysis.unified_engine import engine as marker_engine
from app.ingestion.router import router as ingestion_router
from app.dashboard.router import router as dashboard_router

STATIC_DIR = Path(__file__).parent / "dashboard" / "static"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

app = FastAPI(title="Beziehungs-Radar API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)

app.include_router(ingestion_router)
app.include_router(dashboard_router)

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.on_event("startup")
async def startup():
    await init_db()
    marker_engine.load()


@app.get("/")
async def root():
    return RedirectResponse(url="/dashboard")


@app.get("/health")
async def health():
    return {"status": "ok", "service": "beziehungs-radar"}


@app.get("/dashboard")
async def dashboard_page():
    index = STATIC_DIR / "index.html"
    if index.exists():
        return FileResponse(str(index))
    return {"error": "Dashboard not built yet"}
