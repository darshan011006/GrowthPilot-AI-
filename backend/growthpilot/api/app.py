from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from ..config import Settings, get_settings
from ..db import check_or_stamp_mode, init_engine, migrate
from ..worker import InProcessWorker
from .deps import ApiError

log = logging.getLogger("growthpilot")


def create_app(settings: Settings | None = None, *, start_worker: bool | None = None,
               run_migrations: bool = True) -> FastAPI:
    settings = settings or get_settings()
    engine = init_engine(settings)
    if run_migrations:
        migrate(engine)
    check_or_stamp_mode(settings)
    run_worker = settings.run_worker_in_process if start_worker is None else start_worker

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        worker = InProcessWorker() if run_worker else None
        if worker:
            worker.start()
        log.info("GrowthPilot API started: mode=%s env=%s live_publishing=%s", settings.app_mode.value,
                 settings.app_env.value, settings.live_publishing_enabled)
        for p in settings.problems():
            log.warning("config: %s missing — %s", p["key"], p["impact"])
        yield
        if worker:
            worker.stop()

    app = FastAPI(title="GrowthPilot AI API", lifespan=lifespan,
                  docs_url="/api/docs" if settings.app_env != "production" else None, redoc_url=None,
                  openapi_url="/api/openapi.json" if settings.app_env != "production" else None)

    @app.middleware("http")
    async def headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        if not request.url.path.startswith(("/api/public/", "/api/docs", "/api/openapi")):
            response.headers.setdefault("Cache-Control", "no-store")
        if settings.secure_cookies:
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return response

    @app.exception_handler(ApiError)
    async def api_error(_r: Request, exc: ApiError):
        return JSONResponse(exc.detail, status_code=exc.status_code)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_r: Request, exc: StarletteHTTPException):
        detail = exc.detail if isinstance(exc.detail, dict) else {"error": "http", "message": str(exc.detail)}
        return JSONResponse(detail, status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_r: Request, exc: RequestValidationError):
        msgs = [f"{'.'.join(str(x) for x in e['loc'][1:]) or 'body'}: {e['msg']}" for e in exc.errors()[:5]]
        return JSONResponse({"error": "validation", "message": "; ".join(msgs)}, status_code=422)

    @app.exception_handler(Exception)
    async def unhandled(_r: Request, exc: Exception):
        log.exception("unhandled error")
        return JSONResponse({"error": "internal", "message": "Something went wrong. Check the server log."},
                            status_code=500)

    @app.get("/api/health")
    def health():
        return {"status": "ok", "mode": settings.app_mode.value}

    from .routes import (
        agent,
        analytics,
        auth,
        brand,
        campaigns,
        content,
        governance,
        integrations,
        overview,
        research,
    )
    from .routes import settings as settings_routes

    for module in (auth, overview, brand, research, agent, campaigns, content, integrations, analytics,
                   governance, settings_routes):
        app.include_router(module.router)
    return app
