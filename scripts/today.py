"""Facts for the daily sheet `today.md` (skill /today). Deterministic; the reporter only adds the "Focus" lines.

  today.py [--json]        print the facts
  today.py --write         (re)write today.md at the repo root, keeping an existing "## Focus" section of today
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

from common import DAY_FR, OPEN_STATUSES, get_root, load_config, load_tasks, now as now_fn, parse_date, read_md, week_of
from tasks import due_followups

DRAFT_FOLDERS = ("outbox",)  # folders whose `state: draft` files wait for the owner's validation

FOCUS_PLACEHOLDER = "<!-- reporter: 1–3 lignes, les priorités du jour -->"


def _questions(root: Path) -> list[str]:
    p = root / "questions.md"
    if not p.exists():
        return []
    out = []
    for block in re.split(r"^### ", p.read_text(encoding="utf-8"), flags=re.M)[1:]:
        head, _, rest = block.partition("\n")
        # the whole question (it may span several lines until its "- source:" / "- R:" lines), never truncated
        question = " ".join(l.strip() for l in rest.splitlines()
                            if l.strip() and not l.startswith("- ") and not l.strip().startswith("<!--"))
        out.append(f"{head.split(' · ')[0]} · {question}")
    return out


def scheduled_facts(tasks: dict, today: dt.date) -> dict:
    """Tasks with a fixed day (scheduled_on): today's, and missed ones (day passed, still open)."""
    out = {"today": [], "missed": []}
    for t in tasks.values():
        d = parse_date(t.meta.get("scheduled_on"))
        if not d or t.status not in OPEN_STATUSES:
            continue
        item = {"task": t.id, "title": t.meta.get("title"), "window": t.meta.get("scheduled_window"), "date": str(d)}
        if d == today:
            out["today"].append(item)
        elif d < today:
            out["missed"].append(item)
    return out


def evolution_facts(root: Path, now: dt.datetime) -> dict:
    """Self-improvement news: briefs to approve, PRs to arbitrate, changes merged / reverted since yesterday."""
    from evolution import load_briefs, status_time, stop_path
    since = dt.datetime.combine(now.date() - dt.timedelta(days=1), dt.time())
    out = {"stop": stop_path(root).exists(), "to_approve": [], "pr_open": [], "merged": [], "reverted": []}
    for bid, (m, _, _) in sorted(load_briefs(root).items()):
        item = {"id": bid, "title": m.get("title"), "component": m.get("component"), "risk": m.get("risk"), "pr": m.get("pr")}
        st = m.get("status")
        if st == "proposed":
            out["to_approve"].append(item)
        elif st == "pr-open":
            out["pr_open"].append(item)
        for key, status in (("merged", "merged"), ("reverted", "reverted")):
            t = status_time(m, status)
            if t and t >= since:
                out[key].append(item)
    return out


def task_facts(tasks: dict, today: dt.date, horizon_days: int = 7) -> dict:
    """Open tasks that matter today: in progress, P1, due soon or overdue (dates computed here, never by the LLM)."""
    out = {"doing": [], "p1": [], "overdue": [], "due_soon": []}
    limit = today + dt.timedelta(days=horizon_days)
    for t in sorted(tasks.values(), key=lambda t: t.id):
        if t.status not in OPEN_STATUSES:
            continue
        m = t.meta
        item = {"task": t.id, "title": m.get("title"), "project": m.get("project"), "status": t.status,
                "priority": m.get("priority"), "deadline": str(m["deadline"]) if m.get("deadline") else None}
        dl = parse_date(m.get("deadline"))
        if t.status == "doing":
            out["doing"].append(item)
        if m.get("priority") == "P1" and t.status != "waiting":
            out["p1"].append(item)
        if dl and dl < today:
            out["overdue"].append(item)
        elif dl and dl <= limit:
            out["due_soon"].append(item)
    out["due_soon"].sort(key=lambda x: x["deadline"])
    return out


def facts(root: Path) -> dict:
    cfg = load_config(root)
    now = now_fn(cfg)
    today = now.date()
    tasks = load_tasks(root)
    to_validate = []
    for folder in DRAFT_FOLDERS:
        for p in sorted((root / folder).glob("*.md")):
            if p.name.startswith("_"):
                continue
            meta, _ = read_md(p)
            if (meta.get("state") or "draft") == "draft":
                to_validate.append(str(p.relative_to(root)))
    return {
        "date": str(today), "weekday": DAY_FR[today.weekday()], "week": week_of(today), "now": now.strftime("%H:%M"),
        "tasks": task_facts(tasks, today),
        "scheduled": scheduled_facts(tasks, today),
        "follow_ups": due_followups(root),
        "questions": _questions(root),
        "to_validate": to_validate,
        "evolution": evolution_facts(root, now),
    }


