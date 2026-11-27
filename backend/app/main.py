"""The enrollment engine's API."""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import auth, enrollments, intake, submissions
from app.config import get_settings
from app.services import build, setup_logging

log = logging.getLogger(__name__)


def create_app() -> FastAPI:
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        setup_logging()
        services = await build(settings)
        for name in ("pool", "shared", "enrollments", "intake", "pipeline", "runs", "submitter"):
            setattr(app.state, name, getattr(services, name))
        app.state.tasks = set()
        log.info("enrollment engine ready (%s, shared state: %s, AI mapper: %s)", settings.app_env,
                 type(services.shared).__name__, services.llm.name if services.llm else "off")
        try:
            yield
        finally:
            for task in list(app.state.tasks):
                task.cancel()
            await services.aclose()

    app = FastAPI(title="Enrollment automation engine", version="0.1.0", lifespan=lifespan,
                  docs_url=None if settings.is_production else "/docs", redoc_url=None)
    app.add_middleware(CORSMiddleware, allow_origins=settings.origins, allow_methods=["GET", "POST", "PATCH"],
                       allow_headers=["Authorization", "Content-Type", "Idempotency-Key"])
    app.include_router(auth.router)
    app.include_router(enrollments.router)
    app.include_router(intake.router)
    app.include_router(submissions.router)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("X-Frame-Options", "DENY")
        if request.url.path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")   # answers can hold personal data
        return response

    @app.get("/health")
    async def health(request: Request) -> JSONResponse:
        try:
            await request.app.state.pool.fetchval("SELECT 1")
            db = True
        except Exception:
            db = False
        shared = await request.app.state.shared.ping()
        ok = db and shared
        return JSONResponse({"status": "ok" if ok else "degraded", "database": db, "shared_state": shared},
                            status_code=200 if ok else 503)

    return app


app = create_app()
