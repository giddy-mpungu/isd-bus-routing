"""Application settings.

Every value that matters for security (JWT signing key, DB connection
string) comes from the environment, never a hardcoded default that
would be safe to ship. The defaults below exist ONLY so the test suite
and local `uvicorn` quickstart work out of the box on a laptop with no
`.env` file — they are clearly marked and must not reach a real
deployment. `Settings.require_production_ready()` is called by
`main.py` at startup outside of `ENVIRONMENT=test`/`ENVIRONMENT=dev`
and raises if an insecure default is still in use, so a misconfigured
production deployment fails to start rather than running insecurely.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict

_INSECURE_DEV_JWT_SECRET = "dev-only-insecure-secret-do-not-use-in-production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ISD_API_")

    environment: str = "dev"  # "dev" | "test" | "production"
    database_url: str = "sqlite:///./isd_api_dev.db"
    jwt_secret_key: str = _INSECURE_DEV_JWT_SECRET
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60

    # Connection pool settings — only applied to non-SQLite (i.e.
    # production PostgreSQL, ADR 0003) engines; see isd_api.db.make_engine.
    db_pool_size: int = 5
    db_max_overflow: int = 10
    db_pool_recycle_seconds: int = 1800

    # Browser session cookie (Phase 3 dispatcher console). Separate
    # from access_token_expire_minutes, which still governs the
    # JSON-body bearer token returned to API/script/Swagger consumers.
    # session_inactivity_minutes is the cookie's Max-Age, renewed on
    # every authenticated request made via the cookie — an inactive
    # browser session expires on its own once nothing renews it.
    # session_absolute_max_hours is the underlying JWT's fixed exp,
    # unaffected by renewal — a hard ceiling on session length even
    # under continuous activity.
    session_inactivity_minutes: int = 30
    session_absolute_max_hours: int = 12

    # Origins allowed to make credentialed (cookie-bearing) cross-origin
    # requests to this API — the dispatcher console's dev server by
    # default. Never wildcard this; see main.py's CORSMiddleware setup.
    cors_allowed_origins: list[str] = ["http://localhost:5173"]

    # POST /auth/login brute-force protection (ADR 0006 follow-up).
    # In-memory, per-process — see security.LoginRateLimiter's docstring
    # for why that's a deliberate, honestly-scoped limitation today.
    login_rate_limit_attempts: int = 10
    login_rate_limit_window_seconds: int = 300

    # OpenRouteService (spec section 6, Phase 6 GIS slice 1). Unset by
    # default — a schedule solve falls back to the straight-line
    # estimator when no key is configured, so CI/tests/local dev work
    # without one. See isd_solver.domain.ors_deadhead_estimator.
    ors_api_key: str | None = None
    ors_base_url: str = "https://api.openrouteservice.org"
    ors_profile: str = "driving-hgv"

    def require_production_ready(self) -> None:
        if self.environment == "production" and self.jwt_secret_key == _INSECURE_DEV_JWT_SECRET:
            raise RuntimeError(
                "ISD_API_JWT_SECRET_KEY must be set to a real secret when "
                "ISD_API_ENVIRONMENT=production — refusing to start with the "
                "insecure development default."
            )


settings = Settings()