def _task_line(x: dict) -> str:
    extra = " · ".join(v for v in (x.get("project"), x.get("priority"), x.get("status"),
                                   f"échéance {x['deadline']}" if x.get("deadline") else None) if v)
    return f"- {x['task']} {x['title']}" + (f" — {extra}" if extra else "")


def render(f: dict, focus: str | None = None) -> str:
    t = f["tasks"]
    L = [f"# Aujourd'hui — {f['weekday']} {f['date']} ({f['week']})",
         f"<!-- generated by scripts/today.py at {f['now']} (+ focus by reporter) — overwritten every day -->", "",
         "## Focus", focus or FOCUS_PLACEHOLDER, "", "## En cours"]
    L += [_task_line(x) for x in t["doing"]] or ["- rien"]
    sc = f.get("scheduled") or {}
    if sc.get("today") or sc.get("missed"):
        L += ["", "## Prévu ce jour (jour fixé)"]
        L += [f"- {x['task']} {x['title']}" + (f" ({x['window']})" if x.get("window") else "") for x in sc.get("today", [])]
        L += [f"- ⚠ prévue le {x['date']}, non faite : {x['task']} {x['title']}" for x in sc.get("missed", [])]
    L += ["", "## Échéances"]
    L += [f"- ⚠ en retard : {_task_line(x)[2:]}" for x in t["overdue"]]
    L += [_task_line(x) for x in t["due_soon"]]
    if not t["overdue"] and not t["due_soon"]:
        L.append("- aucune dans les 7 jours")
    L += ["", "## P1 ouvertes"]
    L += [_task_line(x) for x in t["p1"]] or ["- aucune"]
    L += ["", "## Relances dues"]
    L += [f"- {person} : " + "; ".join(f"{i['id']} {i['title']} (depuis {i['follow_up_after']})" for i in items)
          for person, items in f["follow_ups"].items()] or ["- aucune"]
    L += ["", f"## Questions en attente ({len(f['questions'])})"]
    L += [f"- {q}" for q in f["questions"]] or ["- aucune"]
    L += ["", f"## À valider ({len(f['to_validate'])})"]
    L += [f"- {p}" for p in f["to_validate"]] or ["- rien"]
    ev = f.get("evolution") or {}
    if any(ev.get(k) for k in ("stop", "to_approve", "pr_open", "merged", "reverted")):
        L += ["", "## doppel lui-même"]
        if ev.get("stop"):
            L.append("- ⏸ évolution suspendue (evolution/STOP) — `/evolve resume` pour reprendre")
        L += [f"- doppel s'est modifié : {x['id']} — {x['component']} ({x['title']})" for x in ev.get("merged", [])]
        L += [f"- ↩ revert : {x['id']} — {x['component']} ({x['title']})" for x in ev.get("reverted", [])]
        L += [f"- à approuver : {x['id']} [{x['risk']}] {x['title']} → `/evolve approve {x['id']}`" for x in ev.get("to_approve", [])]
        L += [f"- PR à arbitrer : {x['id']} {x['title']} {x.get('pr') or ''}".rstrip() for x in ev.get("pr_open", [])]
    return "\n".join(L) + "\n"


def existing_focus(root: Path, date: str) -> str | None:
    p = root / "today.md"
    if not p.exists():
        return None
    text = p.read_text(encoding="utf-8")
    if date not in text.splitlines()[0]:
        return None
    m = re.search(r"^## Focus\n(.*?)\n\n## ", text, re.S | re.M)
    focus = m.group(1).strip() if m else None
    return None if not focus or focus == FOCUS_PLACEHOLDER else focus


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root"); ap.add_argument("--json", action="store_true"); ap.add_argument("--write", action="store_true")
    args = ap.parse_args(argv)
    root = get_root(args.root)
    f = facts(root)
    if args.write:
        (root / "today.md").write_text(render(f, existing_focus(root, f["date"])), encoding="utf-8")
        print("today.md written")
    elif args.json:
        print(json.dumps(f, ensure_ascii=False, indent=1))
    else:
        print(render(f))
    return 0


if __name__ == "__main__":
    from common import run_main
    sys.exit(run_main(main, __file__))
