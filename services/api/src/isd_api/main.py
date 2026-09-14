from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from isd_api.config import settings
from isd_api.db import Base, engine
from isd_api.routers import (
    absences,
    announcements,
    auth,
    crews,
    drivers,
    field_trips,
    geographic_knowledge,
    positions,
    qualifications,
    runs,
    schedule,
    schools,
    stops,
    students,
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


app = FastAPI(title="isd-bus-routing API", version="0.1.0", lifespan=lifespan)

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
app.include_router(students.router)
app.include_router(absences.router)
app.include_router(absences.all_absences_router)
app.include_router(geographic_knowledge.router)
app.include_router(positions.driver_router)
app.include_router(positions.fleet_router)
app.include_router(field_trips.router)
app.include_router(announcements.router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
