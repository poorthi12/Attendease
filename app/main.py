import logging
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import RedirectResponse
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware
from starlette.staticfiles import StaticFiles

from app.config import Settings, get_settings
from app.database import close_client, ensure_indexes, get_client, get_database
from app.routers import admin, attendance, auth, student, teacher
from app.security.middleware import RequestLimitsAndHeaders
from app.utils.responses import render

logger = logging.getLogger("attendease")
ROOT = Path(__file__).resolve().parents[1]


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    secret = settings.session_secret.get_secret_value() if settings.session_secret else secrets.token_urlsafe(48)

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        if settings.mongodb_url and settings.app_env != "test":
            try:
                database = get_client(settings)[settings.mongodb_database]
                await run_in_threadpool(ensure_indexes, database)
            except Exception:
                logger.warning("MongoDB indexes were not initialized; database-backed pages may be unavailable.")
        try:
            yield
        finally:
            if settings.app_env != "test":
                await run_in_threadpool(close_client)

    application = FastAPI(title="AttendEase", version="1.0.0", lifespan=lifespan)
    application.state.settings = settings
    application.add_middleware(
        SessionMiddleware,
        secret_key=secret,
        session_cookie="attendease_session",
        max_age=settings.session_max_age_seconds,
        same_site="lax",
        https_only=settings.cookie_secure or settings.app_env == "production",
    )
    application.add_middleware(RequestLimitsAndHeaders, max_body_bytes=1_048_576)
    application.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")
    application.include_router(auth.router)
    application.include_router(student.router)
    application.include_router(teacher.router)
    application.include_router(attendance.router)
    application.include_router(admin.router)

    @application.get("/health", include_in_schema=False)
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @application.exception_handler(StarletteHTTPException)
    async def friendly_http_error(request: Request, exc: StarletteHTTPException):
        if exc.status_code == 401:
            return RedirectResponse(url="/", status_code=303)
        if exc.status_code in {403, 404}:
            template = "errors/403.html" if exc.status_code == 403 else "errors/404.html"
            return render(request, template, status_code=exc.status_code, message=exc.detail)
        if exc.status_code in {500, 502, 503}:
            return render(request, "errors/500.html", status_code=exc.status_code, message="The service is temporarily unavailable. Please try again shortly.")
        return await http_exception_handler(request, exc)

    @application.exception_handler(RequestValidationError)
    async def friendly_validation_error(request: Request, exc: RequestValidationError):
        # Keep enough context to diagnose unexpected request-shape failures (such
        # as a form submission rejected before its route handler runs), without
        # logging submitted values or other potentially sensitive input.
        errors = [
            {
                "location": ".".join(str(part) for part in error.get("loc", ())),
                "type": error.get("type", "unknown"),
                "message": error.get("msg", "Invalid value."),
            }
            for error in exc.errors()
        ]
        logger.warning(
            "Request validation failed for %s %s: %s",
            request.method,
            request.url.path,
            errors,
        )
        return render(request, "errors/500.html", status_code=422, message="Please review the information and try again.")

    @application.exception_handler(Exception)
    async def friendly_server_error(request: Request, exc: Exception):
        logger.error("Unhandled application error (%s).", type(exc).__name__)
        return render(request, "errors/500.html", status_code=500, message="Something went wrong. Please try again.")

    return application


app = create_app()
