import os
import pytest

def test_settings_load_from_env(monkeypatch):
    monkeypatch.setenv("BOT_TOKEN", "123:ABC")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
    import importlib
    import bot.config as cfg
    importlib.reload(cfg)
    assert cfg.settings.bot_token == "123:ABC"
    assert "asyncpg" in cfg.settings.database_url
