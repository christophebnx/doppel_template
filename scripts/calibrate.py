"""Recompute capacity.estimate_correction from done tasks (actual_h vs estimate_h).

  calibrate.py [--weeks 8] [--min-tasks 5] [--write]

ratio   = sum(actual_h) / sum(estimate_h) over done tasks updated in the last N weeks with both values
new     = 0.5 * old + 0.5 * ratio  (smoothing), clamped to [0.5, 2.0], rounded to 0.05
Nothing changes when fewer than --min-tasks tasks qualify.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

from common import Task, get_root, load_config, load_tasks, now as now_fn, parse_date, read_md, set_config_scalar


def compute(root: Path, weeks: int = 8, min_tasks: int = 5) -> dict:
    cfg = load_config(root)
    old = float(cfg["capacity"]["estimate_correction"])
    since = now_fn(cfg).date() - dt.timedelta(weeks=weeks)
    sample = []
    tasks = list(load_tasks(root).values())
    for p in [*(root / "tasks" / "_archive").glob("**/T-*.md"), *(root / "archive" / "projects").glob("*/tasks/T-*.md")]:
        meta, _ = read_md(p)
        tasks.append(Task(id=meta.get("id", p.stem), path=p, meta=meta))
    for t in tasks:
        m = t.meta
        if t.status != "done" or not m.get("estimate_h") or m.get("actual_h") is None:
            continue
        if (parse_date(m.get("updated")) or dt.date.min) < since:
            continue
        sample.append((float(m["estimate_h"]), float(m["actual_h"])))
    result = {"old": old, "n": len(sample), "new": old, "ratio": None, "changed": False}
    if len(sample) < min_tasks:
        result["reason"] = f"only {len(sample)} qualifying tasks (< {min_tasks})"
        return result
    ratio = sum(a for _, a in sample) / sum(e for e, _ in sample)
    new = min(max(0.5 * old + 0.5 * ratio, 0.5), 2.0)
    new = round(round(new / 0.05) * 0.05, 2)
    result.update(ratio=round(ratio, 3), new=new, changed=new != old)
    return result


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root"); ap.add_argument("--weeks", type=int, default=8); ap.add_argument("--min-tasks", type=int, default=5)
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args(argv)
    root = get_root(args.root)
    r = compute(root, args.weeks, args.min_tasks)
    if args.write and r["changed"]:
        set_config_scalar(root, "estimate_correction", r["new"])
        r["written"] = True
    print(json.dumps(r))
    return 0


if __name__ == "__main__":
    from common import run_main
    sys.exit(run_main(main, __file__))
