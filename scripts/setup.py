"""Initialisation of a doppel project created from the template (skill /setup) — deterministic writes + checklist.

  setup.py status [--json]                         checklist: identity, domain, template base, mail/calendar intake,
                                                   places, preferences — what is done, what is missing
  setup.py set owner="Christophe" domain="…" timezone=Europe/Brussels data=fr transcription_language=fr
                                                   scalar config values (comments of config.yaml are kept)
  setup.py domain --file domain.md                 replace the content of the « ## Domain » section of CLAUDE.md
  setup.py collect [--enable|--disable] [--private] [--calendar <id>=<alias> …] [--exclude-from x …]
                   [--mail-query "…"] [--no-invoices] [--days-ahead N]
                                                   mail + calendar intake of THIS project (the accounts are the Gmail /
                                                   Google Calendar connectors attached to the project's sessions)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import yaml

from common import get_root, load_config, set_config_scalar, write_config_block

PLACEHOLDER = re.compile(r"à compléter", re.I)
SCALARS = {"owner": "owner", "domain": "domain", "timezone": "timezone", "data": "data",
           "transcription_language": "language"}  # cli name -> config key (first occurrence in config.yaml)


def _domain_section(root: Path) -> str:
    text = (root / "CLAUDE.md").read_text(encoding="utf-8")
    m = re.search(r"^## Domain\n(.*)\Z", text, re.S | re.M)
    return m.group(1).strip() if m else ""


def set_domain(root: Path, content: str) -> None:
    path = root / "CLAUDE.md"
    text = path.read_text(encoding="utf-8")
    m = re.search(r"^## Domain\n", text, re.M)
    if not m:
        raise SystemExit("CLAUDE.md has no « ## Domain » section")
    path.write_text(text[: m.end()] + "\n" + content.strip() + "\n", encoding="utf-8")


def set_scalars(root: Path, assignments: list[str]) -> list[str]:
    done = []
    for a in assignments:
        k, _, v = a.partition("=")
        if k not in SCALARS:
            raise SystemExit(f"unknown key {k}; expected {sorted(SCALARS)}")
        key = SCALARS[k]
        if k == "transcription_language":  # `language:` under transcription (the 2nd `language` key is a block)
            path = root / "config.yaml"
            text = path.read_text(encoding="utf-8")
            text = re.sub(r"(^transcription:\n(?:  .*\n)*?  language:\s*)([^#\n]*?)(\s*(#.*)?)$",
                          lambda m: f"{m.group(1)}{v}{m.group(3)}", text, count=1, flags=re.M)
            path.write_text(text, encoding="utf-8")
        else:
            set_config_scalar(root, key, json.dumps(v, ensure_ascii=False) if k in ("owner", "domain") else v)
        done.append(f"{k}={v}")
    return done


def set_collect(root: Path, *, enable=None, private=False, calendars=None, exclude_from=None, mail_query=None,
                no_invoices=False, days_ahead=None) -> dict:
    cur = dict(load_config(root).get("collect") or {})
    cur["mail"] = dict(cur.get("mail") or {})
    if enable is not None:
        cur["enabled"] = bool(enable)
    if private:
        cur["private_repo"] = True
    if calendars is not None:
        cals = []
        for c in calendars:
            cid, _, alias = c.rpartition("=")
            if not cid or not re.fullmatch(r"[a-z0-9-]+", alias):
                raise SystemExit(f"calendar must be <id>=<alias-slug>, got {c}")
            cals.append({"id": cid, "alias": alias})
        cur["calendars"] = cals
    if exclude_from is not None:
        cur["mail"]["exclude_from"] = list(dict.fromkeys(exclude_from))
    if mail_query:
        cur["mail"]["query"] = mail_query
    if no_invoices:
        cur["mail"]["invoices_query"] = ""
    if days_ahead is not None:
        cur["calendar_days_ahead"] = int(days_ahead)
    if cur.get("enabled") and not cur.get("private_repo"):
        raise SystemExit("refused: enabling collection needs --private (the repository must be private)")
    write_config_block(root, "collect", cur)
    return cur


def status(root: Path) -> dict:
    cfg = load_config(root)
    col = cfg.get("collect") or {}
    tpl = cfg.get("template") or {}
    prefs = (root / "preferences.md").read_text(encoding="utf-8") if (root / "preferences.md").exists() else ""
    domain = _domain_section(root)
    checks = {
        "owner": not PLACEHOLDER.search(str(cfg.get("owner") or "à compléter")),
        "domain": not PLACEHOLDER.search(str(cfg.get("domain") or "à compléter")),
        "claude_domain_section": bool(domain) and not PLACEHOLDER.search(domain),
        "template_base": bool(tpl.get("base")),
        "collect_enabled": bool(col.get("enabled") and col.get("private_repo")),
        "calendars": len(col.get("calendars") or []),
        "places": sorted((cfg.get("places") or {}).keys()),
        "projects": sorted(cfg["projects"].keys()),
        "preferences": len(re.findall(r"^- \d{4}-\d{2}-\d{2} · ", prefs.split("## Remplacées")[0], re.M)),
    }
    todo = [k for k in ("owner", "domain", "claude_domain_section", "template_base") if not checks[k]]
    return {"checks": checks, "missing": todo}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status").add_argument("--json", action="store_true")
    s = sub.add_parser("set"); s.add_argument("assign", nargs="+")
    d = sub.add_parser("domain"); d.add_argument("--file", required=True)
    c = sub.add_parser("collect")
    g = c.add_mutually_exclusive_group(); g.add_argument("--enable", action="store_true", default=None)
    g.add_argument("--disable", action="store_true")
    c.add_argument("--private", action="store_true"); c.add_argument("--calendar", action="append")
    c.add_argument("--exclude-from", action="append"); c.add_argument("--mail-query")
    c.add_argument("--no-invoices", action="store_true"); c.add_argument("--days-ahead", type=int)
    args = ap.parse_args(argv)
    root = get_root(args.root)
    if args.cmd == "status":
        st = status(root)
        if args.json:
            print(json.dumps(st, ensure_ascii=False, indent=1))
        else:
            for k, v in st["checks"].items():
                print(f"{'✓' if v else '✗'} {k}: {v}")
            print("manque : " + (", ".join(st["missing"]) or "rien"))
    elif args.cmd == "set":
        print("; ".join(set_scalars(root, args.assign)))
    elif args.cmd == "domain":
        set_domain(root, Path(args.file).read_text(encoding="utf-8"))
        print("CLAUDE.md « Domain » mis à jour")
    else:
        enable = True if args.enable else (False if args.disable else None)
        cur = set_collect(root, enable=enable, private=args.private, calendars=args.calendar,
                          exclude_from=args.exclude_from, mail_query=args.mail_query, no_invoices=args.no_invoices,
                          days_ahead=args.days_ahead)
        print(yaml.safe_dump({"collect": cur}, allow_unicode=True, sort_keys=False).strip())
    return 0


if __name__ == "__main__":
    from common import run_main
    sys.exit(run_main(main, __file__))
