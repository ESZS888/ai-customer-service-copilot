import pytest
from app.config import settings


@pytest.fixture(autouse=True)
def isolated_database(tmp_path, monkeypatch):
    """All engineering tests use temporary DBs; never pollute demo analytics."""
    monkeypatch.setattr(settings, 'db_path', str(tmp_path / 'test.sqlite3'))
