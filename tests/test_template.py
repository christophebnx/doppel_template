"""Template upgrade: framework changes flow into a project, project edits and data are kept, new config keys added."""
import subprocess

import pytest

import common
import template


def sh(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True).stdout.strip()


def commit(cwd, msg):
    sh(cwd, "add", "-A")
    sh(cwd, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", msg)
    return sh(cwd, "rev-parse", "HEAD")


CONFIG_V1 = "owner: À compléter\ntimezone: Europe/Brussels\nclimate:\n  min_score: 0.6\nprojects: {}\n"
CLAUDE_V1 = "# doppel\n\n## Skills\n- /today\n\n## Domain\n- à compléter\n"


@pytest.fixture
def pair(tmp_path):
    tpl, proj = tmp_path / "tpl", tmp_path / "proj"
    tpl.mkdir()
    sh(tpl, "init", "-q", "-b", "main")
    (tpl / "scripts").mkdir()
    (tpl / "scripts" / "a.py").write_text("print('v1')\n")
    (tpl / "CLAUDE.md").write_text(CLAUDE_V1)
    (tpl / "config.yaml").write_text(CONFIG_V1)
    v1 = commit(tpl, "v1")
    # project created from the template (no shared history), customised, with data
    subprocess.run(["cp", "-r", str(tpl), str(proj)], check=True)
    subprocess.run(["rm", "-rf", str(proj / ".git")], check=True)
    sh(proj, "init", "-q", "-b", "main")
    (proj / "CLAUDE.md").write_text(CLAUDE_V1.replace("- à compléter", "- maison et famille"))
    (proj / "config.yaml").write_text(CONFIG_V1.replace("À compléter", "Christophe").replace("0.6", "0.7"))
    (proj / "tasks").mkdir()
    (proj / "tasks" / "T-0001.md").write_text("donnée\n")
    common.write_config_block(proj, "template", {"repo": str(tpl), "ref": "main", "base": v1})
    commit(proj, "project")
    return tpl, proj, v1


def test_upgrade_brings_framework_changes_and_keeps_project_edits(pair):
    tpl, proj, v1 = pair
    (tpl / "scripts" / "a.py").write_text("print('v2')\n")
    (tpl / "scripts" / "b.py").write_text("new\n")
    (tpl / "CLAUDE.md").write_text(CLAUDE_V1.replace("- /today", "- /today\n- /collect"))
    (tpl / "config.yaml").write_text(CONFIG_V1.replace("  min_score: 0.6\n", "  min_score: 0.6\n  step_min: 30\n")
                                     .replace("projects:", "collect:\n  enabled: false\nprojects:"))
    v2 = commit(tpl, "v2")
    assert template.status(proj)["upstream_commits"][0].endswith("v2")
    assert template.upgrade(proj, dry_run=True)["config_added"] == ["climate", "collect"]
    res = template.upgrade(proj)
    assert res["status"] == "applied" and res["conflicts"] == []
    assert (proj / "scripts" / "a.py").read_text() == "print('v2')\n" and (proj / "scripts" / "b.py").exists()
    claude = (proj / "CLAUDE.md").read_text()
    assert "- /collect" in claude and "- maison et famille" in claude  # both sides kept
    cfg = common.load_config(proj)
    assert cfg["owner"] == "Christophe" and cfg["climate"] == {"min_score": 0.7, "step_min": 30}
    assert cfg["collect"] == {"enabled": False} and cfg["template"]["base"] == v2
    assert (proj / "tasks" / "T-0001.md").read_text() == "donnée\n"
    commit(proj, "upgrade")
    assert template.upgrade(proj)["status"] == "up-to-date"


def test_overlapping_edit_is_reported_as_conflict(pair):
    tpl, proj, _ = pair
    (proj / "scripts" / "a.py").write_text("print('projet')\n")
    commit(proj, "local change")
    (tpl / "scripts" / "a.py").write_text("print('v2')\n")
    commit(tpl, "v2")
    res = template.upgrade(proj)
    assert res["status"] == "conflicts" and res["conflicts"] == ["scripts/a.py"]


def test_excluded_paths_and_template_itself(pair):
    tpl, proj, v1 = pair
    common.write_config_block(proj, "template", {"repo": str(tpl), "ref": "main", "base": v1, "exclude": ["scripts/"]})
    commit(proj, "exclude scripts")
    (tpl / "scripts" / "a.py").write_text("print('v2')\n")
    commit(tpl, "v2")
    assert template.upgrade(proj)["files"] == []
    assert (proj / "scripts" / "a.py").read_text() == "print('v1')\n"
    sh(proj, "remote", "add", "origin", str(tpl))
    assert template.is_template(proj) and template.upgrade(proj)["status"] == "is-template"


def test_refuses_without_base_or_with_dirty_framework(pair):
    tpl, proj, v1 = pair
    (proj / "scripts" / "a.py").write_text("dirty\n")
    with pytest.raises(SystemExit, match="uncommitted"):
        template.upgrade(proj)
    common.write_config_block(proj, "template", {"repo": str(tpl), "ref": "main"})
    with pytest.raises(SystemExit, match="base"):
        template.upgrade(proj)


# --------------------------------------------------------------------------- /setup (scripts/setup.py)
import shutil  # noqa: E402

import setup  # noqa: E402

REPO = common.REPO_ROOT


@pytest.fixture
def fresh(tmp_path):
    for f in ("config.yaml", "CLAUDE.md", "preferences.md"):
        shutil.copy(REPO / f, tmp_path / f)
    return tmp_path


def test_setup_checklist_and_writes(fresh):
    assert set(setup.status(fresh)["missing"]) == {"owner", "domain", "claude_domain_section", "template_base"}
    setup.set_scalars(fresh, ["owner=Christophe", "domain=gestion de la maison et de la famille",
                              "timezone=Europe/Paris", "transcription_language=nl"])
    cfg = common.load_config(fresh)
    assert cfg["owner"] == "Christophe" and cfg["timezone"] == "Europe/Paris"
    assert cfg["transcription"]["language"] == "nl" and cfg["language"]["data"] == "fr"
    setup.set_domain(fresh, "- **Owner's domain**: maison, famille, papiers.\n- **A project is**: un chantier ou un dossier.")
    assert "un chantier ou un dossier" in (fresh / "CLAUDE.md").read_text() and "## Skills" in (fresh / "CLAUDE.md").read_text()
    common.write_config_block(fresh, "template", {"repo": "x", "ref": "main", "base": "abc"})
    assert setup.status(fresh)["missing"] == []


def test_setup_collect_needs_private_and_keeps_accounts_out_of_the_template(fresh):
    with pytest.raises(SystemExit, match="private"):
        setup.set_collect(fresh, enable=True)
    cur = setup.set_collect(fresh, enable=True, private=True, calendars=["famille@exemple.be=famille"],
                            exclude_from=["noreply@"])
    assert cur["calendars"] == [{"id": "famille@exemple.be", "alias": "famille"}] and cur["mail"]["exclude_from"] == ["noreply@"]
    assert common.load_config(fresh)["collect"]["mail"]["first_sync_days"] == 7  # other settings kept
    assert setup.status(fresh)["checks"]["collect_enabled"] is True
    tpl = common.load_config(REPO)  # the template itself names no account
    assert tpl["collect"]["calendars"] == [] and tpl["collect"]["enabled"] is False and not tpl["template"]["base"]
