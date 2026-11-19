"""Fixtures of the evaluation harness: a throwaway doppel tree with the config and templates of the current commit.  PROTECTED."""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

import common

REPO = Path(__file__).resolve().parents[2]
DATA_DIRS = ("inbox/_processed", "inbox/_raw", "tasks", "projects", "log", "outbox", "evolution/signals",
             "evolution/briefs", "evolution/runs")


@pytest.fixture
def doppel_root(tmp_path, monkeypatch):
    """doppel_root(now, fixtures=None) → Path of a fresh tree (config, templates, empty data folders, questions.md,
    preferences.md of the current commit). `fixtures` = a folder under tests/evals/fixtures/ copied on top."""
    def make(now: str, fixtures: str | None = None) -> Path:
        root = tmp_path / (fixtures or "root")
        root.mkdir()
        for f in ("config.yaml", "questions.md", "preferences.md"):
            shutil.copy(REPO / f, root / f)
        shutil.copytree(REPO / "templates", root / "templates")
        for d in DATA_DIRS:
            (root / d).mkdir(parents=True, exist_ok=True)
        monkeypatch.setenv("DOPPEL_NOW", now)
        common.write_config_projects(root, {})
        if fixtures:
            shutil.copytree(REPO / "tests" / "evals" / "fixtures" / fixtures, root, dirs_exist_ok=True)
        return root
    return make
