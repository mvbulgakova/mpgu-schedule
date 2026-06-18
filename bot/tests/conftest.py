import os
import pytest


@pytest.fixture(scope="session", autouse=True)
def setup_env():
    """Set up minimal environment for tests."""
    os.environ.setdefault("BOT_TOKEN", "test_token")
    os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
    os.environ.setdefault("CDN_BASE", "https://example.com/cdn")
