"""Refuse a diff that an autonomous /improve run must not merge.  PROTECTED.

  check_diff.py [--base main] [--head HEAD] [--brief E-001] [--json]

Refused when:
  - a path of evolution/protected.txt is touched (as listed in the BASE version of that file):
      `path`            exact file          `dir/`        anything below
      `file#core`       a changed line inside <!-- core:begin --> … <!-- core:end --> (or a marker changed)
      `dir/**#existing` modification / deletion / rename of a file existing in base (additions allowed)
  - more files than evolution.guards.max_files_changed;
  - a file outside evolution.guards.allowed_paths;
  - with --brief: a file outside the brief's `files` scope (its regression scenario under tests/evals/scenarios/ is allowed).
Exit 0 = OK, 1 = refused. The protected list and limits are read from BASE, so a branch cannot loosen them for itself.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import yaml  # noqa: E402

from common import get_root  # noqa: E402

CORE_BEGIN, CORE_END = "<!-- core:begin", "<!-- core:end"


def git(root: Path, *args: str) -> str:
    r = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"git {' '.join(args)}: {r.stderr.strip()}")
    return r.stdout


def show(root: Path, ref: str, path: str) -> str | None:
    r = subprocess.run(["git", "-C", str(root), "show", f"{ref}:{path}"], capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else None


def changed_files(root: Path, base: str, head: str) -> list[tuple[str, str, str | None]]:
    """[(status, path, old_path)] with renames detected."""
    out = []
    for line in git(root, "diff", "--name-status", "-M", f"{base}...{head}").splitlines():
        parts = line.split("\t")
        st = parts[0][0]
        if st == "R":
            out.append(("R", parts[2], parts[1]))
        else:
            out.append((st, parts[1], None))
    return out


def core_range(text: str) -> tuple[int, int] | None:
    lines = text.splitlines()
    b = next((i + 1 for i, l in enumerate(lines) if l.strip().startswith(CORE_BEGIN)), None)
    e = next((i + 1 for i, l in enumerate(lines) if l.strip().startswith(CORE_END)), None)
    return (b, e) if b and e and b < e else None


def touched_old_lines(root: Path, base: str, head: str, path: str) -> list[tuple[int, int]]:
    """Old-file line ranges touched by the diff (deletions/changes; pure insertions as (n, n))."""
    ranges = []
    for line in git(root, "diff", "-U0", f"{base}...{head}", "--", path).splitlines():
        m = re.match(r"^@@ -(\d+)(?:,(\d+))? \+\d+(?:,\d+)? @@", line)
        if m:
            start, count = int(m.group(1)), int(m.group(2) if m.group(2) is not None else 1)
            ranges.append((start, start + count - 1) if count else (start, start))
    return ranges


def load_protected(root: Path, base: str) -> list[str]:
    text = show(root, base, "evolution/protected.txt") or ""
    return [l.strip() for l in text.splitlines() if l.strip() and not l.strip().startswith("#")]


def load_guards(root: Path, base: str) -> dict:
    cfg = yaml.safe_load(show(root, base, "config.yaml") or "") or {}
    from signals import DEFAULT_EVOLUTION
    return {**DEFAULT_EVOLUTION["guards"], **((cfg.get("evolution") or {}).get("guards") or {})}


def check(root: Path, base: str = "main", head: str = "HEAD", brief: str | None = None) -> dict:
    files = changed_files(root, base, head)
    protected = load_protected(root, base)
    guards = load_guards(root, base)
    reasons = []
    paths = [p for _, p, _ in files] + [old for _, _, old in files if old]

    for rule in protected:
        target, _, mode = rule.partition("#")
        for st, path, old in files:
            for p in {path, old} - {None}:
                if mode == "core":
                    if p != target:
                        continue
                    base_text = show(root, base, target)
                    rng = core_range(base_text or "")
                    if rng is None:
                        reasons.append(f"{target} : bloc core introuvable dans la base")
                        continue
                    for a, b in touched_old_lines(root, base, head, target):
                        if a <= rng[1] and b >= rng[0]:
                            reasons.append(f"{target} : lignes {a}-{b} dans la section protégée (core {rng[0]}-{rng[1]})")
                            break
                elif mode == "existing":
                    pattern = target
                    if fnmatch.fnmatch(p, pattern) or (pattern.endswith("/**") and p.startswith(pattern[:-2])):
                        if st != "A" or p == old:
                            reasons.append(f"{p} : scénario/grille existant(e) modifié(e) ({st}) — ajout seulement")
                elif target.endswith("/"):
                    if p.startswith(target):
                        reasons.append(f"{p} : chemin protégé ({target})")
                elif p == target:
                    reasons.append(f"{p} : fichier protégé")

    if len(files) > int(guards["max_files_changed"]):
        reasons.append(f"{len(files)} fichiers modifiés > max_files_changed {guards['max_files_changed']}")
    allowed = guards["allowed_paths"]
    for p in sorted(set(paths)):
        if not any(p.startswith(a) for a in allowed):
            reasons.append(f"{p} : hors allowed_paths")
    if brief:
        bpath = f"evolution/briefs/{brief}.md"
        # scope read from BASE first (the branch cannot widen its own scope), else the working tree
        text = show(root, base, bpath) or ((root / bpath).read_text(encoding="utf-8") if (root / bpath).exists() else None)
        if not text:
            reasons.append(f"brief {brief} introuvable : périmètre non vérifiable")
        meta = yaml.safe_load(text.split("---")[1]) if text else {}
        scope = set(meta.get("files") or [])
        for p in sorted(set(paths)):
            if p not in scope and not p.startswith("tests/evals/scenarios/"):
                reasons.append(f"{p} : hors du périmètre du brief {brief}")
    # dedupe, keep order
    seen, uniq = set(), []
    for r in reasons:
        if r not in seen:
            seen.add(r)
            uniq.append(r)
    return {"ok": not uniq, "base": base, "head": head, "files": [p for _, p, _ in files], "reasons": uniq}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root"); ap.add_argument("--base", default="main"); ap.add_argument("--head", default="HEAD")
    ap.add_argument("--brief"); ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    res = check(get_root(args.root), args.base, args.head, args.brief)
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=1))
    else:
        print(("OK" if res["ok"] else "REFUSÉ") + f" · {len(res['files'])} fichier(s) · {args.base}...{args.head}")
        for r in res["reasons"]:
            print(f"- {r}")
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    from common import run_main
    sys.exit(run_main(main, __file__))
