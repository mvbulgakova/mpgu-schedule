import pytest


def test_build_group_list_extracts_groups(monkeypatch):
    """Test build_group_list extracts groups from manifest."""
    # Set env before importing
    monkeypatch.setenv("BOT_TOKEN", "test_token")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")

    import importlib
    from bot.services import data_sync
    importlib.reload(data_sync)

    manifest = {
        "groups": [
            {"name": "БИО40-БА2501", "file": "БИО40-БА2501", "year": 2026, "form": "full_time", "degree": "bachelor"},
            {"name": "БИО40-БА2502", "file": "БИО40-БА2502", "year": 2026, "form": "full_time", "degree": "bachelor"},
        ]
    }
    result = data_sync.build_group_list(manifest)
    assert len(result) == 2
    assert result[0]["name"] == "БИО40-БА2501"


def test_build_group_list_empty(monkeypatch):
    """Test build_group_list with empty groups."""
    monkeypatch.setenv("BOT_TOKEN", "test_token")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")

    import importlib
    from bot.services import data_sync
    importlib.reload(data_sync)

    assert data_sync.build_group_list({"groups": []}) == []


def test_build_group_list_missing_key(monkeypatch):
    """Test build_group_list with missing groups key."""
    monkeypatch.setenv("BOT_TOKEN", "test_token")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")

    import importlib
    from bot.services import data_sync
    importlib.reload(data_sync)

    assert data_sync.build_group_list({}) == []
