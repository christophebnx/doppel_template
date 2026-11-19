"""Task files (tasks/T-nnnn.md): create, update fields, list, archive.

  tasks.py new --project demo-project --title "..." [--status todo] [--priority P2] [--executor me]
               [--estimate 2] [--confidence medium] [--deadline 2026-11-24]
               [--depends-on T-0001,person:jean-exemple] [--source inbox/_processed/x.md ...] [--body "..."]
  tasks.py set T-0001 status=done actual_h=2.5 [sources+=inbox/_processed/y.md]   (updates `updated`)
  tasks.py set T-0001 actual_h+=1h30     add time spent (durations: 2, 1.5, 1h30, 45min)
  tasks.py set T-0001 remaining_h=3      derive estimate_h from a "remaining hours" statement (e.g. « reste ~3 h »)
  tasks.py new … --status waiting --waiting-on person:jean-exemple [--expected-by 2026-11-26] [--from 2026-11-20]
               follow_up_after = expected_by + 1 workday, else (--from|today) + 3 workdays
  tasks.py new … --scheduled-on 2026-11-26 [--window 08:30-12:30]   day to DO it (deadline = day it is DUE)
  tasks.py followups [--json]            waiting tasks whose follow_up_after is today or past, grouped by person
  tasks.py bump-followup T-0001 [--workdays 3]    after a follow-up was drafted: next check in N workdays
  tasks.py list [--status todo,doing] [--project p] [--executor me] [--json]
  tasks.py archive --older-than 30 [--dry-run]      move done/dropped tasks (updated > N days ago) to tasks/_archive/
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

import yaml

from common import CLOSED_STATUSES, get_root, load_config, load_tasks, now as now_fn, parse_date, read_md, write_md
from dates import add_workdays
from ids import next_id

FIELD_ORDER = [
    "id", "project", "title", "status", "priority", "executor", "estimate_h", "estimate_range_h", "confidence",
    "actual_h", "deadline", "scheduled_on", "scheduled_window", "depends_on", "waiting_on", "expected_by", "follow_up_after",
    "sources", "created", "updated",
]
STATUSES = ("clarify", "todo", "doing", "blocked", "waiting", "done", "dropped")
OPTIONAL_FIELDS = ("estimate_range_h", "waiting_on", "expected_by", "follow_up_after", "scheduled_on",
                   "scheduled_window")  # omitted when empty
DATE_FIELDS = ("deadline", "expected_by", "follow_up_after", "scheduled_on")
WINDOW_RE = re.compile(r"^\d{2}:\d{2}-\d{2}:\d{2}$")
PRIORITIES = ("P1", "P2", "P3")
EXECUTORS = ("me", "doppel")  # default; extend with config.yaml `executors:` (e.g. claude-code, assistant)
LIST_FIELDS = ("depends_on", "sources", "estimate_range_h")

DEFAULT_BODY = "## Contexte\n\n## Questions ouvertes\n\n## Progression\n"


def executors(root: Path) -> tuple[str, ...]:
    extra = load_config(root).get("executors") or []
    return tuple(dict.fromkeys([*EXECUTORS, *extra]))


def _ordered(meta: dict) -> dict:
    out = {k: meta.get(k) for k in FIELD_ORDER}
    out.update({k: v for k, v in meta.items() if k not in out})
    return out


HOUR_FIELDS = ("estimate_h", "actual_h", "remaining_h")


def parse_hours(value: str) -> float:
    """'2' '1.5' '1,5' '1h30' '2h' '45min' '45 min' -> hours as float."""
    v = str(value).strip().lower().replace(" ", "").replace(",", ".")
    m = re.fullmatch(r"(?:(\d+(?:\.\d+)?)h)?(?:(\d+)(?:min|m)?)?", v)
    if "h" not in v and not v.endswith(("min", "m")):
        return float(v)
    if not m or not (m.group(1) or m.group(2)):
        raise SystemExit(f"cannot parse duration '{value}'")
    h = float(m.group(1) or 0)
    mins = int(m.group(2) or 0)
    return round(h + mins / 60, 2)


def _coerce(key: str, value: str, root: Path | None = None):
    if key in HOUR_FIELDS:
        return None if value in ("", "null", "none") else parse_hours(value)
    if key == "estimate_range_h":
        return [parse_hours(v) for v in value.split(",") if v.strip()]
    if key in LIST_FIELDS:
        return [v.strip() for v in value.split(",") if v.strip()]
    if value in ("", "null", "none"):
        return None
    parsed = yaml.safe_load(value)
    if key == "status" and parsed not in STATUSES:
        raise SystemExit(f"invalid status {parsed}; expected {STATUSES}")
    if key == "priority" and parsed not in PRIORITIES:
        raise SystemExit(f"invalid priority {parsed}")
    if key == "executor" and parsed not in (executors(root) if root else EXECUTORS):
        raise SystemExit(f"invalid executor {parsed}")
    if key == "scheduled_window":
        if not WINDOW_RE.match(str(value)):
            raise SystemExit("scheduled_window must be HH:MM-HH:MM (e.g. 08:30-12:30)")
        return str(value)
    if key in DATE_FIELDS and parsed is not None:
        parsed = parse_date(parsed)
    if key == "waiting_on" and parsed and not str(parsed).startswith("person:"):
        raise SystemExit("waiting_on must be person:<slug>")
    return parsed


def follow_up_date(expected_by: dt.date | None, ref: dt.date) -> dt.date:
    """Announced date + 1 workday; without an announced date, reference date + 3 workdays."""
    return add_workdays(expected_by, 1) if expected_by else add_workdays(ref, 3)


def new_task(root: Path, project: str, title: str, *, status="todo", priority="P2", executor="me",
             estimate=None, confidence=None, deadline=None, depends_on=None,
             sources=None, body: str | None = None, waiting_on=None, expected_by=None, ref_date=None,
             scheduled_on=None, scheduled_window=None) -> Path:
    today = now_fn(load_config(root)).date()
    if status == "waiting" and not waiting_on:
        raise SystemExit("status waiting requires --waiting-on person:<slug>")
    if executor not in executors(root):
        raise SystemExit(f"invalid executor {executor}; expected {executors(root)}")
    tid = next_id(root, "task")
    expected = parse_date(expected_by)
    follow = follow_up_date(expected, parse_date(ref_date) or today) if status == "waiting" else None
    meta = _ordered({
        "id": tid, "project": project, "title": title, "status": status, "priority": priority,
        "executor": executor, "estimate_h": estimate, "confidence": confidence, "actual_h": None,
        "deadline": parse_date(deadline), "depends_on": depends_on or [],
        "waiting_on": waiting_on, "expected_by": expected, "follow_up_after": follow,
        "scheduled_on": parse_date(scheduled_on),
        "scheduled_window": _coerce("scheduled_window", scheduled_window) if scheduled_window else None,
        "sources": sources or [], "created": today, "updated": today,
    })
    for k in OPTIONAL_FIELDS:
        if meta.get(k) is None:
            meta.pop(k, None)
    path = root / "tasks" / f"{tid}.md"
    write_md(path, meta, body or DEFAULT_BODY)
    return path


def set_fields(root: Path, tid: str, assignments: list[str]) -> dict:
    path = root / "tasks" / f"{tid}.md"
    if not path.exists():
        raise SystemExit(f"{tid} not found")
    meta, body = read_md(path)
    for a in assignments:
        if a.startswith("remaining_h="):  # derive estimate_h so that remaining = estimate_h × correction − actual_h
            corr = float(load_config(root)["capacity"]["estimate_correction"]) or 1.0
            remaining = parse_hours(a.split("=", 1)[1])
            meta["estimate_h"] = round((remaining + float(meta.get("actual_h") or 0)) / corr, 2)
            continue
        if "+=" in a:
            k, v = a.split("+=", 1)
            if k in HOUR_FIELDS:  # cumulative hours, e.g. actual_h+=1h30
                meta[k] = round(float(meta.get(k) or 0) + parse_hours(v), 2)
                continue
            cur = list(meta.get(k) or [])
            cur += [x for x in _coerce(k, v) if x not in cur] if k in LIST_FIELDS else [_coerce(k, v)]
            meta[k] = cur
        else:
            k, v = a.split("=", 1)
            meta[k] = _coerce(k, v, root)
    today = now_fn(load_config(root)).date()
    keys = {a.split("=")[0].rstrip("+") for a in assignments}
    if meta.get("status") == "waiting":
        if not meta.get("waiting_on"):
            raise SystemExit("status waiting requires waiting_on=person:<slug>")
        if "follow_up_after" not in keys and (not meta.get("follow_up_after") or "expected_by" in keys):
            meta["follow_up_after"] = follow_up_date(parse_date(meta.get("expected_by")), today)
    elif "status" in keys:  # leaving waiting: the follow-up date is meaningless
        meta.pop("follow_up_after", None)
    meta["updated"] = today
    _check_estimate_overrun(root, tid, meta, keys)
    meta = _ordered({k: v for k, v in meta.items()})
    for k in OPTIONAL_FIELDS:
        if meta.get(k) is None:
            meta.pop(k, None)
    write_md(path, meta, body)
    return meta


def _check_estimate_overrun(root: Path, tid: str, meta: dict, keys: set) -> None:
    """Mechanical detection: a task closed with actual_h / estimate_h above evolution.estimate_overrun_ratio."""
    if meta.get("status") != "done" or not ({"status", "actual_h"} & keys):
        return
    est, act = meta.get("estimate_h"), meta.get("actual_h")
    if not est or act is None:
        return
    try:
        from signals import emit, evo_config
        ratio = float(act) / float(est)
        threshold = float(evo_config(root).get("estimate_overrun_ratio", 1.5))
        if ratio > threshold:
            emit(root, emitter="script:tasks.py", kind="wrong-output", component=".claude/agents/triage.md",
                 fingerprint="tasks.estimate-overrun", severity="low", origin="deterministic",
                 evidence=f"{tid}", expected=f"réel ≤ {threshold} × estimation",
                 observed=f"{tid} : réel/estimé = {ratio:.2f}", proofs=[f"tasks/{tid}.md (estimate_h, actual_h)"])
    except Exception:
        pass


def due_followups(root: Path) -> dict[str, list[dict]]:
    """Waiting tasks whose follow_up_after <= today, grouped by person slug."""
    today = now_fn(load_config(root)).date()
    out: dict[str, list[dict]] = {}
    for t in load_tasks(root).values():
        f = parse_date(t.meta.get("follow_up_after"))
        if t.status == "waiting" and f and f <= today:
            person = str(t.meta.get("waiting_on") or "person:?").split(":", 1)[1]
            out.setdefault(person, []).append({"id": t.id, "project": t.meta.get("project"), "title": t.meta.get("title"),
                                               "expected_by": str(t.meta.get("expected_by") or ""), "follow_up_after": str(f)})
    return out


def bump_followup(root: Path, tid: str, workdays: int = 3) -> dict:
    today = now_fn(load_config(root)).date()
    return set_fields(root, tid, [f"follow_up_after={add_workdays(today, workdays)}"])


def archive(root: Path, older_than: int, dry_run: bool) -> list[str]:
    today = now_fn(load_config(root)).date()
    moved = []
    for t in load_tasks(root).values():
        upd = parse_date(t.meta.get("updated")) or today
        if t.status in CLOSED_STATUSES and (today - upd).days > older_than:
            moved.append(t.id)
            if not dry_run:
                dest = root / "tasks" / "_archive" / f"{upd:%Y}" / t.path.name
                dest.parent.mkdir(parents=True, exist_ok=True)
                t.path.rename(dest)
    return moved


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root")
    sub = ap.add_subparsers(dest="cmd", required=True)
    n = sub.add_parser("new")
    n.add_argument("--project", required=True); n.add_argument("--title", required=True)
    n.add_argument("--status", default="todo", choices=STATUSES); n.add_argument("--priority", default="P2", choices=PRIORITIES)
    n.add_argument("--executor", default="me"); n.add_argument("--estimate", type=float)
    n.add_argument("--confidence", choices=("low", "medium", "high")); n.add_argument("--deadline")
    n.add_argument("--depends-on"); n.add_argument("--source", action="append")
    n.add_argument("--body"); n.add_argument("--waiting-on"); n.add_argument("--expected-by")
    n.add_argument("--scheduled-on", help="day the owner wants to DO it (≠ deadline)"); n.add_argument("--window", help="HH:MM-HH:MM on that day")
    n.add_argument("--from", dest="ref_date", help="reference date for the follow-up (date of the source message)")
    sub.add_parser("followups").add_argument("--json", action="store_true")
    bf = sub.add_parser("bump-followup"); bf.add_argument("id"); bf.add_argument("--workdays", type=int, default=3)
    s = sub.add_parser("set"); s.add_argument("id"); s.add_argument("assign", nargs="+")
    li = sub.add_parser("list"); li.add_argument("--status"); li.add_argument("--project"); li.add_argument("--executor"); li.add_argument("--json", action="store_true")
    a = sub.add_parser("archive"); a.add_argument("--older-than", type=int, default=30); a.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    root = get_root(args.root)

    if args.cmd == "new":
        deps = [d.strip() for d in args.depends_on.split(",")] if args.depends_on else []
        p = new_task(root, args.project, args.title, status=args.status, priority=args.priority, executor=args.executor,
                     estimate=args.estimate, confidence=args.confidence, deadline=args.deadline,
                     depends_on=deps, sources=args.source,
                     body=args.body.replace("\\n", "\n") if args.body else None,
                     waiting_on=args.waiting_on, expected_by=args.expected_by, ref_date=args.ref_date,
                     scheduled_on=args.scheduled_on, scheduled_window=args.window)
        print(p.relative_to(root))
    elif args.cmd == "set":
        meta = set_fields(root, args.id, args.assign)
        keys = [("estimate_h" if a.startswith("remaining_h=") else a.split("=")[0].rstrip("+")) for a in args.assign]
        print(f"{args.id}: " + ", ".join(f"{k}={meta.get(k)}" for k in keys))
    elif args.cmd == "followups":
        due = due_followups(root)
        if args.json:
            print(json.dumps(due, ensure_ascii=False, indent=1))
        else:
            for person, items in due.items():
                print(f"{person}: " + "; ".join(f"{i['id']} {i['title']} (relance depuis {i['follow_up_after']})" for i in items))
            print("" if due else "aucune relance due")
    elif args.cmd == "bump-followup":
        print(f"{args.id}: follow_up_after={bump_followup(root, args.id, args.workdays)['follow_up_after']}")
    elif args.cmd == "list":
        wanted = set(args.status.split(",")) if args.status else None
        rows = []
        for t in load_tasks(root).values():
            if wanted and t.status not in wanted:
                continue
            if args.project and t.meta.get("project") != args.project:
                continue
            if args.executor and t.meta.get("executor") != args.executor:
                continue
            rows.append({k: (str(v) if isinstance(v, dt.date) else v) for k, v in t.meta.items()})
        if args.json:
            print(json.dumps(rows, ensure_ascii=False, indent=1))
        else:
            for r in rows:
                print(f"{r['id']} · {r.get('project')} · {r.get('status')} · {r.get('priority')} · {r.get('executor')} · {r.get('estimate_h') if r.get('estimate_h') is not None else '?'}h · {r.get('deadline') or '-'} · {r.get('title')}")
    elif args.cmd == "archive":
        moved = archive(root, args.older_than, args.dry_run)
        print(("would move: " if args.dry_run else "moved: ") + (", ".join(moved) or "nothing"))
    return 0


if __name__ == "__main__":
    from common import run_main
    sys.exit(run_main(main, __file__))
