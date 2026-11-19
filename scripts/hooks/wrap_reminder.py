"""Claude Code Stop hook: remind /wrap (or a commit) when the doppel repo has uncommitted changes.

Never blocks; prints a JSON `systemMessage` shown to the owner, or nothing when the tree is clean.
Stdlib only (runs before `uv sync`). Configured in .claude/settings.json.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def main() -> int:
    try:
        json.load(sys.stdin)  # hook input (unused, but consume it)
    except Exception:
        pass
    root = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[2])
    r = subprocess.run(["git", "-C", str(root), "status", "--porcelain"], capture_output=True, text=True)
    changed = [l for l in r.stdout.splitlines() if l.strip()] if r.returncode == 0 else []
    if changed:
        files = ", ".join(l[3:] for l in changed[:5]) + ("…" if len(changed) > 5 else "")
        msg = (f"doppel : {len(changed)} fichier(s) non commité(s) ({files}). "
               "Lancez /wrap (ou committez) avant de supprimer cette conversation.")
        print(json.dumps({"systemMessage": msg}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
