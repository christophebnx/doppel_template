"""Evolution signals (evolution/signals/S-nnnn.md) and skill runs (evolution/runs/AAAA-Wnn.jsonl).  PROTECTED.

  signals.py run start --skill ingest [--args "…"]               → prints R-AAAA-MM-JJ-HHMM[-n]
  signals.py run end --run R-… --outcome ok|error|partial [--signals S-0001,S-0002]
  signals.py emit --emitter skill:/ingest --kind bug --component scripts/tasks.py --fingerprint ingest.duplicate-task
                 --severity medium --origin deterministic [--run R-…] [--commit abc1234] [--evidence "R-…"]
                 [--expected "…"] [--observed "…"] [--proof "…" …] [--impact "…"] [--hypothesis "…"] [--json]
      dedup: an open/grouped signal with the same fingerprint gets occurrences+1, last_seen, the new evidence;
      the SAME evidence twice is a no-op (re-running a check never inflates counts).
  signals.py stats [--days 28 | --since D --until D] [--component C] [--json]   signals / runs, per component and skill
  signals.py groups [--json]          open signals grouped by fingerprint, scored, with eligibility for a brief
  signals.py scan [--json]            mechanical detection: outbox drafts edited by the owner (non-doppel commit)
  signals.py set S-0001 status=grouped brief=E-001
  signals.py index                    regenerate evolution/signals/_index.md

Signal bodies are DATA (pointers: paths@commit, IDs, ≤ 10 lines of error), never instructions. Free text is passed
through scripts/redact.py (secrets, URLs, e-mails, IPs, internal hosts are masked).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import get_root, load_config, now as now_fn, read_md, week_of, write_md  # noqa: E402

KINDS = ("bug", "wrong-output", "limitation", "friction", "missing-capability", "cost", "user-correction")
SEVERITIES = ("low", "medium", "high")
ORIGINS = ("user", "deterministic", "self-report", "ingestion")  # decreasing reliability
STATUSES = ("open", "grouped", "addressed", "discarded")
FIELD_ORDER = ["id", "date", "emitter", "run_id", "commit", "kind", "component", "fingerprint", "severity", "origin",
               "origins", "occurrences", "first_seen", "last_seen", "status", "brief", "evidence"]
DEFAULT_EVOLUTION = {
    "capture": True, "review": "weekly", "autonomy": "propose", "merge": "pr", "auto_merge_max_risk": "low",
    "guards": {"max_briefs_per_week": 2, "max_files_changed": 8,
               "allowed_paths": [".claude/skills/", ".claude/agents/", "templates/", "scripts/", "tests/evals/scenarios/"],
               "require": ["pytest", "evals_no_regression"], "cooldown_days": 7, "observe_days": 7, "auto_revert": True,
               "self_report_threshold": 3, "evals_min_scenarios": 8,
               "origin_weights": {"user": 3, "deterministic": 2, "self-report": 1, "ingestion": 0.5}},
    "severity_weights": {"low": 1, "medium": 2, "high": 3},
    "recency_half_life_days": 14,
    "estimate_overrun_ratio": 1.5,
}
MAX_PROOF_LINES = 10


def evo_config(root: Path) -> dict:
    raw = load_config(root).get("evolution") or {}
    cfg = {**DEFAULT_EVOLUTION, **{k: v for k, v in raw.items() if k != "guards"}}
    cfg["guards"] = {**DEFAULT_EVOLUTION["guards"], **(raw.get("guards") or {})}
    return cfg


def sig_dir(root: Path) -> Path:
    return root / "evolution" / "signals"


def _ts(d: dt.datetime) -> str:
    return d.strftime("%Y-%m-%dT%H:%M")


def _parse_ts(v) -> dt.datetime:
    if isinstance(v, dt.datetime):
        return v.replace(tzinfo=None)
    return dt.datetime.fromisoformat(str(v).replace(" ", "T"))


def git_head(root: Path) -> str:
    r = subprocess.run(["git", "-C", str(root), "rev-parse", "--short", "HEAD"], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else "nogit"


def _redact(text: str) -> str:
    if not text:
        return ""
    try:
        from redact import redact
        text = redact(text)[0]
    except Exception:  # never block an emission on the redactor
        pass
    lines = text.strip().splitlines()
    if len(lines) > MAX_PROOF_LINES:
        lines = lines[:MAX_PROOF_LINES] + [f"[… {len(lines) - MAX_PROOF_LINES} lignes coupées]"]
    return "\n".join(lines)


def normalize_fingerprint(fp: str) -> str:
    s = unicodedata.normalize("NFKD", fp).encode("ascii", "ignore").decode().lower().strip()
    s = re.sub(r"[\s_/:]+", "-", s)
    s = re.sub(r"[^a-z0-9.\-]", "", s)
    s = re.sub(r"-{2,}", "-", s)
    s = re.sub(r"\.{2,}", ".", s)
    return s.strip(".-") or "unknown"


# --------------------------------------------------------------------------- signals


def load_signals(root: Path) -> dict[str, tuple[dict, str, Path]]:
    out = {}
    for p in sorted(sig_dir(root).glob("S-*.md")):
        meta, body = read_md(p)
        out[meta.get("id", p.stem)] = (meta, body, p)
    return out


def next_signal_id(root: Path) -> str:
    nums = [int(m.group(1)) for p in sig_dir(root).glob("S-*.md") if (m := re.match(r"S-(\d+)", p.stem))]
    return f"S-{max(nums, default=0) + 1:04d}"


def _ordered(meta: dict) -> dict:
    out = {k: meta.get(k) for k in FIELD_ORDER if k in meta or k in ("brief",)}
    out.update({k: v for k, v in meta.items() if k not in out})
    return out


def _body(expected, observed, proofs, impact, hypothesis) -> str:
    def sec(title, content):
        return f"## {title}\n{content.strip() if content else '-'}\n"
    proof_txt = "\n".join(f"- {p}" for p in proofs) if proofs else "-"
    hyp = f"Hypothèse : {hypothesis}" if hypothesis else "-"
    return "\n".join([sec("Attendu", expected), sec("Observé", observed), sec("Preuves", proof_txt),
                      sec("Impact", impact), sec("Hypothèse", hyp)])


def emit(root: Path, *, emitter: str, kind: str, component: str, fingerprint: str, severity: str = "medium",
         origin: str = "self-report", run: str | None = None, commit: str | None = None,
         evidence: str | None = None, expected: str = "", observed: str = "", proofs: list[str] | None = None,
         impact: str = "", hypothesis: str = "") -> dict:
    if kind not in KINDS or severity not in SEVERITIES or origin not in ORIGINS:
        raise SystemExit(f"invalid kind/severity/origin: {kind}/{severity}/{origin}")
    cfg = evo_config(root)
    if not cfg.get("capture", True):
        return {"skipped": "evolution.capture is false"}
    now = now_fn(load_config(root))
    fp = normalize_fingerprint(fingerprint)
    commit = commit or git_head(root)
    ev = evidence or run or f"{commit}@{_ts(now)}"
    ev_line = f"{_ts(now)} · {ev}"
    proofs = [_redact(p) for p in (proofs or []) if p]
    sd = sig_dir(root)
    sd.mkdir(parents=True, exist_ok=True)

    for sid, (meta, body, path) in load_signals(root).items():
        if meta.get("fingerprint") == fp and meta.get("status") in ("open", "grouped"):
            known = [str(e).split(" · ", 1)[-1] for e in meta.get("evidence") or []]
            if ev in known:
                return {"id": sid, "action": "unchanged", "occurrences": meta.get("occurrences")}
            meta["occurrences"] = int(meta.get("occurrences") or 1) + 1
            meta["last_seen"] = _ts(now)
            meta["evidence"] = list(meta.get("evidence") or []) + [ev_line]
            origins = dict(meta.get("origins") or {meta.get("origin"): 1})
            origins[origin] = origins.get(origin, 0) + 1
            meta["origins"] = origins
            if ORIGINS.index(origin) < ORIGINS.index(meta.get("origin", "ingestion")):
                meta["origin"] = origin  # the most reliable origin seen
            if SEVERITIES.index(severity) > SEVERITIES.index(meta.get("severity", "low")):
                meta["severity"] = severity
            add = f"- {_ts(now)} · {ev} · {origin}" + (f" · {proofs[0].splitlines()[0]}" if proofs else "")
            body = re.sub(r"(## Preuves\n)(.*?)(\n## Impact)", lambda m: m.group(1) + m.group(2).rstrip("\n") + "\n" + add + "\n" + m.group(3),
                          body, count=1, flags=re.S)
            write_md(path, _ordered(meta), body)
            write_index(root)
            return {"id": sid, "action": "incremented", "occurrences": meta["occurrences"]}

    sid = next_signal_id(root)
    meta = {"id": sid, "date": _ts(now), "emitter": emitter, "run_id": run, "commit": commit, "kind": kind,
            "component": component, "fingerprint": fp, "severity": severity, "origin": origin, "origins": {origin: 1},
            "occurrences": 1, "first_seen": _ts(now), "last_seen": _ts(now), "status": "open", "brief": None,
            "evidence": [ev_line]}
    write_md(sd / f"{sid}.md", _ordered(meta), _body(_redact(expected), _redact(observed), proofs, _redact(impact),
                                                       _redact(hypothesis)))
    write_index(root)
    return {"id": sid, "action": "created", "occurrences": 1}


def set_fields(root: Path, sid: str, assignments: list[str]) -> dict:
    sigs = load_signals(root)
    if sid not in sigs:
        raise SystemExit(f"{sid} not found")
    meta, body, path = sigs[sid]
    for a in assignments:
        k, v = a.split("=", 1)
        if k == "status" and v not in STATUSES:
            raise SystemExit(f"invalid status {v}")
        meta[k] = v or None
    write_md(path, _ordered(meta), body)
    write_index(root)
    return meta


def write_index(root: Path) -> None:
    lines = []
    order = {"open": 0, "grouped": 1, "addressed": 2, "discarded": 3}
    for sid, (m, _, _) in sorted(load_signals(root).items(), key=lambda x: (order.get(x[1][0].get("status"), 9), x[0])):
        lines.append(" · ".join(str(x) for x in (sid, m.get("status"), m.get("origin"), m.get("kind"), m.get("severity"),
                                                  f"×{m.get('occurrences')}", m.get("component"), m.get("fingerprint"),
                                                  m.get("brief") or "-", m.get("last_seen"))))
    body = "\n".join(lines) if lines else "_(vide)_"
    sig_dir(root).mkdir(parents=True, exist_ok=True)
    (sig_dir(root) / "_index.md").write_text(
        "# Signaux\n<!-- generated by scripts/signals.py — do not edit by hand -->\n"
        "`id · statut · origine · kind · gravité · occurrences · composant · fingerprint · brief · vu le`\n\n" + body + "\n",
        encoding="utf-8")


# --------------------------------------------------------------------------- runs


def _runs_file(root: Path, when: dt.datetime) -> Path:
    return root / "evolution" / "runs" / f"{week_of(when)}.jsonl"


def load_runs(root: Path) -> dict[str, dict]:
    runs: dict[str, dict] = {}
    for p in sorted((root / "evolution" / "runs").glob("*.jsonl")):
        for line in p.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            runs.setdefault(rec["run_id"], {}).update(rec)
    return runs


def run_start(root: Path, skill: str, args: str = "") -> str:
    if not evo_config(root).get("capture", True):
        return "R-disabled"
    now = now_fn(load_config(root))
    base = f"R-{now:%Y-%m-%d-%H%M}"
    existing = load_runs(root)
    rid, n = base, 2
    while rid in existing:
        rid, n = f"{base}-{n}", n + 1
    rec = {"run_id": rid, "event": "start", "skill": skill.lstrip("/"), "args": args, "start": _ts(now),
           "commit_before": git_head(root), "outcome": "running"}
    f = _runs_file(root, now)
    f.parent.mkdir(parents=True, exist_ok=True)
    with f.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rid


def run_end(root: Path, run_id: str, outcome: str, signals: list[str] | None = None) -> dict:
    if run_id == "R-disabled":
        return {}
    runs = load_runs(root)
    if run_id not in runs:
        raise SystemExit(f"unknown run {run_id}")
    if outcome not in ("ok", "error", "partial"):
        raise SystemExit("outcome must be ok|error|partial")
    now = now_fn(load_config(root))
    start = runs[run_id]
    rec = {**{k: v for k, v in start.items() if k != "event"}, "event": "end", "end": _ts(now),
           "commit_after": git_head(root), "outcome": outcome, "signals": signals or []}
    with _runs_file(root, _parse_ts(start["start"])).open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


# --------------------------------------------------------------------------- stats & groups


def _evidence_times(meta: dict) -> list[dt.datetime]:
    out = []
    for e in meta.get("evidence") or []:
        try:
            out.append(_parse_ts(str(e).split(" · ", 1)[0]))
        except ValueError:
            continue
    return out or [_parse_ts(meta.get("last_seen") or meta.get("date"))]


def stats(root: Path, since: dt.datetime, until: dt.datetime, component: str | None = None,
          fingerprints: set[str] | None = None, any_of: bool = False) -> dict:
    """Signal occurrences / runs in [since, until). Filters: component prefix and/or fingerprints (AND by default,
    OR with any_of=True — used to observe a brief: its component OR the problems it was meant to fix)."""
    runs = [r for r in load_runs(root).values() if since <= _parse_ts(r["start"]) < until]
    runs_by_skill: dict[str, int] = {}
    for r in runs:
        runs_by_skill[r["skill"]] = runs_by_skill.get(r["skill"], 0) + 1
    by_comp: dict[str, int] = {}
    by_skill: dict[str, int] = {}
    total = 0
    for sid, (m, _, _) in load_signals(root).items():
        comp_ok = not component or str(m.get("component", "")).startswith(component)
        fp_ok = fingerprints is None or m.get("fingerprint") in fingerprints
        if any_of and component and fingerprints is not None:
            if not (str(m.get("component", "")).startswith(component) or m.get("fingerprint") in fingerprints):
                continue
        elif not (comp_ok and fp_ok):
            continue
        n = sum(1 for t in _evidence_times(m) if since <= t < until)
        if not n:
            continue
        total += n
        by_comp[m.get("component")] = by_comp.get(m.get("component"), 0) + n
        em = str(m.get("emitter", ""))
        if em.startswith("skill:/"):
            by_skill[em[7:]] = by_skill.get(em[7:], 0) + n
    n_runs = len(runs)
    return {
        "since": _ts(since), "until": _ts(until), "runs": n_runs, "signals": total,
        "rate": round(total / n_runs, 3) if n_runs else None,
        "by_component": {c: {"signals": n, "rate": round(n / n_runs, 3) if n_runs else None}
                         for c, n in sorted(by_comp.items(), key=lambda x: -x[1])},
        "by_skill": {s: {"runs": runs_by_skill.get(s, 0), "signals": by_skill.get(s, 0),
                         "rate": round(by_skill.get(s, 0) / runs_by_skill[s], 3) if runs_by_skill.get(s) else None}
                     for s in sorted(set(runs_by_skill) | set(by_skill))},
    }


def signal_score(meta: dict, cfg: dict, now: dt.datetime) -> float:
    sev = cfg["severity_weights"].get(meta.get("severity"), 1)
    weights = cfg["guards"]["origin_weights"]
    origins = meta.get("origins") or {meta.get("origin"): meta.get("occurrences") or 1}
    freq_w = sum(weights.get(o, 0) * n for o, n in origins.items())  # frequency × origin weight
    age_days = max((now - _parse_ts(meta.get("last_seen") or meta.get("date"))).total_seconds() / 86400, 0)
    recency = math.pow(0.5, age_days / float(cfg.get("recency_half_life_days") or 14))
    return round(sev * freq_w * recency, 3)


def groups(root: Path) -> list[dict]:
    cfg = evo_config(root)
    now = now_fn(load_config(root))
    th = int(cfg["guards"]["self_report_threshold"])
    out: dict[str, dict] = {}
    for sid, (m, _, _) in load_signals(root).items():
        if m.get("status") not in ("open", "grouped"):
            continue
        g = out.setdefault(m["fingerprint"], {"fingerprint": m["fingerprint"], "components": set(), "signals": [],
                                              "origins": {}, "score": 0.0, "max_severity": "low", "briefs": set()})
        g["components"].add(m.get("component"))
        g["signals"].append(sid)
        for o, n in (m.get("origins") or {m.get("origin"): m.get("occurrences") or 1}).items():
            g["origins"][o] = g["origins"].get(o, 0) + int(n)
        g["score"] = round(g["score"] + signal_score(m, cfg, now), 3)
        if SEVERITIES.index(m.get("severity", "low")) > SEVERITIES.index(g["max_severity"]):
            g["max_severity"] = m["severity"]
        if m.get("brief"):
            g["briefs"].add(m["brief"])
    try:
        from evolution import component_in_cooldown
    except Exception:  # pragma: no cover
        component_in_cooldown = lambda root, comp: None  # noqa: E731
    res = []
    for g in out.values():
        o = g["origins"]
        if o.get("user") or o.get("deterministic"):
            eligible, why = True, "signal user/deterministic"
        elif o.get("self-report", 0) >= th:
            eligible, why = True, f"self-report ≥ {th}"
        elif set(o) <= {"ingestion"}:
            eligible, why = False, "ingestion seule : jamais de brief"
        else:
            eligible, why = False, f"self-report < {th}"
        cooldown = {c: u for c in g["components"] if (u := component_in_cooldown(root, c))}
        res.append({**g, "components": sorted(g["components"]), "briefs": sorted(g["briefs"]), "eligible": eligible,
                    "eligibility": why, "cooldown_until": cooldown})
    return sorted(res, key=lambda g: -g["score"])


# --------------------------------------------------------------------------- mechanical scan

# draft folder -> (emitting agent, component file). Add a folder here when a domain module adds a drafts folder.
DRAFT_FOLDERS = {"outbox": ("agent:reporter", ".claude/agents/reporter.md")}


def scan(root: Path) -> list[dict]:
    """Drafts (folders in DRAFT_FOLDERS) edited by a commit that is not a doppel(...) commit = owner corrections."""
    results = []
    for folder, (agent, comp) in DRAFT_FOLDERS.items():
        for p in sorted((root / folder).glob("*.md")):
            if p.name.startswith("_"):
                continue
            rel = str(p.relative_to(root))
            # plain per-path history: --follow would attribute similar files' history (copies, demo fixtures) to this one
            log = subprocess.run(["git", "-C", str(root), "log", "--format=%h\t%s", "--no-renames", "--", rel],
                                 capture_output=True, text=True).stdout.strip().splitlines()
            if len(log) < 2:
                continue
            for line in log[:-1]:  # all commits but the creation
                h, _, subject = line.partition("\t")
                if not subject.startswith("doppel("):
                    r = emit(root, emitter="user", kind="user-correction", component=comp,
                             fingerprint=f"{folder}.draft-rewritten-by-owner", severity="low", origin="user",
                             evidence=f"{rel}@{h}", expected="Brouillon validable sans réécriture",
                             observed=f"{rel} modifié par le propriétaire avant validation ({agent})",
                             proofs=[f"git show {h} -- {rel}"], impact="Temps de réécriture pour le propriétaire")
                    results.append({**r, "file": rel, "commit": h})
    return results


# --------------------------------------------------------------------------- CLI


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run"); r.add_argument("action", choices=["start", "end"]); r.add_argument("--skill")
    r.add_argument("--args", default=""); r.add_argument("--run"); r.add_argument("--outcome", default="ok"); r.add_argument("--signals")
    e = sub.add_parser("emit")
    for a in ("--emitter", "--kind", "--component", "--fingerprint"):
        e.add_argument(a, required=True)
    e.add_argument("--severity", default="medium"); e.add_argument("--origin", default="self-report")
    for a in ("--run", "--commit", "--evidence", "--expected", "--observed", "--impact", "--hypothesis"):
        e.add_argument(a)
    e.add_argument("--proof", action="append"); e.add_argument("--json", action="store_true")
    st = sub.add_parser("stats"); st.add_argument("--days", type=int, default=28); st.add_argument("--since"); st.add_argument("--until")
    st.add_argument("--component"); st.add_argument("--json", action="store_true")
    g = sub.add_parser("groups"); g.add_argument("--json", action="store_true")
    sc = sub.add_parser("scan"); sc.add_argument("--json", action="store_true")
    s = sub.add_parser("set"); s.add_argument("id"); s.add_argument("assign", nargs="+")
    sub.add_parser("index")
    args = ap.parse_args(argv)
    root = get_root(args.root)

    if args.cmd == "run":
        if args.action == "start":
            print(run_start(root, args.skill or "?", args.args))
        else:
            sigs = [x.strip() for x in (args.signals or "").split(",") if x.strip()]
            print(json.dumps(run_end(root, args.run, args.outcome, sigs), ensure_ascii=False))
    elif args.cmd == "emit":
        res = emit(root, emitter=args.emitter, kind=args.kind, component=args.component, fingerprint=args.fingerprint,
                   severity=args.severity, origin=args.origin, run=args.run, commit=args.commit, evidence=args.evidence,
                   expected=args.expected or "", observed=args.observed or "", proofs=args.proof or [],
                   impact=args.impact or "", hypothesis=args.hypothesis or "")
        print(json.dumps(res, ensure_ascii=False) if args.json else f"{res.get('id', '-')} {res.get('action', res.get('skipped'))} (×{res.get('occurrences', 0)})")
    elif args.cmd == "stats":
        now = now_fn(load_config(root))
        until = _parse_ts(args.until) if args.until else now + dt.timedelta(minutes=1)
        since = _parse_ts(args.since) if args.since else now - dt.timedelta(days=args.days)
        res = stats(root, since, until, args.component)
        if args.json:
            print(json.dumps(res, ensure_ascii=False, indent=1))
        else:
            print(f"# Signaux {res['since']} → {res['until']} : {res['signals']} signaux / {res['runs']} runs (taux {res['rate']})")
            for c, v in res["by_component"].items():
                print(f"- {c} : {v['signals']} (taux {v['rate']})")
            for s_, v in res["by_skill"].items():
                print(f"- /{s_} : {v['signals']} signaux / {v['runs']} runs (taux {v['rate']})")
    elif args.cmd == "groups":
        res = groups(root)
        if args.json:
            print(json.dumps(res, ensure_ascii=False, indent=1))
        else:
            for g_ in res:
                print(f"- {g_['fingerprint']} · score {g_['score']} · {','.join(g_['signals'])} · {g_['origins']} · "
                      f"{'ÉLIGIBLE' if g_['eligible'] else 'non éligible'} ({g_['eligibility']})"
                      + (f" · cooldown {g_['cooldown_until']}" if g_["cooldown_until"] else ""))
            print("" if res else "aucun signal ouvert")
    elif args.cmd == "scan":
        res = scan(root)
        print(json.dumps(res, ensure_ascii=False) if args.json else "\n".join(f"{r_['id']} {r_['action']} · {r_['file']}@{r_['commit']}" for r_ in res) or "rien")
    elif args.cmd == "set":
        print(set_fields(root, args.id, args.assign))
    elif args.cmd == "index":
        write_index(root)
        print("evolution/signals/_index.md written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
