"""Extension 3: signals, runs, stats, groups, briefs, guards, observation, check_diff, evals compare."""
import datetime as dt
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

import check_diff
import common
import evals
import evolution
import signals

REPO = Path(__file__).resolve().parent.parent


def _setup(root):
    (root / "evolution" / "signals").mkdir(parents=True, exist_ok=True)
    (root / "templates").mkdir(exist_ok=True)
    shutil.copy(REPO / "templates" / "evolution-brief.md", root / "templates" / "evolution-brief.md")


def _emit(root, run, **kw):
    base = dict(emitter="skill:/ingest", kind="bug", component="scripts/tasks.py", fingerprint="Plan Block on OFF-day",
                severity="medium", origin="deterministic", run=run, commit="abc1234",
                observed="bloc placé sur un jour off", proofs=["logbook.py since --days 5"])
    base.update(kw)
    return signals.emit(root, **base)


def test_emit_dedup_increment_and_index(repo):
    _setup(repo.root)
    a = _emit(repo.root, "R-1")
    b = _emit(repo.root, "R-2")
    c = _emit(repo.root, "R-3")
    again = _emit(repo.root, "R-3")  # same evidence: no inflation
    assert a["action"] == "created" and a["id"] == "S-0001"
    assert (b["action"], c["occurrences"], again["action"]) == ("incremented", 3, "unchanged")
    meta, body = common.read_md(repo.root / "evolution/signals/S-0001.md")
    assert meta["fingerprint"] == "plan-block-on-off-day" and meta["occurrences"] == 3 and len(meta["evidence"]) == 3
    assert body.count("R-") >= 2 and "## Hypothèse" in body
    idx = (repo.root / "evolution/signals/_index.md").read_text()
    assert "S-0001 · open · deterministic · bug · medium · ×3" in idx
    other = _emit(repo.root, "R-4", fingerprint="other.thing")
    assert other["id"] == "S-0002"


def test_emit_redacts_and_keeps_most_reliable_origin(repo):
    _setup(repo.root)
    _emit(repo.root, "R-1", origin="ingestion", proofs=["password=Zq9secretvalue42 at https://x.internal/a"])
    r = _emit(repo.root, "R-2", origin="user")
    meta, body = common.read_md(repo.root / "evolution/signals/S-0001.md")
    assert "Zq9secretvalue42" not in body and "x.internal" not in body
    assert meta["origin"] == "user" and meta["origins"] == {"ingestion": 1, "user": 1} and r["occurrences"] == 2


def test_runs_stats_and_rates(repo, monkeypatch):
    _setup(repo.root)
    r1 = signals.run_start(repo.root, "ingest", "2026-W48")
    r2 = signals.run_start(repo.root, "ingest")
    assert r1 != r2 and r2.endswith("-2")
    signals.run_end(repo.root, r1, "ok")
    _emit(repo.root, r2)
    signals.run_end(repo.root, r2, "partial", ["S-0001"])
    signals.run_start(repo.root, "status")
    now = common.now()
    st = signals.stats(repo.root, now - dt.timedelta(days=1), now + dt.timedelta(minutes=1))
    assert st["runs"] == 3 and st["signals"] == 1 and st["rate"] == 0.333
    assert st["by_skill"]["ingest"] == {"runs": 2, "signals": 1, "rate": 0.5}
    lines = (repo.root / "evolution/runs/2026-W47.jsonl").read_text().splitlines()
    assert json.loads(lines[-2])["outcome"] == "partial" and json.loads(lines[-2])["signals"] == ["S-0001"]


def test_groups_eligibility_rules(repo):
    _setup(repo.root)
    _emit(repo.root, "R-1", fingerprint="inj.only", origin="ingestion")
    _emit(repo.root, "R-2", fingerprint="self.few", origin="self-report")
    for i in range(3):
        _emit(repo.root, f"R-s{i}", fingerprint="self.many", origin="self-report")
    _emit(repo.root, "R-3", fingerprint="user.one", origin="user", kind="user-correction")
    g = {x["fingerprint"]: x for x in signals.groups(repo.root)}
    assert not g["inj.only"]["eligible"] and "ingestion" in g["inj.only"]["eligibility"]
    assert not g["self.few"]["eligible"] and g["self.many"]["eligible"] and g["user.one"]["eligible"]
    assert g["user.one"]["score"] == 6.0  # medium(2) × user weight(3) × 1 occurrence × recency 1


