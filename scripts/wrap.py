"""What this conversation already persisted, so /wrap only extracts what is still missing.

  wrap.py context [--since "AAAA-MM-JJ HH:MM" | --hours 12] [--json]

Prints: commits since that time (time · subject · files), uncommitted changes, and the /wrap items
(inbox/**/*_conversation_*.md) written since that time. Use the conversation's start time as --since when known.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path

from zoneinfo import ZoneInfo

from common import DEFAULT_TZ, fmt_dt, get_root, load_config, now as now_fn, parse_dt


def _git(root: Path, *args: str, tz: str = DEFAULT_TZ) -> str:
    env = {**os.environ, "TZ": tz}  # commit dates shown in doppel's time zone
    r = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, env=env)
    return r.stdout if r.returncode == 0 else ""


def context(root: Path, since: dt.datetime) -> dict:
    commits = []
    since_tz = since.replace(tzinfo=ZoneInfo(DEFAULT_TZ)).isoformat()
    out = _git(root, "log", f"--since={since_tz}", "--date=format-local:%Y-%m-%d %H:%M",
               "--format=@@%h\t%ad\t%s", "--name-only")
    cur = None
    for line in out.splitlines():
        if line.startswith("@@"):
            h, date, subject = (line[2:].split("\t") + ["", ""])[:3]
            cur = {"commit": h, "date": date, "subject": subject, "files": []}
            commits.append(cur)
        elif line.strip() and cur:
            cur["files"].append(line.strip())
    status = [l for l in _git(root, "status", "--porcelain").splitlines() if l.strip()]
    wraps = []
    for p in sorted((root / "inbox").rglob("*_conversation_*.md")):
        if dt.datetime.fromtimestamp(p.stat().st_mtime) >= since or any(str(p.relative_to(root)) in c["files"] for c in commits):
            wraps.append(str(p.relative_to(root)))
    return {"since": fmt_dt(since), "commits": commits, "uncommitted": status, "wrap_items": wraps}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("context"); c.add_argument("--since"); c.add_argument("--hours", type=float, default=12)
    c.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    root = get_root(args.root)
    since = parse_dt(args.since) if args.since else now_fn(load_config(root)) - dt.timedelta(hours=args.hours)
    ctx = context(root, since)
    if args.json:
        print(json.dumps(ctx, ensure_ascii=False, indent=1))
        return 0
    print(f"# Déjà persisté depuis {ctx['since']}")
    for c in ctx["commits"]:
        print(f"- {c['date']} {c['commit']} {c['subject']} ({len(c['files'])} fichiers: {', '.join(c['files'][:8])}{'…' if len(c['files']) > 8 else ''})")
    print("- aucun commit" if not ctx["commits"] else "")
    print("# Non commité\n" + ("\n".join(f"- {l}" for l in ctx["uncommitted"]) or "- rien"))
    print("# Fiches /wrap\n" + ("\n".join(f"- {w}" for w in ctx["wrap_items"]) or "- aucune"))
    return 0


if __name__ == "__main__":
    from common import run_main
    sys.exit(run_main(main, __file__))
