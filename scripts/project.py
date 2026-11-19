"""Projects: create the folder skeleton + config entry, update config fields.

  project.py add demo-project --name "Projet de démonstration"
  project.py set demo-project active=false
  project.py list
  project.py close demo-mini [--dry-run] [--force] [--json]
      stats (tasks by status, estimated vs actual hours), then moves projects/<slug>/ and the
      project's tasks to archive/projects/<slug>/, sets active=false + archived=<date>. Refuses while tasks are open
      (unless --force).
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

import yaml

from common import OPEN_STATUSES, get_root, load_config, load_tasks, now as now_fn, write_config_projects


def add(root: Path, slug: str, name: str) -> Path:
    cfg = load_config(root)
    projects = cfg["projects"]
    if slug in projects:
        raise SystemExit(f"project {slug} already exists")
    projects[slug] = {"name": name, "active": True}
    write_config_projects(root, projects)
    pdir = root / "projects" / slug
    for sub in ("status",):
        (pdir / sub).mkdir(parents=True, exist_ok=True)
        (pdir / sub / ".gitkeep").touch()
    brain = pdir / "brain.md"
    if not brain.exists():
        tpl = (root / "templates" / "brain.md").read_text(encoding="utf-8")
        today = now_fn(cfg).date()
        brain.write_text(tpl.replace("{project}", slug).replace("{name}", name)
                         .replace("{date}", str(today)), encoding="utf-8")
    return pdir


def set_fields(root: Path, slug: str, assignments: list[str]) -> dict:
    cfg = load_config(root)
    if slug not in cfg["projects"]:
        raise SystemExit(f"unknown project {slug}")
    for a in assignments:
        k, v = a.split("=", 1)
        cfg["projects"][slug][k] = yaml.safe_load(v) if v else None
    write_config_projects(root, cfg["projects"])
    return cfg["projects"][slug]


def close_stats(root: Path, slug: str) -> dict:
    cfg = load_config(root)
    corr = float(cfg["capacity"]["estimate_correction"])
    tasks = [t for t in load_tasks(root).values() if t.meta.get("project") == slug]
    by_status: dict[str, int] = {}
    for t in tasks:
        by_status[t.status] = by_status.get(t.status, 0) + 1
    pairs = [(float(t.meta["estimate_h"]), float(t.meta["actual_h"])) for t in tasks
             if t.status == "done" and t.meta.get("estimate_h") and t.meta.get("actual_h") is not None]
    est, act = round(sum(e for e, _ in pairs), 2), round(sum(a for _, a in pairs), 2)
    over = sorted(((t.id, float(t.meta["actual_h"]) - float(t.meta["estimate_h"])) for t in tasks
                   if t.status == "done" and t.meta.get("estimate_h") and t.meta.get("actual_h") is not None),
                  key=lambda x: -abs(x[1]))[:5]
    pdir = root / "projects" / slug
    return {
        "project": slug,
        "tasks": len(tasks),
        "by_status": by_status,
        "open_tasks": [t.id for t in tasks if t.status in OPEN_STATUSES],
        "done_with_actual": len(pairs),
        "estimated_h": est,
        "actual_h": act,
        "ratio_actual_over_estimate": round(act / est, 2) if est else None,
        "estimated_with_correction_h": round(est * corr, 2),
        "biggest_gaps_h": [{"task": tid, "actual_minus_estimate_h": round(d, 2)} for tid, d in over],
        "status_reports": sorted(p.name for p in (pdir / "status").glob("*.md")),
        "dates": {"first_created": str(min((t.meta.get("created") for t in tasks if t.meta.get("created")), default="")),
                  "last_updated": str(max((t.meta.get("updated") for t in tasks if t.meta.get("updated")), default=""))},
    }


def close(root: Path, slug: str, force: bool = False, dry_run: bool = False) -> dict:
    cfg = load_config(root)
    if slug not in cfg["projects"]:
        raise SystemExit(f"unknown project {slug}")
    stats = close_stats(root, slug)
    if dry_run:
        return stats
    if stats["open_tasks"] and not force:
        raise SystemExit(f"open tasks: {', '.join(stats['open_tasks'])} — close, drop or move them first (or --force)")
    dest = root / "archive" / "projects" / slug
    if dest.exists():
        raise SystemExit(f"{dest.relative_to(root)} already exists")
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(root / "projects" / slug), str(dest))
    (dest / "tasks").mkdir(exist_ok=True)
    for t in load_tasks(root).values():
        if t.meta.get("project") == slug:
            shutil.move(str(t.path), str(dest / "tasks" / t.path.name))
    today = now_fn(cfg).date()
    cfg["projects"][slug].update(active=False, archived=today)
    write_config_projects(root, cfg["projects"])
    stats["archived_to"] = str(dest.relative_to(root))
    return stats


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add"); a.add_argument("slug"); a.add_argument("--name", required=True)
    s = sub.add_parser("set"); s.add_argument("slug"); s.add_argument("assign", nargs="+")
    sub.add_parser("list")
    c = sub.add_parser("close"); c.add_argument("slug"); c.add_argument("--dry-run", action="store_true")
    c.add_argument("--force", action="store_true"); c.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    root = get_root(args.root)
    if args.cmd == "add":
        print(add(root, args.slug, args.name).relative_to(root))
    elif args.cmd == "set":
        print(set_fields(root, args.slug, args.assign))
    elif args.cmd == "close":
        print(json.dumps(close(root, args.slug, args.force, args.dry_run), ensure_ascii=False, indent=1))
    else:
        for slug, p in load_config(root)["projects"].items():
            print(f"{slug} · {p.get('name')} · active={p.get('active')}")
    return 0


if __name__ == "__main__":
    from common import run_main
    sys.exit(run_main(main, __file__))
