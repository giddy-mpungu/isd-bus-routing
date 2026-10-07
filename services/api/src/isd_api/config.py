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

import base64
import hashlib
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

    # Two-step sign-in (Phase 5.3, isd_api/mfa.py). Roles listed here must
    # use an authenticator app; others may (drivers never do). The key
    # encrypts authenticator secrets (a Fernet key: 32 random bytes,
    # url-safe base64); required in production, and changing it means
    # everyone sets up their authenticator again.
    mfa_required_roles: list[str] = ["transportation_admin", "dispatcher"]
    mfa_encryption_key: str | None = None
    mfa_issuer: str = "isd-bus-routing"

    # Single sign-on (Phase 5.4, isd_api/oidc.py): any OpenID Connect
    # provider. Unset issuer = no SSO button. The redirect URI is this
    # api's /auth/oidc/callback as the browser reaches it, registered with
    # the provider. trust_mfa: "claim" counts the provider's two-step
    # check only when its ID token reports one (amr, or acr in
    # mfa_acr_values); "always" for providers that enforce MFA by policy
    # without saying so in the token; "never" always asks for ours.
    oidc_issuer: str | None = None
    oidc_client_id: str | None = None
    oidc_client_secret: str | None = None
    oidc_redirect_uri: str | None = None
    oidc_scopes: str = "openid email profile"
    oidc_email_claim: str = "email"
    oidc_label: str = "your district account"
    oidc_roles: list[str] = ["transportation_admin", "dispatcher", "school_admin", "driver"]
    oidc_trust_mfa: Literal["claim", "always", "never"] = "claim"
    oidc_mfa_acr_values: list[str] = []

    # FERPA retention (isd_api/retention.py): a withdrawn student's data is
    # kept through the end of this many school years after the one they
    # left in; school years end on school_year_end (MM-DD).
    school_year_end: str = "06-30"
    student_retention_school_years: int = 1

    # Scheduled SIS roster sync (isd_api/sis_sync.py): the district's
    # OneRoster 1.1 REST API, e.g. https://sis.example.org/ims/oneroster/v1p1,
    # and its OAuth 2 token endpoint. All four set = the nightly sync runs
    # at sis_sync_time (district time) and "Sync now" works.
    sis_oneroster_base_url: str | None = None
    sis_oneroster_token_url: str | None = None
    sis_oneroster_client_id: str | None = None
    sis_oneroster_client_secret: str | None = None
    sis_oneroster_scope: str | None = None
    sis_sync_time: str = "03:00"

    # Bus-time emails to families (Phase 5.5, isd_api/eta_notifications.py),
    # sent by the worker (isd_api/worker.py) every worker_interval_seconds.
    eta_email_threshold_minutes: int = 10
    eta_email_earliest: str = "05:30"  # district time, HH:MM
    worker_interval_seconds: int = 120

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
        "smtp_host",
        "smtp_username",
        "smtp_password",
        "mail_from",
        "public_web_url",
        "mfa_encryption_key",
        "oidc_issuer",
        "oidc_client_id",
        "oidc_client_secret",
        "oidc_redirect_uri",
        "sis_oneroster_base_url",
        "sis_oneroster_token_url",
        "sis_oneroster_client_id",
        "sis_oneroster_client_secret",
        "sis_oneroster_scope",
        mode="before",
    )
    @classmethod
    def _blank_is_unset(cls, value: object) -> object:
        # docker compose's `${VAR:-}` passes "" rather than leaving it unset.
        return None if value == "" else value

    @property
    def web_url(self) -> str:
        base = self.public_web_url or (self.cors_allowed_origins or ["http://localhost:5173"])[0]
        return base.rstrip("/")

    @property
    def mfa_fernet_key(self) -> bytes:
        if self.mfa_encryption_key:
            return self.mfa_encryption_key.encode("ascii")
        # Dev/test only (production refuses to start without a real key).
        digest = hashlib.sha256(b"isd-mfa-dev:" + self.jwt_secret_key.encode()).digest()
        return base64.urlsafe_b64encode(digest)

    # The interactive API docs (/docs, /redoc, /openapi.json) map every
    # endpoint; on by default except in production (audit, 2026-10-04).
    expose_api_docs: bool | None = None

    @property
    def api_docs_enabled(self) -> bool:
        if self.expose_api_docs is not None:
            return self.expose_api_docs
        return self.environment != "production"

    def require_production_ready(self) -> None:
        if self.environment == "production" and self.jwt_secret_key == _INSECURE_DEV_JWT_SECRET:
            raise RuntimeError(
                "ISD_API_JWT_SECRET_KEY must be set to a real secret when "
                "ISD_API_ENVIRONMENT=production — refusing to start with the "
                "insecure development default."
            )
        if self.environment == "production":
            try:
                ok = len(base64.urlsafe_b64decode(self.mfa_encryption_key or "")) == 32
            except ValueError:
                ok = False
            if not ok:
                raise RuntimeError(
                    "ISD_API_MFA_ENCRYPTION_KEY must be set to 32 random bytes in url-safe "
                    "base64 when ISD_API_ENVIRONMENT=production (see docs/deployment.md)."
                )
        if self.oidc_issuer:
            missing = [
                name
                for name in ("oidc_client_id", "oidc_client_secret", "oidc_redirect_uri")
                if not getattr(self, name)
            ]
            if missing:
                raise RuntimeError(
                    "ISD_API_OIDC_ISSUER is set but these are not: "
                    + ", ".join("ISD_API_" + m.upper() for m in missing)
                )
            if self.environment == "production" and not self.oidc_issuer.startswith("https://"):
                raise RuntimeError("ISD_API_OIDC_ISSUER must be an https:// address in production.")
        if self.environment == "production":
            for name in ("sis_oneroster_base_url", "sis_oneroster_token_url"):
                value = getattr(self, name)
                if value and not value.startswith("https://"):
                    raise RuntimeError(f"ISD_API_{name.upper()} must be an https:// address.")
        if self.smtp_host and not self.mail_from:
            raise RuntimeError("ISD_API_MAIL_FROM must be set when ISD_API_SMTP_HOST is.")


settings = Settings()
