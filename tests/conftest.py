"""Fixtures: a throwaway doppel root with config and tasks written per test."""
import pytest

from helpers import NOW, Repo


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setenv("DOPPEL_NOW", NOW.strftime("%Y-%m-%d %H:%M"))
    return Repo(tmp_path)