def test_risk_classes():
    assert evolution.risk([".claude/skills/status/SKILL.md", "tests/evals/scenarios/test_x.py"])[0] == "low"
    assert evolution.risk([".claude/agents/reporter.md"], logic=True)[0] == "medium"
    assert evolution.risk(["scripts/logbook.py"])[0] == "medium"
    assert evolution.risk(["scripts/common.py"])[0] == "high"
    assert evolution.risk([".claude/skills/a.md", "templates/b.md", "scripts/c.py"])[0] == "high"
    assert evolution.risk(["templates/task.md"], format_change=True)[0] == "high"
    level, reasons = evolution.risk(["CLAUDE.md", ".claude/skills/plan/SKILL.md"], logic=True)
    assert level == "high" and "noyau protégé" in reasons[0]


def test_brief_lifecycle_guard_and_observe(repo, monkeypatch):
    _setup(repo.root)
    _emit(repo.root, "R-1", origin="user")
    b = evolution.new_brief(repo.root, "Pas de bloc sur un jour off", "scripts/logbook.py", ["S-0001"],
                            ["scripts/logbook.py"], 6.0)
    assert b["id"] == "E-001" and b["risk"] == "medium"
    assert common.read_md(repo.root / "evolution/signals/S-0001.md")[0]["status"] == "grouped"
    with pytest.raises(SystemExit):
        evolution.set_status(repo.root, "E-001", "merged")  # proposed → merged is not allowed
    for s in ("approved", "running", "merged", "observing"):
        evolution.set_status(repo.root, "E-001", s)
    assert evolution.component_in_cooldown(repo.root, "scripts/logbook.py")
    # the same problem comes back after the merge → degraded → revert, signals reopened
    monkeypatch.setenv("DOPPEL_NOW", "2026-11-22 17:00")
    signals.run_start(repo.root, "plan")
    _emit(repo.root, "R-after", origin="deterministic")
    obs = evolution.observe(repo.root, "E-001")
    assert obs["verdict"] == "degraded" and obs["action"] == "revert"
    evolution.set_status(repo.root, "E-001", "reverted", "dégradation")
    assert common.read_md(repo.root / "evolution/signals/S-0001.md")[0]["status"] == "open"
    line = evolution.changelog(repo.root, "E-001", "revert de la correction")
    assert "E-001 · scripts/logbook.py" in line and "reverted" in line


def test_observe_counts_brief_fingerprints_not_only_component(repo, monkeypatch):
    _setup(repo.root)
    monkeypatch.setenv("DOPPEL_NOW", "2026-11-20 09:00")
    signals.run_start(repo.root, "plan")
    _emit(repo.root, "R-1")  # component logbook.py (the detector)
    evolution.new_brief(repo.root, "fix", "scripts/dates.py", ["S-0001"], ["scripts/dates.py"])  # the real cause
    monkeypatch.setenv("DOPPEL_NOW", "2026-11-20 10:00")
    for s in ("approved", "running", "merged", "observing"):
        evolution.set_status(repo.root, "E-001", s)
    monkeypatch.setenv("DOPPEL_NOW", "2026-11-28 09:00")
    signals.run_start(repo.root, "plan")
    obs = evolution.observe(repo.root, "E-001")
    assert obs["before"]["signals"] == 1 and obs["after"]["signals"] == 0 and obs["verdict"] == "improved"
    assert obs["action"] == "validate"


def test_guard_stop_and_startup(repo, monkeypatch):
    _setup(repo.root)
    (repo.root / "config.yaml").write_text((repo.root / "config.yaml").read_text().replace(
        "projects: {}", "evolution:\n  autonomy: execute\n  merge: auto\nprojects: {}"))
    g = evolution.guard(repo.root, "improve")
    assert g["ok"] and g["autonomy"] == "propose" and g["merge"] == "pr" and "garde de démarrage" in g["notes"][0]
    (repo.root / "evolution" / "STOP").write_text("test\n")
    assert not evolution.guard(repo.root, "evolve")["ok"]


def _git(root, *args):
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t", "GIT_CONFIG_GLOBAL": os.devnull}
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, env=env)


