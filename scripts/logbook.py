"""Append-only work log (log/AAAA-Wnn.md).

Line format:  - AAAA-MM-JJ HH:MM · <project> · <type> · <texte> · <source>
types: done | decision | info | blocked | planned

  logbook.py add --project demo-project --type done --text "..." --source inbox/_processed/x.md [--at "2026-11-17 10:00"]
  logbook.py since --days 5 [--project p] [--type done,decision]     entries of the last N days (today included)
  logbook.py old --weeks 8                                          weekly log files older than N weeks (for roll-up)
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from pathlib import Path

from common import get_root, load_config, now as now_fn, parse_dt, shift_week, week_of

TYPES = ("done", "decision", "info", "blocked", "planned")
LINE_RE = re.compile(r"^- (\d{4}-\d{2}-\d{2} \d{2}:\d{2}) · ([^·]+?) · (\w+) · (.*) · ([^·]+)$")


def add(root: Path, project: str, etype: str, text: str, source: str, at: dt.datetime | None = None) -> str:
    if etype not in TYPES:
        raise SystemExit(f"invalid type {etype}; expected {TYPES}")
    at = at or now_fn(load_config(root))
    text = " ".join(text.split()).replace(" · ", " - ")
    line = f"- {at:%Y-%m-%d %H:%M} · {project} · {etype} · {text} · {source}"
    path = root / "log" / f"{week_of(at)}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(f"# Log {week_of(at)}\n\n", encoding="utf-8")
    with path.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    return line


def parse_lines(path: Path):
    for raw in path.read_text(encoding="utf-8").splitlines():
        m = LINE_RE.match(raw.strip())
        if m:
            yield {"at": m.group(1), "project": m.group(2), "type": m.group(3), "text": m.group(4), "source": m.group(5), "line": raw}


def since(root: Path, days: int, project: str | None = None, types: set | None = None) -> list[dict]:
    now = now_fn(load_config(root))
    start = dt.datetime.combine(now.date() - dt.timedelta(days=days - 1), dt.time())
    out = []
    w, last = week_of(start), week_of(now)
    weeks = [w]
    while w != last:
        w = shift_week(w, 1)
        weeks.append(w)
    for wk in weeks:
        p = root / "log" / f"{wk}.md"
        if not p.exists():
            continue
        for e in parse_lines(p):
            if parse_dt(e["at"]) < start:
                continue
            if project and e["project"] != project:
                continue
            if types and e["type"] not in types:
                continue
            out.append(e)
    return out


def old_files(root: Path, weeks: int) -> list[Path]:
    limit = shift_week(week_of(now_fn(load_config(root))), -weeks)
    return sorted(p for p in (root / "log").glob("*-W*.md") if p.stem < limit)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add")
    a.add_argument("--project", required=True); a.add_argument("--type", required=True, choices=TYPES)
    a.add_argument("--text", required=True); a.add_argument("--source", required=True); a.add_argument("--at")
    s = sub.add_parser("since"); s.add_argument("--days", type=int, default=5); s.add_argument("--project"); s.add_argument("--type")
    o = sub.add_parser("old"); o.add_argument("--weeks", type=int, default=8)
    args = ap.parse_args(argv)
    root = get_root(args.root)
    if args.cmd == "add":
        print(add(root, args.project, args.type, args.text, args.source, parse_dt(args.at) if args.at else None))
    elif args.cmd == "since":
        types = set(args.type.split(",")) if args.type else None
        for e in since(root, args.days, args.project, types):
            print(e["line"])
    elif args.cmd == "old":
        for p in old_files(root, args.weeks):
            print(p.relative_to(root))
    return 0


if __name__ == "__main__":
    from common import run_main
    sys.exit(run_main(main, __file__))
