from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from isd_api.config import settings
from isd_api.db import Base, engine
from isd_api.routers import (
    auth,
    crews,
    drivers,
    qualifications,
    runs,
    schedule,
    schools,
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


app = FastAPI(title="isd-bus-routing API", version="0.1.0", lifespan=lifespan)

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(qualifications.router)
app.include_router(schools.router)
app.include_router(vehicles.router)
app.include_router(drivers.router)
app.include_router(crews.router)
app.include_router(runs.router)
app.include_router(schedule.router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
