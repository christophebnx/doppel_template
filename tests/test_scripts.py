"""Tests for the deterministic helpers."""
import datetime as dt
import shutil
from pathlib import Path

import calibrate
import common
import dates
import ids
import index
import logbook
import project
import tasks
from helpers import WEEK

REPO = Path(__file__).resolve().parent.parent


def test_iso_week_helpers():
    assert common.week_of(dt.date(2026, 11, 17)) == "2026-W47"
    assert common.week_monday("2026-W48") == dt.date(2026, 11, 23)
    assert common.shift_week("2026-W53", 1) == "2027-W01"
    assert dates.add_workdays(dt.date(2026, 11, 20), 1) == dt.date(2026, 11, 23)  # fri -> mon


def test_tasks_new_set_list_archive(repo, monkeypatch):
    p = tasks.new_task(repo.root, "p", "Faire X", estimate=2, deadline="2026-11-24", sources=["inbox/_processed/a.md"])
    assert p.name == "T-0001.md"
    assert ids.next_id(repo.root, "task") == "T-0002"
    meta = tasks.set_fields(repo.root, "T-0001", ["status=done", "actual_h=2.5", "sources+=inbox/_processed/b.md"])
    assert meta["status"] == "done" and meta["actual_h"] == 2.5 and len(meta["sources"]) == 2
    assert tasks.set_fields(repo.root, "T-0001", ["remaining_h=1.5"])["estimate_h"] == 4.0
    assert tasks.set_fields(repo.root, "T-0001", ["actual_h+=1h30"])["actual_h"] == 4.0
    assert [tasks.parse_hours(x) for x in ("2", "1,5", "1h30", "2h", "45min")] == [2.0, 1.5, 1.5, 2.0, 0.75]
    monkeypatch.setenv("DOPPEL_NOW", "2027-01-30 10:00")
    assert tasks.archive(repo.root, 30, dry_run=False) == ["T-0001"]
    assert ids.next_id(repo.root, "task") == "T-0002"  # archived ids are never reused


def test_logbook_append_and_since(repo):
    logbook.add(repo.root, "p", "done", "Fini · le modèle", "inbox/_processed/x.md", common.parse_dt("2026-11-18 10:00"))
    logbook.add(repo.root, "p", "info", "Vieux", "s", common.parse_dt("2026-11-02 10:00"))
    text = (repo.root / "log" / "2026-W47.md").read_text()
    assert "- 2026-11-18 10:00 · p · done · Fini - le modèle · inbox/_processed/x.md" in text
    got = logbook.since(repo.root, 5)
    assert [e["text"] for e in got] == ["Fini - le modèle"]


def test_index_generation(repo):
    tasks.new_task(repo.root, "p", "A", priority="P3")
    tasks.new_task(repo.root, "p", "B", priority="P1")
    index.main(["--root", str(repo.root)])
    lines = (repo.root / "tasks" / "_index.md").read_text().splitlines()
    rows = [l for l in lines if l.startswith("T-")]
    assert rows[0].startswith("T-0002") and "P1" in rows[0]
    assert index.main(["--root", str(repo.root), "--check"]) == 0


def test_project_add_keeps_config_comments(repo):
    (repo.root / "templates").mkdir()
    shutil.copy(REPO / "templates" / "brain.md", repo.root / "templates" / "brain.md")
    cfg = repo.root / "config.yaml"
    cfg.write_text("# keep me\n" + cfg.read_text())
    project.add(repo.root, "demo", "Demo")
    project.set_fields(repo.root, "demo", ["active=false"])
    text = cfg.read_text()
    assert text.startswith("# keep me") and "active: false" in text
    assert (repo.root / "projects" / "demo" / "brain.md").exists()
    common.set_config_scalar(repo.root, "estimate_correction", 1.2)
    assert common.load_config(repo.root)["capacity"]["estimate_correction"] == 1.2


def test_calibrate(repo):
    for i in range(5):
        repo.task(f"T-000{i + 1}", status="done", estimate_h=2, actual_h=3, updated="2026-11-18")
    r = calibrate.compute(repo.root)
    assert r["ratio"] == 1.5 and r["new"] == 1.25 and r["changed"]
    repo.task("T-0001", status="done", estimate_h=2, actual_h=3, updated="2025-01-01")
    assert calibrate.compute(repo.root)["n"] == 4 and not calibrate.compute(repo.root)["changed"]


def test_frontmatter_has_no_yaml_aliases(repo):
    p = tasks.new_task(repo.root, "p", "X")  # created == updated (same date object)
    assert "&id" not in p.read_text() and "*id" not in p.read_text()


def test_tasks_scheduled_on_fields(repo):
    p = tasks.new_task(repo.root, "p", "Revoir les tests", scheduled_on="2026-11-26", scheduled_window="08:30-12:30",
                       deadline="2026-11-27")
    meta, _ = common.read_md(p)
    assert meta["scheduled_on"] == dt.date(2026, 11, 26) and meta["scheduled_window"] == "08:30-12:30"
    assert list(meta).index("deadline") < list(meta).index("scheduled_on")
    import pytest
    with pytest.raises(SystemExit):
        tasks.set_fields(repo.root, "T-0001", ["scheduled_window=matin"])
    assert tasks.set_fields(repo.root, "T-0001", ["scheduled_on=2026-11-30"])["scheduled_on"] == dt.date(2026, 11, 30)


def test_executors_are_configurable(repo):
    import pytest
    with pytest.raises(SystemExit):
        tasks.new_task(repo.root, "p", "X", executor="robot")
    cfg = repo.root / "config.yaml"
    cfg.write_text("executors: [robot]\n" + cfg.read_text())
    assert tasks.new_task(repo.root, "p", "X", executor="robot").exists()


def test_today_facts(repo, monkeypatch):
    import today
    monkeypatch.setenv("DOPPEL_NOW", "2026-11-23 08:00")
    tasks.new_task(repo.root, "p", "Urgent", priority="P1", deadline="2026-11-20")
    tasks.new_task(repo.root, "p", "Bientôt", deadline="2026-11-25")
    f = today.facts(repo.root)
    assert [x["task"] for x in f["tasks"]["overdue"]] == ["T-0001"]
    assert [x["task"] for x in f["tasks"]["due_soon"]] == ["T-0002"]
    assert "T-0001 Urgent" in today.render(f)
