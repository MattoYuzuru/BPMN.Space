"""Старт поверх схемы БД, которую применил более новый релиз (откат деплоя)."""

from types import SimpleNamespace

import pytest
from alembic.config import Config
from alembic.script.revision import ResolutionError
from alembic.util.exc import CommandError

from app.infra import database as database_module
from app.infra.database import unknown_db_revisions


class _Scripts:
    def __init__(self, known: set[str], error: type[Exception] | None = None) -> None:
        self.known = known
        self.error = error

    def get_revision(self, revision: str) -> object | None:
        if revision in self.known:
            return object()
        if self.error is not None:
            if self.error is ResolutionError:
                raise ResolutionError("Can't locate revision", revision)
            raise self.error(f"Can't locate revision identified by '{revision}'")
        return None


def _patch(monkeypatch: pytest.MonkeyPatch, heads: tuple[str, ...], scripts: _Scripts) -> None:
    monkeypatch.setattr(
        database_module.MigrationContext,
        "configure",
        lambda _connection: SimpleNamespace(get_current_heads=lambda: heads),
    )
    monkeypatch.setattr(database_module.ScriptDirectory, "from_config", lambda _config: scripts)


@pytest.mark.parametrize("error", [None, CommandError, ResolutionError])
def test_unknown_revision_is_reported(
    monkeypatch: pytest.MonkeyPatch, error: type[Exception] | None
) -> None:
    _patch(monkeypatch, ("0008_onboarding",), _Scripts({"0007_run_warnings"}, error))
    assert unknown_db_revisions(object(), Config()) == ["0008_onboarding"]


def test_known_or_empty_revision_is_not_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch, ("0007_run_warnings",), _Scripts({"0007_run_warnings"}))
    assert unknown_db_revisions(object(), Config()) == []
    _patch(monkeypatch, (), _Scripts(set()))  # пустая БД
    assert unknown_db_revisions(object(), Config()) == []
