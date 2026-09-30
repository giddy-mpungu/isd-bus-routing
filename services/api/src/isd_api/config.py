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

from typing import Literal

from pydantic import field_validator
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

    # Passwords (Phase 5.1, isd_api/passwords.py). The minimum applies to
    # new and changed passwords only; reset links work once, for this long.
    password_min_length: int = 8
    password_reset_link_hours: int = 24
    # Links sent by email (Phase 5.2): "Forgot password" and the set-up
    # email for a new account. Admin-issued links use the value above.
    password_reset_email_minutes: int = 60
    account_setup_link_hours: int = 72

    # Email (Phase 5.2, isd_api/mailer.py): any SMTP provider. Unset
    # smtp_host means no email is sent and "Forgot password" is hidden.
    # "starttls" upgrades a plain connection (usually port 587); "ssl" is
    # TLS from the start (465); "none" is only for a local test inbox.
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_security: Literal["starttls", "ssl", "none"] = "starttls"
    smtp_username: str | None = None
    smtp_password: str | None = None
    mail_from: str | None = None  # e.g. "Bus Office <transportation@district.org>"
    # The web app's public address, for links in emails. Falls back to the
    # first CORS origin, which is the same thing in a normal deployment.
    public_web_url: str | None = None

    # OpenRouteService (spec section 6, Phase 6 GIS slice 1). Unset by
    # default — a schedule solve falls back to the straight-line
    # estimator when no key is configured, so CI/tests/local dev work
    # without one. See isd_solver.domain.ors_deadhead_estimator.
    ors_api_key: str | None = None

    # GPS history (isd_api/position_history.py): how many days of a bus's
    # track to keep. A track shows where students were, so it's deleted
    # after this; spec section 20's learning only needs recent weeks.
    position_history_days: int = 30
    ors_base_url: str = "https://api.openrouteservice.org"
    ors_profile: str = "driving-hgv"

    @field_validator(
        "smtp_host", "smtp_username", "smtp_password", "mail_from", "public_web_url", mode="before"
    )
    @classmethod
    def _blank_is_unset(cls, value: object) -> object:
        # docker compose's `${VAR:-}` passes "" rather than leaving it unset.
        return None if value == "" else value

    @property
    def web_url(self) -> str:
        base = self.public_web_url or (self.cors_allowed_origins or ["http://localhost:5173"])[0]
        return base.rstrip("/")

    def require_production_ready(self) -> None:
        if self.environment == "production" and self.jwt_secret_key == _INSECURE_DEV_JWT_SECRET:
            raise RuntimeError(
                "ISD_API_JWT_SECRET_KEY must be set to a real secret when "
                "ISD_API_ENVIRONMENT=production — refusing to start with the "
                "insecure development default."
            )
        if self.smtp_host and not self.mail_from:
            raise RuntimeError("ISD_API_MAIL_FROM must be set when ISD_API_SMTP_HOST is.")


settings = Settings()
