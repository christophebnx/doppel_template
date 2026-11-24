"""Structural consistency of the protocol: CLAUDE.md, skills, agents, scripts, templates, empty real data."""
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
SKILLS = ["add", "ingest", "answer", "ask", "done", "status", "today", "consolidate", "wrap", "signal", "evolve",
          "improve", "new-skill", "place"]
AGENTS = {"triage": "sonnet", "brain-keeper": "sonnet", "curator": "sonnet", "reporter": "haiku", "steward": "opus"}
TEMPLATES = ["task", "brain", "status", "inbox-item", "outbox-item", "signal", "evolution-brief", "skill", "agent"]


def frontmatter(path: Path) -> dict:
    m = re.match(r"\A---\n(.*?)\n---", path.read_text(encoding="utf-8"), re.S)
    assert m, f"{path} has no frontmatter"
    return yaml.safe_load(m.group(1))


def test_claude_md_is_short_and_lists_everything():
    text = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    assert len(text.splitlines()) <= 200
    for s in SKILLS:
        assert f"`/{s}" in text, s
    for a in AGENTS:
        assert f"`{a}`" in text, a
    for script in re.findall(r"`(\w+\.py)`", text):
        assert (ROOT / "scripts" / script).exists(), script


def test_skills():
    for s in SKILLS:
        fm = frontmatter(ROOT / ".claude" / "skills" / s / "SKILL.md")
        assert fm["name"] == s and len(fm["description"]) > 40
        body = (ROOT / ".claude" / "skills" / s / "SKILL.md").read_text(encoding="utf-8")
        assert "Unattended" in body, f"{s}: missing unattended behaviour"


def test_agents():
    for a, model in AGENTS.items():
        fm = frontmatter(ROOT / ".claude" / "agents" / f"{a}.md")
        assert fm["name"] == a and fm["model"] == model and fm["tools"] and fm["description"]
        assert "## Never" in (ROOT / ".claude" / "agents" / f"{a}.md").read_text(encoding="utf-8")


def test_skill_and_agent_script_references_exist():
    # docs/extending.md lists files of the doppel_klee reference implementation (optional modules): not checked here
    files = list((ROOT / ".claude").rglob("*.md")) + [p for p in (ROOT / "docs").glob("*.md") if p.name != "extending.md"]
    for f in files:
        for script in set(re.findall(r"scripts/(\w+\.py)", f.read_text(encoding="utf-8"))):
            assert (ROOT / "scripts" / script).exists(), f"{f}: scripts/{script}"
        for tpl in set(re.findall(r"templates/([\w-]+\.md)", f.read_text(encoding="utf-8"))):
            assert (ROOT / "templates" / tpl).exists(), f"{f}: templates/{tpl}"


def test_templates_present():
    for t in TEMPLATES:
        assert (ROOT / "templates" / f"{t}.md").exists()


def test_preferences_file_is_referenced_and_read_first():
    assert (ROOT / "preferences.md").exists()
    claude = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    assert "read `preferences.md`" in claude and "Conversations are disposable" in claude
    for a in AGENTS:
        assert "Read `preferences.md` first" in (ROOT / ".claude" / "agents" / f"{a}.md").read_text(encoding="utf-8")
    assert "conversation" in (ROOT / "templates" / "inbox-item.md").read_text(encoding="utf-8")


def test_stop_hook_is_configured():
    import json
    cfg = json.loads((ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))
    cmd = cfg["hooks"]["Stop"][0]["hooks"][0]["command"]
    assert "wrap_reminder.py" in cmd and (ROOT / "scripts" / "hooks" / "wrap_reminder.py").exists()


def test_every_skill_is_instrumented():
    for s in SKILLS:
        body = (ROOT / ".claude" / "skills" / s / "SKILL.md").read_text(encoding="utf-8")
        assert f"signals.py run start --skill {s}" in body and "signals.py run end" in body and "retro" in body, s


def test_core_markers_and_protected_list():
    claude = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    b, e = claude.index("<!-- core:begin"), claude.index("<!-- core:end")
    assert b < claude.index("1. **Files = state.**") < claude.index("15. **Python counts.**") < e
    prot = (ROOT / "evolution" / "protected.txt").read_text(encoding="utf-8")
    for p in ("CLAUDE.md#core", "config.yaml", "evolution/protected.txt", ".claude/skills/evolve/", ".claude/skills/improve/",
              ".claude/agents/steward.md", "scripts/check_diff.py", "scripts/redact.py", "scripts/signals.py", "scripts/evals.py",
              "tests/evals/scenarios/**#existing", "tests/evals/rubrics/**#existing"):
        assert p in prot, p


def test_no_lot_files_tracked():
    import subprocess
    files = subprocess.run(["git", "-C", str(ROOT), "ls-files"], capture_output=True, text=True).stdout.splitlines()
    assert not [f for f in files if f.endswith((".zip", ".eml", ".msg"))]
