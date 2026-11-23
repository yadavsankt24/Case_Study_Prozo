"""
FastAPI application factory.

Run locally:   uvicorn app.main:app --reload
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pymongo.errors import ConnectionFailure

from app.case_study_1 import api as cs1_api
from app.case_study_1 import pages as cs1_pages
from app.case_study_2 import api as cs2_api
from app.case_study_2 import pages as cs2_pages
from app.case_study_3 import api as cs3_api
from app.case_study_3 import pages as cs3_pages
from app.config import Settings
from app.container import Container
from app.shared import pages as shared_pages
from app.shared.errors import InputError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("app")


def create_app(settings: Optional[Settings] = None) -> FastAPI:
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        container = Container.build(settings)
        interrupted = container.jobs.fail_interrupted_jobs() + container.cs3_repo.fail_interrupted_runs()
        if interrupted:
            log.warning("Marked %d interrupted job(s) as failed", interrupted)
        resumed = container.cs1.resume_unfinished()
        if resumed:
            log.info("Resumed %d unfinished Case Study 1 batch(es)", resumed)
        if container.cs3_scheduler:
            container.cs3_scheduler.start()
        app.state.container = container
        yield
        container.runner.shutdown()
        container.cs1.shutdown()
        container.cs3.shutdown()
        if container.cs3_scheduler:
            container.cs3_scheduler.stop()

    app = FastAPI(
        title="Prozo EIR case studies",
        version="0.2.0",
        description="Proof of concept: Case Study 1 (parcel frames -> shipment CSV), Case Study 2 "
                    "(wagesheet vs PF/ESIC ECR verification), Case Study 3 (daily FC P&L monitor).",
        lifespan=lifespan,
    )

    @app.exception_handler(ConnectionFailure)
    async def database_error_handler(_: Request, error: ConnectionFailure):
        # AutoReconnect / ServerSelectionTimeout / network or TLS drops: temporary, the browser retries
        log.warning("Database not reachable: %s", str(error).split(" (configured timeouts")[0])
        return JSONResponse(status_code=503, content={
            "detail": "The database could not be reached just now. Please try again in a moment."})

    @app.exception_handler(InputError)
    async def input_error_handler(_: Request, error: InputError):
        return JSONResponse(status_code=400, content={"detail": error.message, "field": error.field})

    @app.get("/health", tags=["system"])
    def health(request: Request):
        container: Container = request.app.state.container
        return {"status": "ok", "database": "in-memory" if container.in_memory_db else "mongodb"}

    static_dir = Path(__file__).resolve().parent / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    # JSON APIs
    app.include_router(cs1_api.router)
    app.include_router(cs2_api.router)
    app.include_router(cs3_api.router)
    # HTML pages
    app.include_router(shared_pages.router)
    app.include_router(cs1_pages.router)
    app.include_router(cs2_pages.router)
    app.include_router(cs3_pages.router)
    return app


app = create_app()
