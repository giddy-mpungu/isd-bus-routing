from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from isd_api import i18n
from isd_api.config import settings
from isd_api.db import Base, engine
from isd_api.routers import (
    absences,
    alerts,
    announcements,
    audit_log,
    auth,
    bell_schedules,
    corrections,
    crews,
    destination_profiles,
    dispatch_tasks,
    driver_reports,
    drivers,
    field_trips,
    geographic_knowledge,
    mfa,
    notifications,
    optimization_settings,
    positions,
    qualifications,
    reports,
    ridership_rules,
    road_closures,
    runs,
    schedule,
    schools,
    sis_import,
    sso,
    stop_proposals,
    stops,
    students,
    templates,
    transportation_rules,
    users,
    vehicles,
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings.require_production_ready()
    if settings.environment != "production":
        # Convenience for dev/test only. Production schema changes go
        # through Alembic migrations (alembic/), never this.
        Base.metadata.create_all(bind=engine)
    yield
    engine.dispose()


app = FastAPI(
    title="isd-bus-routing API",
    version="0.1.0",
    lifespan=lifespan,
    # Not published in production unless ISD_API_EXPOSE_API_DOCS=true.
    docs_url="/docs" if settings.api_docs_enabled else None,
    redoc_url="/redoc" if settings.api_docs_enabled else None,
    openapi_url="/openapi.json" if settings.api_docs_enabled else None,
)

# allow_credentials=True is required for the Phase 3 dispatcher console's
# session cookie to cross the dev-server/API origin boundary — combined
# with an explicit allow-list (never a wildcard; browsers reject that
# combination with credentials anyway) this is the actual CORS security
# boundary. See isd_api.security and the Phase 3 plan for the rest of
# the cookie's protections (httponly, SameSite=Lax).
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(StarletteHTTPException)
async def translated_http_exception(request: Request, exc: StarletteHTTPException) -> Response:
    """Errors in the language the request asked for (isd_api/i18n), when
    the message is a known phrase; otherwise as they were."""
    lang = i18n.request_language(request)
    if lang != i18n.DEFAULT and isinstance(exc.detail, str):
        exc = StarletteHTTPException(
            status_code=exc.status_code,
            detail=i18n.translate_message(lang, exc.detail),
            headers=exc.headers,
        )
    return await http_exception_handler(request, exc)


app.include_router(auth.router)
app.include_router(users.router)
app.include_router(qualifications.router)
app.include_router(schools.router)
app.include_router(vehicles.router)
app.include_router(drivers.router)
app.include_router(crews.router)
app.include_router(runs.router)
app.include_router(schedule.router)
app.include_router(stops.router)
app.include_router(stop_proposals.router)
app.include_router(students.router)
app.include_router(absences.router)
app.include_router(absences.all_absences_router)
app.include_router(geographic_knowledge.router)
app.include_router(positions.driver_router)
app.include_router(positions.fleet_router)
app.include_router(field_trips.router)
app.include_router(dispatch_tasks.router)
app.include_router(alerts.router)
app.include_router(reports.router)
app.include_router(destination_profiles.router)
app.include_router(announcements.router)
app.include_router(bell_schedules.router)
app.include_router(driver_reports.router)
app.include_router(driver_reports.all_reports_router)
app.include_router(audit_log.router)
app.include_router(sis_import.router)
app.include_router(optimization_settings.router)
app.include_router(ridership_rules.router)
app.include_router(road_closures.router)
app.include_router(mfa.router)
app.include_router(sso.router)
app.include_router(notifications.router)
app.include_router(corrections.router)
app.include_router(transportation_rules.router)
app.include_router(templates.route_router)
app.include_router(templates.crew_router)
app.include_router(templates.generate_router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
