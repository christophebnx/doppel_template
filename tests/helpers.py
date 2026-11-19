"""Shared helpers of the unit tests (constants, Repo builder)."""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import common

WEEK = "2026-W48"  # Mon 2026-11-23 .. Sun 2026-11-29
NOW = dt.datetime(2026, 11, 20, 17, 0)  # Friday before the week


class Repo:
    def __init__(self, root: Path):
        self.root = root
        (root / "tasks").mkdir()
        self.config()

    def config(self, **capacity):
        cap = {"estimate_correction": 1.0, **capacity}
        text = "owner: Test\ntimezone: Europe/Brussels\ncapacity:\n"
        text += "".join(f"  {k}: {v}\n" for k, v in cap.items())
        text += "projects: {}\n"
        (self.root / "config.yaml").write_text(text)

    def task(self, tid, **meta):
        base = {"id": tid, "project": "p", "title": tid, "status": "todo", "priority": "P2", "executor": "me",
                "estimate_h": 1, "actual_h": None, "deadline": None, "depends_on": []}
        base.update(meta)
        common.write_md(self.root / "tasks" / f"{tid}.md", base, "body\n")
