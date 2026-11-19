"""Date arithmetic for agents (never compute dates "by heart").

  dates.py now [--json]                  current date/time, ISO week, weekday, plan_week, next working day
  dates.py week 2026-W47                 the 7 dates of a week
  dates.py resolve mardi [--week W | --from D] [--next]   date of a weekday (in week W, or next occurrence from D/today)
  dates.py shift --days 3 [--from 2026-11-17] [--workdays]
  dates.py month [--offset -1]           first and last date of the current (or offset) month ("le mois passé" = -1)
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys

from common import DAY_FR, day_index, get_root, load_config, now as now_fn, parse_date, shift_week, week_days, week_monday, week_of


def add_workdays(d: dt.date, n: int) -> dt.date:
    step = 1 if n >= 0 else -1
    while n:
        d += dt.timedelta(days=step)
        if d.weekday() < 5:
            n -= step
    return d


def month_range(d: dt.date, offset: int = 0) -> tuple[dt.date, dt.date]:
    m = d.year * 12 + (d.month - 1) + offset
    first = dt.date(m // 12, m % 12 + 1, 1)
    nxt = dt.date((m + 1) // 12, (m + 1) % 12 + 1, 1)
    return first, nxt - dt.timedelta(days=1)


def info(now: dt.datetime) -> dict:
    today = now.date()
    week = week_of(today)
    return {
        "now": now.strftime("%Y-%m-%d %H:%M"),
        "date": str(today),
        "weekday": DAY_FR[today.weekday()],
        "week": week,
        "plan_week": week if today.weekday() < 5 else shift_week(week, 1),  # weekend -> next week
        "next_week": shift_week(week, 1),
        "next_workday": str(add_workdays(today, 1)),
        "prev_workday": str(add_workdays(today, -1)),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root")
    sub = ap.add_subparsers(dest="cmd", required=True)
    n = sub.add_parser("now"); n.add_argument("--json", action="store_true")
    w = sub.add_parser("week"); w.add_argument("week")
    r = sub.add_parser("resolve"); r.add_argument("day"); r.add_argument("--week"); r.add_argument("--next", action="store_true"); r.add_argument("--from", dest="start")
    s = sub.add_parser("shift"); s.add_argument("--days", type=int, required=True); s.add_argument("--from", dest="start"); s.add_argument("--workdays", action="store_true")
    mo = sub.add_parser("month"); mo.add_argument("--offset", type=int, default=0)
    args = ap.parse_args(argv)
    cfg = load_config(get_root(args.root))
    now = now_fn(cfg)

    if args.cmd == "now":
        d = info(now)
        print(json.dumps(d, ensure_ascii=False) if args.json else "\n".join(f"{k}: {v}" for k, v in d.items()))
    elif args.cmd == "week":
        for d in week_days(args.week):
            print(f"{DAY_FR[d.weekday()]} {d}")
    elif args.cmd == "resolve":
        idx = day_index(args.day)
        if args.week:
            d = week_monday(args.week) + dt.timedelta(days=idx)
        else:
            today = parse_date(args.start) if args.start else now.date()
            delta = (idx - today.weekday()) % 7
            if args.next and delta == 0:
                delta = 7
            d = today + dt.timedelta(days=delta)
        print(f"{d} ({DAY_FR[d.weekday()]}, {week_of(d)})")
    elif args.cmd == "month":
        first, last = month_range(now.date(), args.offset)
        print(f"{first} {last}")
    elif args.cmd == "shift":
        start = parse_date(args.start) if args.start else now.date()
        d = add_workdays(start, args.days) if args.workdays else start + dt.timedelta(days=args.days)
        print(f"{d} ({DAY_FR[d.weekday()]}, {week_of(d)})")
    return 0


if __name__ == "__main__":
    from common import run_main
    sys.exit(run_main(main, __file__))
