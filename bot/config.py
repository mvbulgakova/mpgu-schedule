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


settings = Settings()
