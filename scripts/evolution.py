"""Evolution briefs (evolution/briefs/E-nnn.md), guards, observation, kill switch.  PROTECTED.

  evolution.py guard --for evolve|improve [--json]
      STOP file, review/autonomy off, weekly cap, startup guard (execute / auto-merge need ≥ evals_min_scenarios
      scenarios and a reference eval report on a commit of main). Prints effective autonomy/merge.
  evolution.py new-brief --title "…" --component C --signals S-0001,S-0002 --files a,b [--score 12.5]
                         [--logic] [--format-change] [--migration]          → E-nnn (risk class computed)
  evolution.py risk --files a,b [--logic] [--format-change] [--migration]    → low | medium | high + reasons
  evolution.py status E-001 approved|running|pr-open|merged|observing|validated|reverted|failed|rejected
                      [--reason "…"] [--pr URL] [--branch evolve/E-001]
  evolution.py observe E-001 [--json]     before/after signal rate of the component → improved | stable | degraded
  evolution.py stop [--reason "…"] | resume
  evolution.py changelog --brief E-001 --text "…"
  evolution.py list [--status approved] [--json]
  evolution.py index
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import get_root, load_config, now as now_fn, read_md, week_bounds, week_of, write_md  # noqa: E402

STATUSES = ("proposed", "approved", "running", "pr-open", "merged", "observing", "validated", "reverted", "failed",
            "rejected")
TRANSITIONS = {
    "proposed": {"approved", "rejected"},
    "approved": {"running", "rejected"},
    "running": {"pr-open", "merged", "failed"},
    "pr-open": {"merged", "rejected", "failed"},
    "merged": {"observing", "reverted"},
    "observing": {"validated", "reverted"},
    "failed": {"approved", "rejected"},
    "validated": set(), "reverted": set(), "rejected": set(),
}
RISK_ORDER = ("low", "medium", "high")
FIELD_ORDER = ["id", "title", "component", "created", "status", "risk", "risk_reasons", "score", "signals", "files",
               "scenario", "branch", "pr", "history"]
CORE_FILES = ("scripts/common.py", "scripts/index.py", "scripts/tasks.py")  # shared data formats


def bdir(root: Path) -> Path:
    return root / "evolution" / "briefs"


def stop_path(root: Path) -> Path:
    return root / "evolution" / "STOP"


def _now(root: Path) -> dt.datetime:
    return now_fn(load_config(root))


def load_briefs(root: Path) -> dict[str, tuple[dict, str, Path]]:
    out = {}
    for p in sorted(bdir(root).glob("E-*.md")):
        meta, body = read_md(p)
        out[meta.get("id", p.stem)] = (meta, body, p)
    return out


def next_brief_id(root: Path) -> str:
    nums = [int(m.group(1)) for p in bdir(root).glob("E-*.md") if (m := re.match(r"E-(\d+)", p.stem))]
    return f"E-{max(nums, default=0) + 1:03d}"


def _history_time(entry: str) -> dt.datetime | None:
    m = re.match(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2})", str(entry))
    return dt.datetime.fromisoformat(m.group(1)) if m else None


def status_time(meta: dict, status: str) -> dt.datetime | None:
    """Last time the brief entered `status` (from its history)."""
    for h in reversed(meta.get("history") or []):
        if f" {status}" in str(h).split(" — ")[0]:
            return _history_time(h)
    return None


# --------------------------------------------------------------------------- risk


def protected_hits(files: list[str], root: Path | None = None) -> list[str]:
    """Files of the change that fall under evolution/protected.txt (additions to `**#existing` dirs excluded)."""
    path = (root or Path(__file__).resolve().parent.parent) / "evolution" / "protected.txt"
    rules = [l.strip() for l in path.read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")] if path.exists() else []
    hits = []
    for f in files:
        for r in rules:
            target, _, mode = r.partition("#")
            if mode == "existing":
                continue
            if f == target or (target.endswith("/") and f.startswith(target)):
                hits.append(f)
    return hits


def risk(files: list[str], logic: bool = False, format_change: bool = False, migration: bool = False) -> tuple[str, list[str]]:
    """Explicit criteria:
    high   : a protected path (evolution/protected.txt), data format change / migration flag, a shared data-format
             script (common/index/tasks), or files in ≥ 3 component families
    medium : any Python script, any non-eval test, or a logic change flag (skill/agent behaviour, not wording)
    low    : only wording in skills / agents / templates (.md), plus the regression scenario"""
    reasons = []
    families = set()
    for f in files:
        if f.startswith("tests/evals/scenarios/"):
            continue
        fam = f.split("/")[0] if not f.startswith(".claude/") else "/".join(f.split("/")[:2])
        families.add(fam)
    level = "low"
    if hits := protected_hits(files):
        reasons.append("noyau protégé (" + ", ".join(hits) + ") : PR supervisée obligatoire")
    if format_change:
        reasons.append("changement de format de données")
    if migration:
        reasons.append("migration de données")
    if any(f in CORE_FILES for f in files):
        reasons.append("script de format partagé (" + ", ".join(f for f in files if f in CORE_FILES) + ")")
    if len(families) >= 3:
        reasons.append(f"{len(families)} familles de composants ({', '.join(sorted(families))})")
    if reasons:
        return "high", reasons
    if any(f.endswith(".py") and not f.startswith("tests/evals/scenarios/") for f in files):
        reasons.append("script Python modifié")
        level = "medium"
    if any(f.startswith("tests/") and not f.startswith("tests/evals/scenarios/") for f in files):
        reasons.append("tests hors scénarios d'éval")
        level = "medium"
    if logic:
        reasons.append("logique d'un skill/agent (pas seulement la formulation)")
        level = "medium"
    if level == "low":
        reasons.append("formulation de skill/agent/template uniquement")
    return level, reasons


# --------------------------------------------------------------------------- guards


def component_in_cooldown(root: Path, component: str) -> str | None:
    from signals import evo_config
    days = int(evo_config(root)["guards"]["cooldown_days"])
    now = _now(root)
    for bid, (m, _, _) in load_briefs(root).items():
        if m.get("component") != component and component not in (m.get("files") or []):
            continue
        t = status_time(m, "merged")
        if t and now - t < dt.timedelta(days=days) and m.get("status") not in ("reverted",):
            return str((t + dt.timedelta(days=days)).date())
    return None


def merged_this_week(root: Path) -> list[str]:
    now = _now(root)
    start, end = week_bounds(week_of(now))
    out = []
    for bid, (m, _, _) in load_briefs(root).items():
        t = status_time(m, "merged") or status_time(m, "pr-open")
        if t and start <= t < end:
            out.append(bid)
    return out


def reference_report(root: Path) -> str | None:
    """Most recent eval report whose commit is on main (ancestor of main / origin/main)."""
    reports = sorted((root / "evolution" / "evals").glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for p in reports:
        try:
            commit = json.loads(p.read_text(encoding="utf-8")).get("commit")
        except Exception:
            continue
        for ref in ("main", "origin/main"):
            r = subprocess.run(["git", "-C", str(root), "merge-base", "--is-ancestor", str(commit), ref], capture_output=True)
            if r.returncode == 0:
                return str(p.relative_to(root))
    return None


def guard(root: Path, for_: str) -> dict:
    from evals import count_scenarios
    from signals import evo_config
    cfg = evo_config(root)
    g = cfg["guards"]
    reasons, notes = [], []
    autonomy, merge = cfg["autonomy"], cfg["merge"]
    if stop_path(root).exists():
        reasons.append(f"evolution/STOP présent : chaîne d'évolution suspendue ({stop_path(root).read_text(encoding='utf-8').strip()[:120]})")
    if for_ == "evolve" and cfg["review"] == "off":
        reasons.append("evolution.review = off")
    if for_ == "improve" and autonomy == "off":
        reasons.append("evolution.autonomy = off")
    if for_ == "improve":
        done = merged_this_week(root)
        if len(done) >= int(g["max_briefs_per_week"]):
            reasons.append(f"plafond atteint : {len(done)} brief(s) cette semaine ({', '.join(done)}) ≥ max_briefs_per_week {g['max_briefs_per_week']}")
    n_scen = count_scenarios(root)
    ref = reference_report(root)
    if autonomy == "execute" or merge == "auto":
        missing = []
        if n_scen < int(g["evals_min_scenarios"]):
            missing.append(f"{n_scen} scénario(s) d'éval < evals_min_scenarios {g['evals_min_scenarios']}")
        if not ref:
            missing.append("aucun run d'éval de référence sur main (scripts/evals.py run sur main)")
        if missing:
            notes.append("garde de démarrage : " + " ; ".join(missing) + " → autonomy ramenée à propose, merge à pr")
            autonomy = "propose" if autonomy == "execute" else autonomy
            merge = "pr"
    return {"ok": not reasons, "reasons": reasons, "notes": notes, "autonomy": autonomy, "merge": merge,
            "auto_merge_max_risk": cfg["auto_merge_max_risk"], "scenarios": n_scen, "reference": ref,
            "configured": {"autonomy": cfg["autonomy"], "merge": cfg["merge"]}}


# --------------------------------------------------------------------------- briefs


def _ordered(meta: dict) -> dict:
    out = {k: meta.get(k) for k in FIELD_ORDER}
    out.update({k: v for k, v in meta.items() if k not in out})
    return out


def new_brief(root: Path, title: str, component: str, signals: list[str], files: list[str], score=None,
              logic=False, format_change=False, migration=False) -> dict:
    from signals import set_fields as set_signal
    bid = next_brief_id(root)
    level, reasons = risk(files, logic, format_change, migration)
    now = _now(root)
    meta = _ordered({"id": bid, "title": title, "component": component, "created": now.date(), "status": "proposed",
                     "risk": level, "risk_reasons": reasons, "score": score, "signals": signals, "files": files,
                     "scenario": None, "branch": None, "pr": None,
                     "history": [f"{now:%Y-%m-%d %H:%M} proposed — créé par /evolve"]})
    tpl = (root / "templates" / "evolution-brief.md").read_text(encoding="utf-8")
    body = tpl.split("---", 2)[2].lstrip("\n")
    body = re.sub(r"<!--.*?-->\n*", "", body, count=1, flags=re.S)
    body = body.replace("E-000", bid).replace("<titre>", title)
    write_md(bdir(root) / f"{bid}.md", meta, body)
    for s in signals:
        set_signal(root, s, ["status=grouped", f"brief={bid}"])
    write_index(root)
    return {"id": bid, "risk": level, "risk_reasons": reasons, "file": f"evolution/briefs/{bid}.md"}


def set_status(root: Path, bid: str, status: str, reason: str = "", pr: str | None = None, branch: str | None = None) -> dict:
    from signals import load_signals, set_fields as set_signal
    briefs = load_briefs(root)
    if bid not in briefs:
        raise SystemExit(f"{bid} not found")
    meta, body, path = briefs[bid]
    cur = meta.get("status", "proposed")
    if status not in STATUSES or status not in TRANSITIONS.get(cur, set()):
        raise SystemExit(f"transition {cur} → {status} refusée")
    now = _now(root)
    meta["status"] = status
    meta["history"] = list(meta.get("history") or []) + [f"{now:%Y-%m-%d %H:%M} {status}" + (f" — {reason}" if reason else "")]
    if pr:
        meta["pr"] = pr
    if branch:
        meta["branch"] = branch
    write_md(path, _ordered(meta), body)
    sigs = load_signals(root)
    for s in meta.get("signals") or []:
        if s not in sigs:
            continue
        if status == "validated":
            set_signal(root, s, ["status=addressed"])
        elif status in ("reverted", "rejected"):
            set_signal(root, s, ["status=open", "brief="])  # reopened: the problem is back on the table
    write_index(root)
    return {"id": bid, "from": cur, "to": status}


def observe(root: Path, bid: str) -> dict:
    from signals import evo_config, load_signals, stats
    meta = load_briefs(root)[bid][0]
    days = int(evo_config(root)["guards"]["observe_days"])
    since = status_time(meta, "merged") or status_time(meta, "observing")
    if not since:
        raise SystemExit(f"{bid} was never merged")
    now = _now(root)
    end_after = since + dt.timedelta(days=days)
    sigs = load_signals(root)
    fps = {sigs[s][0].get("fingerprint") for s in meta.get("signals") or [] if s in sigs}
    comp = meta.get("component")
    before = stats(root, since - dt.timedelta(days=days), since, comp, fps, any_of=True)
    after = stats(root, since, min(now, end_after) + dt.timedelta(minutes=1), comp, fps, any_of=True)
    recur = stats(root, since, now + dt.timedelta(minutes=1), None, fps)["signals"]
    ready = now >= end_after
    br, ar = before["rate"] or 0, after["rate"] or 0
    if recur > 0:
        verdict, why = "degraded", f"le problème corrigé est réapparu ({recur} occurrence(s) des mêmes fingerprints)"
    elif after["signals"] > before["signals"] and ar > br * 1.2:
        verdict, why = "degraded", f"taux du composant {br} → {ar}"
    elif ar < br * 0.8 or (before["signals"] and not after["signals"]):
        verdict, why = "improved", f"taux du composant {br} → {ar}"
    else:
        verdict, why = "stable", f"taux du composant {br} → {ar}"
    return {"id": bid, "component": comp, "observing_since": str(since), "observe_days": days, "ready": ready,
            "before": {"signals": before["signals"], "runs": before["runs"], "rate": before["rate"]},
            "after": {"signals": after["signals"], "runs": after["runs"], "rate": after["rate"]},
            "recurrences": recur, "verdict": verdict, "why": why,
            "action": ("revert" if verdict == "degraded" else "validate" if ready else "wait")}


def changelog(root: Path, bid: str, text: str) -> str:
    meta = load_briefs(root)[bid][0]
    now = _now(root)
    line = (f"- {now:%Y-%m-%d} · {bid} · {meta.get('component')} · {text} · signaux {', '.join(meta.get('signals') or [])}"
            f" · {meta.get('status')}" + (f" · {meta['pr']}" if meta.get("pr") else ""))
    p = root / "evolution" / "changelog.md"
    s = p.read_text(encoding="utf-8") if p.exists() else "# Changelog de doppel (auto-évolution)\n\n<!-- newest first -->\n"
    head, sep, rest = s.partition("-->\n")
    p.write_text(head + sep + line + "\n" + rest.lstrip("\n") if sep else s + line + "\n", encoding="utf-8")
    return line


def write_index(root: Path) -> None:
    lines = []
    for bid, (m, _, _) in sorted(load_briefs(root).items()):
        lines.append(" · ".join(str(x) for x in (bid, m.get("status"), m.get("risk"), m.get("score"), m.get("component"),
                                                  ",".join(m.get("signals") or []), m.get("title"))))
    bdir(root).mkdir(parents=True, exist_ok=True)
    (bdir(root) / "_index.md").write_text(
        "# Briefs d'évolution\n<!-- generated by scripts/evolution.py — do not edit by hand -->\n"
        "`id · statut · risque · score · composant · signaux · titre`\n\n" + ("\n".join(lines) or "_(vide)_") + "\n",
        encoding="utf-8")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root")
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("guard"); g.add_argument("--for", dest="for_", choices=["evolve", "improve"], required=True); g.add_argument("--json", action="store_true")
    for name in ("new-brief", "risk"):
        p = sub.add_parser(name)
        if name == "new-brief":
            p.add_argument("--title", required=True); p.add_argument("--component", required=True)
            p.add_argument("--signals", required=True); p.add_argument("--score", type=float)
        p.add_argument("--files", required=True)
        p.add_argument("--logic", action="store_true"); p.add_argument("--format-change", action="store_true"); p.add_argument("--migration", action="store_true")
    st = sub.add_parser("status"); st.add_argument("id"); st.add_argument("status"); st.add_argument("--reason", default="")
    st.add_argument("--pr"); st.add_argument("--branch")
    ob = sub.add_parser("observe"); ob.add_argument("id"); ob.add_argument("--json", action="store_true")
    sp = sub.add_parser("stop"); sp.add_argument("--reason", default="arrêt manuel")
    sub.add_parser("resume")
    cl = sub.add_parser("changelog"); cl.add_argument("--brief", required=True); cl.add_argument("--text", required=True)
    li = sub.add_parser("list"); li.add_argument("--status"); li.add_argument("--json", action="store_true")
    sub.add_parser("index")
    args = ap.parse_args(argv)
    root = get_root(args.root)
    split = lambda s: [x.strip() for x in s.split(",") if x.strip()]  # noqa: E731

    if args.cmd == "guard":
        res = guard(root, args.for_)
        if args.json:
            print(json.dumps(res, ensure_ascii=False, indent=1))
        else:
            print(("OK" if res["ok"] else "ARRÊT") + f" · autonomy {res['autonomy']} · merge {res['merge']} · {res['scenarios']} scénarios · référence {res['reference'] or 'aucune'}")
            for r in res["reasons"] + res["notes"]:
                print(f"- {r}")
        return 0 if res["ok"] else 2
    if args.cmd == "new-brief":
        print(json.dumps(new_brief(root, args.title, args.component, split(args.signals), split(args.files), args.score,
                                   args.logic, args.format_change, args.migration), ensure_ascii=False))
    elif args.cmd == "risk":
        level, reasons = risk(split(args.files), args.logic, args.format_change, args.migration)
        print(json.dumps({"risk": level, "reasons": reasons}, ensure_ascii=False))
    elif args.cmd == "status":
        print(json.dumps(set_status(root, args.id, args.status, args.reason, args.pr, args.branch), ensure_ascii=False))
    elif args.cmd == "observe":
        res = observe(root, args.id)
        print(json.dumps(res, ensure_ascii=False, indent=1) if args.json else f"{res['id']} · {res['verdict']} ({res['why']}) → {res['action']}")
    elif args.cmd == "stop":
        stop_path(root).write_text(f"{_now(root):%Y-%m-%d %H:%M} · {args.reason}\n", encoding="utf-8")
        print("evolution/STOP créé : chaîne d'évolution suspendue")
    elif args.cmd == "resume":
        if stop_path(root).exists():
            stop_path(root).unlink()
        print("evolution/STOP supprimé : chaîne d'évolution réactivée")
    elif args.cmd == "changelog":
        print(changelog(root, args.brief, args.text))
    elif args.cmd == "list":
        rows = [{**{k: (str(v) if isinstance(v, (dt.date, dt.datetime)) else v) for k, v in m.items()}}
                for _, (m, _, _) in sorted(load_briefs(root).items()) if not args.status or m.get("status") == args.status]
        rows.sort(key=lambda m: -(m.get("score") or 0))
        print(json.dumps(rows, ensure_ascii=False, indent=1) if args.json else "\n".join(f"{m['id']} · {m['status']} · {m['risk']} · {m.get('score')} · {m['title']}" for m in rows) or "aucun brief")
    elif args.cmd == "index":
        write_index(root)
        print("evolution/briefs/_index.md written")
    return 0


if __name__ == "__main__":
    from common import run_main
    sys.exit(run_main(main, __file__))
