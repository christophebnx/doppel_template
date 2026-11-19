"""Kernel scenarios: the deterministic guarantees every doppel (whatever the domain) relies on."""
import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path

import common
import ids
import index
import logbook
import project
import signals
import tasks
import today

REPO = Path(__file__).resolve().parents[3]


def test_ids_are_never_reused_after_archive(doppel_root):
    root = doppel_root("2026-11-23 08:00")
    tasks.new_task(root, "p", "A")
    tasks.set_fields(root, "T-0001", ["status=done"])
    os.environ["DOPPEL_NOW"] = "2027-01-30 10:00"
    assert tasks.archive(root, 30, dry_run=False) == ["T-0001"]
    assert ids.next_id(root, "task") == "T-0002"


def test_waiting_task_gets_follow_up_from_script(doppel_root):
    root = doppel_root("2026-11-20 10:00")  # friday
    p = tasks.new_task(root, "p", "Recevoir le plan", status="waiting", waiting_on="person:jean-exemple",
                       expected_by="2026-11-24")
    meta, _ = common.read_md(p)
    assert meta["follow_up_after"] == dt.date(2026, 11, 25)
    os.environ["DOPPEL_NOW"] = "2026-11-25 08:00"
    assert list(tasks.due_followups(root)) == ["jean-exemple"]


def test_actual_hours_accumulate_without_llm_arithmetic(doppel_root):
    root = doppel_root("2026-11-23 08:00")
    tasks.new_task(root, "p", "A", estimate=2)
    tasks.set_fields(root, "T-0001", ["actual_h+=1h30"])
    assert tasks.set_fields(root, "T-0001", ["actual_h+=45min"])["actual_h"] == 2.25


def test_indexes_are_generated_and_checked(doppel_root):
    root = doppel_root("2026-11-23 08:00")
    tasks.new_task(root, "p", "A")
    assert index.main(["--root", str(root), "--check"]) == 1
    index.main(["--root", str(root)])
    assert index.main(["--root", str(root), "--check"]) == 0


def test_log_is_append_only_and_sourced(doppel_root):
    root = doppel_root("2026-11-23 08:00")
    line = logbook.add(root, "p", "decision", "Choix · option B", "inbox/_processed/x.md")
    assert line.endswith("· inbox/_processed/x.md") and "Choix - option B" in line
    logbook.add(root, "p", "info", "Autre", "s")
    text = (root / "log" / "2026-W48.md").read_text()
    assert text.index("Choix") < text.index("Autre")


def test_project_add_creates_brain_from_template(doppel_root):
    root = doppel_root("2026-11-23 08:00")
    project.add(root, "demo-project", "Projet démo")
    brain = (root / "projects" / "demo-project" / "brain.md").read_text()
    assert "Projet démo (demo-project)" in brain and "{" not in brain.splitlines()[0]
    assert "## Décisions" in brain


def test_signal_is_redacted_and_deduplicated(doppel_root):
    root = doppel_root("2026-11-23 08:00")
    kw = dict(emitter="skill:/ingest", kind="bug", component="scripts/tasks.py", fingerprint="ingest.x",
              severity="low", origin="self-report", observed="token=abcd1234secret mail jean@exemple.org")
    a = signals.emit(root, evidence="R-1", **kw)
    b = signals.emit(root, evidence="R-1", **kw)  # same evidence: no-op
    c = signals.emit(root, evidence="R-2", **kw)
    assert a["action"] == "created" and b["action"] == "unchanged" and c["action"] == "incremented"
    body = (root / "evolution" / "signals" / f"{a['id']}.md").read_text()
    assert "abcd1234secret" not in body and "jean@exemple.org" not in body


def test_today_sheet_lists_overdue_and_drafts(doppel_root):
    root = doppel_root("2026-11-23 08:00")
    tasks.new_task(root, "p", "En retard", deadline="2026-11-20")
    common.write_md(root / "outbox" / "2026-11-23_T-0001_x.md", {"title": "x", "state": "draft"}, "# x\n")
    text = today.render(today.facts(root))
    assert "en retard : T-0001" in text and "outbox/2026-11-23_T-0001_x.md" in text


def test_wrap_hook_reminds_uncommitted_changes(doppel_root, tmp_path):
    root = doppel_root("2026-11-23 08:00")
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t", "GIT_CONFIG_GLOBAL": os.devnull}
    for args in (["init", "-q"], ["add", "-A"], ["commit", "-qm", "init"]):
        subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, env=env)
    (root / "inbox" / "2026-11-23_note_x.md").write_text("x\n")
    hook = REPO / "scripts" / "hooks" / "wrap_reminder.py"
    out = subprocess.run([sys.executable, str(hook)], input="{}", capture_output=True, text=True,
                         env={**os.environ, "CLAUDE_PROJECT_DIR": str(root)}).stdout
    assert "/wrap" in json.loads(out)["systemMessage"]
