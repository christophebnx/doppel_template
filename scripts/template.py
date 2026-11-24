"""Keep a doppel project up to date with the doppel template it was created from (skills /setup and /upgrade).

A project repository is created from the template (GitHub « Use this template », private). It records in
config.yaml: template the template repository, the ref it follows and `base` = the template commit its framework
files currently correspond to. An upgrade applies the template's changes base..latest to the FRAMEWORK files only
(3-way: the project's own edits — Domain section of CLAUDE.md, extra skills, tuned templates — are kept; overlapping
edits become conflicts to resolve in the PR), adds the config keys the project does not have yet (never changes a
value the project set), then moves `base`. Data folders are never touched.

  template.py status [--json]                     template, base, is-this-the-template, upstream commits (fetches)
  template.py init --repo <url> [--ref main] [--base <sha>]   record the template (base = latest of ref by default)
  template.py upgrade [--dry-run] [--json]        apply base..latest (run on a branch; the skill opens the PR)

Framework paths: FRAMEWORK below, minus `template.exclude` (paths the project owns, e.g. [README.md]).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import yaml

from common import dump_yaml, get_root, load_config, write_config_block

FRAMEWORK = [
    "CLAUDE.md", "README.md", "pyproject.toml", "uv.lock", ".gitignore", "evolution/protected.txt",
    ".claude/skills/", ".claude/agents/", ".claude/settings.json", "scripts/", "tests/", "templates/", "docs/",
]
NEVER_MERGE_CONFIG = ("projects", "template")  # project-owned blocks, never filled from the template


def git(root: Path, *args, check=True, input: str | None = None) -> subprocess.CompletedProcess:
    r = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, input=input)
    if check and r.returncode != 0:
        raise SystemExit(f"git {' '.join(args[:2])} failed: {r.stderr.strip()[:400]}")
    return r


def template_config(root: Path) -> dict:
    return dict(load_config(root).get("template") or {})


def _norm(url: str) -> str:
    u = (url or "").strip().rstrip("/")
    u = u[:-4] if u.endswith(".git") else u
    return u.split("github.com", 1)[-1].lstrip(":/").lower() if "github.com" in u else u.lower()


def is_template(root: Path) -> bool:
    """True when this repository IS the template (its origin is the configured template repo)."""
    repo = template_config(root).get("repo")
    origin = git(root, "remote", "get-url", "origin", check=False).stdout.strip()
    return bool(repo) and bool(origin) and _norm(repo) == _norm(origin)


def fetch(root: Path, repo: str, ref: str) -> str:
    git(root, "fetch", "--no-tags", "--quiet", repo, ref)
    return git(root, "rev-parse", "FETCH_HEAD").stdout.strip()


def framework_paths(root: Path) -> list[str]:
    excl = set(template_config(root).get("exclude") or [])
    return [p for p in FRAMEWORK if p not in excl]


def _missing_keys(tpl: dict, cur: dict) -> dict:
    """Keys of the template config absent from the project config (recursively), with the template's values."""
    out = {}
    for k, v in tpl.items():
        if k not in cur:
            out[k] = v
        elif isinstance(v, dict) and isinstance(cur.get(k), dict):
            sub = _missing_keys(v, cur[k])
            if sub:
                out[k] = sub
    return out