def test_check_diff(tmp_path):
    root = tmp_path
    for rel in ("CLAUDE.md", "config.yaml", "evolution/protected.txt"):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO / rel, root / rel)
    for rel in (".claude/skills/status/SKILL.md", "tests/evals/scenarios/test_eval_x.py", "scripts/logbook.py"):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text("v1\n")
    _git(root, "init", "-q", "-b", "main"); _git(root, "add", "-A"); _git(root, "commit", "-qm", "base")
    _git(root, "checkout", "-q", "-b", "evolve/E-001")
    (root / ".claude/skills/status/SKILL.md").write_text("v2\n")
    (root / "tests/evals/scenarios/test_eval_new.py").write_text("new\n")
    _git(root, "add", "-A"); _git(root, "commit", "-qm", "ok change")
    assert check_diff.check(root, "main", "HEAD")["ok"]
    # existing scenario modified + core line of CLAUDE.md + protected script
    (root / "tests/evals/scenarios/test_eval_x.py").write_text("weakened\n")
    text = (root / "CLAUDE.md").read_text().replace("11. **A self-modifying system", "11. **A system")
    (root / "CLAUDE.md").write_text(text)
    (root / "evolution/protected.txt").write_text("# emptied\n")
    _git(root, "add", "-A"); _git(root, "commit", "-qm", "bad change")
    res = check_diff.check(root, "main", "HEAD")
    reasons = "\n".join(res["reasons"])
    assert not res["ok"]
    assert "section protégée" in reasons and "test_eval_x.py : scénario" in reasons and "evolution/protected.txt : fichier protégé" in reasons
    assert "CLAUDE.md : hors allowed_paths" in reasons


def test_check_diff_non_core_claude_md_line_is_only_out_of_allowed_paths(tmp_path):
    root = tmp_path
    for rel in ("CLAUDE.md", "config.yaml", "evolution/protected.txt"):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO / rel, root / rel)
    _git(root, "init", "-q", "-b", "main"); _git(root, "add", "-A"); _git(root, "commit", "-qm", "base")
    (root / "CLAUDE.md").write_text((root / "CLAUDE.md").read_text() + "\nextra line\n")
    _git(root, "add", "-A"); _git(root, "commit", "-qm", "tail")
    reasons = check_diff.check(root, "HEAD~1", "HEAD")["reasons"]
    assert reasons == ["CLAUDE.md : hors allowed_paths"]


def test_evals_compare():
    a = {"commit": "a", "totals": {}, "scenarios": {"x": {"status": "pass", "score": 1.0}, "y": {"status": "fail", "score": 0}}}
    b = {"commit": "b", "totals": {}, "scenarios": {"x": {"status": "fail", "score": 0}, "y": {"status": "pass", "score": 1},
                                                    "z": {"status": "fail", "score": 0}}}
    c = evals.compare(a, b)
    assert not c["ok"] and c["regressions"][0]["id"] == "x" and c["improvements"] == ["y"] and c["new_failures"] == ["z"]
    assert evals.compare(a, {**a, "commit": "c"})["ok"]


def test_mechanical_detections(repo, monkeypatch):
    import tasks
    _setup(repo.root)
    repo.task("T-0001", estimate_h=2)
    tasks.set_fields(repo.root, "T-0001", ["status=done", "actual_h=4"])
    sigs = {m["fingerprint"]: m for m, _, _ in signals.load_signals(repo.root).values()}
    assert sigs["tasks.estimate-overrun"]["origin"] == "deterministic"


def test_script_crash_becomes_signal(repo, monkeypatch):
    _setup(repo.root)
    monkeypatch.setenv("DOPPEL_ROOT", str(repo.root))

    def boom():
        raise KeyError("client data must not leak")
    with pytest.raises(KeyError):
        common.run_main(boom, "scripts/fake.py")
    meta, body = common.read_md(repo.root / "evolution/signals/S-0001.md")
    assert meta["origin"] == "deterministic" and meta["fingerprint"].startswith("script.fake.keyerror")
    assert "client data" not in body


def test_scan_owner_edits_without_false_positives(tmp_path):
    root = tmp_path
    (root / "evolution" / "signals").mkdir(parents=True)
    shutil.copy(REPO / "config.yaml", root / "config.yaml")
    (root / "outbox").mkdir()
    (root / "examples").mkdir()
    body = "---\nstate: draft\n---\n\n# Status\n" + "\n".join(f"- ligne {i}" for i in range(20)) + "\n"
    (root / "examples" / "copy.md").write_text(body)
    _git(root, "init", "-q", "-b", "main"); _git(root, "add", "-A"); _git(root, "commit", "-qm", "fixture copy")
    (root / "outbox" / "d.md").write_text(body)
    _git(root, "add", "-A"); _git(root, "commit", "-qm", "doppel(status): brouillon")
    assert signals.scan(root) == []  # a similar file elsewhere must not be followed
    (root / "outbox" / "d.md").write_text(body.replace("ligne 3", "ligne réécrite"))
    _git(root, "add", "-A"); _git(root, "commit", "-qm", "retouche du status")
    res = signals.scan(root)
    assert len(res) == 1 and res[0]["action"] == "created" and res[0]["file"] == "outbox/d.md"
    assert signals.scan(root)[0]["action"] == "unchanged"  # re-scan never inflates
