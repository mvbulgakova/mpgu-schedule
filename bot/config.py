from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    bot_token: str
    database_url: str
    cdn_base: str = "https://cdn.jsdelivr.net/gh/mvbulgakova/mpgu-schedule@data"  # override via CDN_BASE env var
    poll_interval_hours: int = 4
    enabled_institutes: list[str] = [
        "biology", "childhood", "philology", "sport", "social"
    ]

    model_config = {"env_file": ".env"}

    @field_validator("database_url", mode="before")
    @classmethod
    def fix_postgres_url(cls, v: str) -> str:
        # Fly.io sets DATABASE_URL as postgres:// — SQLAlchemy async needs postgresql+asyncpg://
        if isinstance(v, str) and v.startswith("postgres://"):
            return v.replace("postgres://", "postgresql+asyncpg://", 1)
        return v

    @field_validator("enabled_institutes", mode="before")
    @classmethod
    def parse_institutes_list(cls, v):
        # Allow comma-separated string from env var: "biology,sport,social"
        if isinstance(v, str):
            return [i.strip() for i in v.split(",") if i.strip()]
        return v


settings = Settings()