def _deep_add(cur: dict, add: dict) -> dict:
    out = dict(cur)
    for k, v in add.items():
        out[k] = _deep_add(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def merge_config(root: Path, latest: str) -> list[str]:
    """Add the template's new config keys (defaults) without touching any value the project set."""
    tpl = yaml.safe_load(git(root, "show", f"{latest}:config.yaml").stdout) or {}
    path = root / "config.yaml"
    cur = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    added = []
    for key, val in _missing_keys(tpl, cur).items():
        if key in NEVER_MERGE_CONFIG:
            continue
        if key not in cur:
            write_config_block(root, key, val) if isinstance(val, dict) else _append_scalar(root, key, val)
            added.append(key)
        else:
            write_config_block(root, key, _deep_add(cur[key], val))
            added += [f"{key}.{k}" for k in val]
    return added


def _append_scalar(root: Path, key: str, val) -> None:
    import re
    path = root / "config.yaml"
    text = path.read_text(encoding="utf-8")
    line = dump_yaml({key: val})
    m = re.search(r"^projects:", text, flags=re.M)
    path.write_text(text[: m.start()] + line + text[m.start():] if m else text + line, encoding="utf-8")


def set_template(root: Path, **kw) -> dict:
    cfg = template_config(root)
    cfg.update({k: v for k, v in kw.items() if v is not None})
    write_config_block(root, "template", cfg)
    return cfg


def status(root: Path) -> dict:
    t = template_config(root)
    out = {"repo": t.get("repo"), "ref": t.get("ref", "main"), "base": t.get("base"), "is_template": is_template(root)}
    if out["is_template"] or not out["repo"]:
        return out
    latest = fetch(root, out["repo"], out["ref"])
    out["latest"] = latest
    if out["base"]:
        log = git(root, "log", "--oneline", f"{out['base']}..{latest}", "--", *framework_paths(root), check=False)
        out["upstream_commits"] = [l for l in log.stdout.splitlines() if l]
    return out


def upgrade(root: Path, dry_run: bool = False) -> dict:
    t = template_config(root)
    if is_template(root):
        return {"status": "is-template", "reason": "this repository is the template itself: nothing to upgrade"}
    if not t.get("repo") or not t.get("base"):
        raise SystemExit("template.repo / template.base missing: run `template.py init --repo <url> [--base <sha>]` (/setup)")
    if git(root, "status", "--porcelain", "--", *framework_paths(root), "config.yaml").stdout.strip():
        raise SystemExit("uncommitted changes in framework files or config.yaml: commit or stash them first")
    latest = fetch(root, t["repo"], t.get("ref", "main"))
    if git(root, "cat-file", "-e", f"{t['base']}^{{commit}}", check=False).returncode != 0:
        raise SystemExit(f"template base {t['base'][:12]} not found in the template history (wrong --base?)")
    if latest == t["base"]:
        return {"status": "up-to-date", "base": latest}
    paths = framework_paths(root)
    changed = [l for l in git(root, "diff", "--name-status", t["base"], latest, "--", *paths).stdout.splitlines() if l]
    res = {"status": "dry-run" if dry_run else "applied", "from": t["base"], "to": latest, "files": changed,
           "conflicts": [], "config_added": []}
    if dry_run:
        tpl = yaml.safe_load(git(root, "show", f"{latest}:config.yaml").stdout) or {}
        cur = yaml.safe_load((root / "config.yaml").read_text(encoding="utf-8")) or {}
        res["config_added"] = [k for k in _missing_keys(tpl, cur) if k not in NEVER_MERGE_CONFIG]
        return res
    if changed:
        patch = git(root, "diff", "--binary", t["base"], latest, "--", *paths).stdout
        r = git(root, "apply", "--3way", "--index", "--whitespace=nowarn", check=False, input=patch)
        if r.returncode != 0:
            unmerged = {l.strip() for l in git(root, "diff", "--name-only", "--diff-filter=U").stdout.splitlines() if l}
            failed = {l.split("patch failed: ", 1)[1].rsplit(":", 1)[0] for l in r.stderr.splitlines()
                      if "patch failed: " in l}
            res["conflicts"] = sorted(unmerged | failed) or [r.stderr.strip()[:300]]
            res["status"] = "conflicts"
    res["config_added"] = merge_config(root, latest)
    set_template(root, base=latest)
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status").add_argument("--json", action="store_true")
    i = sub.add_parser("init"); i.add_argument("--repo", required=True); i.add_argument("--ref", default="main")
    i.add_argument("--base")
    u = sub.add_parser("upgrade"); u.add_argument("--dry-run", action="store_true"); u.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    root = get_root(args.root)
    if args.cmd == "init":
        base = args.base or fetch(root, args.repo, args.ref)
        cfg = set_template(root, repo=args.repo, ref=args.ref, base=base)
        print(f"template {cfg['repo']} ({cfg['ref']}) · base {cfg['base'][:12]}")
        return 0
    res = status(root) if args.cmd == "status" else upgrade(root, args.dry_run)
    if getattr(args, "json", False):
        print(json.dumps(res, ensure_ascii=False, indent=1))
    else:
        for k, v in res.items():
            print(f"{k}: " + ("\n  " + "\n  ".join(v) if isinstance(v, list) and v else str(v)))
    return 1 if res.get("status") == "conflicts" else 0


if __name__ == "__main__":
    from common import run_main
    sys.exit(run_main(main, __file__))
