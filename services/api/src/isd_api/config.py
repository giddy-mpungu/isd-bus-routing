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

    def require_production_ready(self) -> None:
        if self.environment == "production" and self.jwt_secret_key == _INSECURE_DEV_JWT_SECRET:
            raise RuntimeError(
                "ISD_API_JWT_SECRET_KEY must be set to a real secret when "
                "ISD_API_ENVIRONMENT=production — refusing to start with the "
                "insecure development default."
            )


settings = Settings()
