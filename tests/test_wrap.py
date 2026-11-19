"""Extension 2: /wrap helpers and the Stop hook."""
import json
import os
import subprocess
import sys
from pathlib import Path

import common
import wrap

HOOK = Path(__file__).resolve().parent.parent / "scripts" / "hooks" / "wrap_reminder.py"


def _git(root, *args):
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t", "GIT_CONFIG_GLOBAL": os.devnull}
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, env=env)


def _hook(root):
    r = subprocess.run([sys.executable, str(HOOK)], input="{}", capture_output=True, text=True,
                       env={**os.environ, "CLAUDE_PROJECT_DIR": str(root)})
    return r.stdout.strip()


def test_wrap_context_and_hook(repo, monkeypatch):
    _git(repo.root, "init", "-q")
    _git(repo.root, "add", "-A")
    _git(repo.root, "commit", "-qm", "init")
    assert _hook(repo.root) == ""  # clean tree: silent
    item = repo.root / "inbox" / "2026-11-25_conversation_decision.md"
    common.write_md(item, {"type": "conversation", "from": "owner"}, "## Contenu\n")
    msg = json.loads(_hook(repo.root))["systemMessage"]
    assert "non commité" in msg and "/wrap" in msg
    _git(repo.root, "add", "-A")
    _git(repo.root, "commit", "-qm", "doppel(wrap): décision")
    monkeypatch.delenv("DOPPEL_NOW")
    ctx = wrap.context(repo.root, common.now() - common.dt.timedelta(hours=1))
    assert ctx["commits"][0]["subject"] == "doppel(wrap): décision"
    assert "inbox/2026-11-25_conversation_decision.md" in ctx["commits"][0]["files"]
    assert ctx["wrap_items"] == ["inbox/2026-11-25_conversation_decision.md"] and ctx["uncommitted"] == []
