"""Automatic intake from the owner's mailbox and calendars (skill /collect) — the deterministic half.

The connectors (Gmail, Google Calendar) are only reachable by the model; the skill fetches raw JSON with them and
hands it to this script, which filters, deduplicates, classifies (mail / facture / rdv), cleans and writes the inbox
items, and keeps the sync state. Collected content is the owner's private data: it is committed with the repo, so
collection is refused unless `collect.enabled` AND `collect.private_repo` are true (set only in a PRIVATE repository).

  collect.py guard [--json]                      exit 1 (with the reason) if collection is not allowed
  collect.py plan [--json]                       what to fetch: Gmail queries (since last sync), calendar windows
  collect.py ingest-mail --file msgs.json [--json]
        msgs.json = list of Gmail messages (get_thread/get_message PLAIN_TEXT objects: id, sender, toRecipients,
        date, subject, plaintextBody, labelIds, attachments). New ones → inbox/AAAA-MM-JJ_<mail|facture>_<slug>.md;
        prints the invoice attachments to download into inbox/_raw/.
  collect.py ingest-events --calendar <alias> --file events.json [--json]
        events.json = Google Calendar `events` list (or the whole list_events response). New / changed / cancelled
        events → inbox/AAAA-MM-JJ_rdv_<slug>.md; agenda/busy.yaml = snapshot of timed events (busy slots used by
        weather.py placement).
  collect.py done --mail-synced | --calendar-synced <alias>   record the sync time (end of a successful pass)

State: collect/state.json (committed; message/event ids stored as hashes only).
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import sys
from pathlib import Path

from common import dump_yaml, get_root, load_config, now as now_fn, slugify, write_md

DEFAULTS = {
    "enabled": False,
    "private_repo": False,
    "mail": {
        "query": "in:inbox category:primary",
        "invoices_query": "has:attachment filename:pdf (facture OR invoice OR factuur OR rekening OR \"note d'honoraires\")",
        "exclude_from": [],          # sender substrings never collected (newsletters, notifications…)
        "first_sync_days": 7,        # look-back of the very first pass
        "max_body_chars": 6000,
    },
    "calendars": [],                 # [{id: <calendar id>, alias: <slug>}] — ids stay in the PRIVATE repo only
    "calendar_days_ahead": 21,
    "calendar_days_back": 1,
}
INVOICE_WORDS = re.compile(r"\b(factur\w*|invoice\w*|factuur\w*|rekening|note d'honoraires|avis d'échéance)\b", re.I)
QUOTE_HEADER = re.compile(r"^(Le .{5,120} a écrit\s*:|On .{5,120} wrote\s*:|-{2,} ?(Original Message|Message d'origine|"
                          r"Forwarded message|Message transféré) ?-{2,}|De ?: .+|From: .+)\s*$", re.I)
SEEN_RETENTION_DAYS = 90
FR_SECRET = re.compile(r"(?i)\b((?:mot de passe|mdp|code (?:d'accès|pin|secret)|code de confirmation|password)\s*[:=]\s*)(\S{4,})")


# --------------------------------------------------------------------------- config, guard, state


def collect_config(root: Path) -> dict:
    raw = load_config(root).get("collect") or {}
    cfg = {**DEFAULTS, **raw}
    cfg["mail"] = {**DEFAULTS["mail"], **(raw.get("mail") or {})}
    return cfg


def guard(root: Path) -> tuple[bool, str]:
    cfg = collect_config(root)
    if not cfg["enabled"]:
        return False, "collect.enabled is false (config.yaml)"
    if not cfg["private_repo"]:
        return False, ("collect.private_repo is false: collected mails and events would be committed — enable it only "
                       "in a PRIVATE repository")
    return True, "ok"


def _h(value: str) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:16]


def state_path(root: Path) -> Path:
    return root / "collect" / "state.json"


def load_state(root: Path) -> dict:
    p = state_path(root)
    st = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    st.setdefault("mail", {"last_sync": None, "seen": {}})
    st.setdefault("calendars", {})
    return st


def save_state(root: Path, st: dict) -> None:
    today = now_fn(load_config(root)).date()
    limit = str(today - dt.timedelta(days=SEEN_RETENTION_DAYS))
    st["mail"]["seen"] = {k: v for k, v in st["mail"]["seen"].items() if v >= limit}
    p = state_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(st, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------- plan


def plan(root: Path) -> dict:
    cfg = collect_config(root)
    now = now_fn(load_config(root))
    st = load_state(root)
    last = st["mail"].get("last_sync")
    # Gmail `after:` is day-granular (midnight): take the day before the last sync; ids dedupe the overlap
    since = (dt.datetime.fromisoformat(last).date() - dt.timedelta(days=1)) if last else \
        now.date() - dt.timedelta(days=int(cfg["mail"]["first_sync_days"]))
    after = f"after:{since:%Y/%m/%d}"
    excl = " ".join(f"-from:{x}" for x in cfg["mail"]["exclude_from"])
    queries = [" ".join(x for x in (cfg["mail"]["query"], after, excl) if x)]
    if cfg["mail"]["invoices_query"]:
        queries.append(" ".join(x for x in (cfg["mail"]["invoices_query"], after, excl) if x))
    start = dt.datetime.combine(now.date() - dt.timedelta(days=int(cfg["calendar_days_back"])), dt.time())
    end = dt.datetime.combine(now.date() + dt.timedelta(days=int(cfg["calendar_days_ahead"])), dt.time())
    cals = [{"alias": c.get("alias") or slugify(str(c.get("id")))[:20], "id": c.get("id"),
             "startTime": start.strftime("%Y-%m-%dT%H:%M:%S"), "endTime": end.strftime("%Y-%m-%dT%H:%M:%S")}
            for c in cfg["calendars"]]
    return {"mail_queries": queries, "mail_since": str(since), "calendars": cals}


# --------------------------------------------------------------------------- text cleaning


def mask_secrets(text: str) -> str:
    """Secrets only (passwords, tokens, keys): mail addresses and links stay — they are the owner's own data."""
    from redact import SECRET_PATTERNS, SECRET_PLACEHOLDER
    for kind, rx in SECRET_PATTERNS:
        if kind == "secret assignment":
            text = rx.sub(lambda m: m.group(1) + m.group(2) + (SECRET_PLACEHOLDER if len(m.group(3)) >= 4 else m.group(3))
                          + m.group(4), text)
        elif kind == "secret header":
            text = rx.sub(lambda m: m.group(1) + SECRET_PLACEHOLDER, text)
        else:
            text = rx.sub(SECRET_PLACEHOLDER, text)
    return FR_SECRET.sub(lambda m: m.group(1) + SECRET_PLACEHOLDER, text)


def clean_body(text: str, max_chars: int) -> str:
    """Drop quoted history, signature and tracking noise; collapse blank lines; cap the length."""
    out = []
    for line in (text or "").replace("\r\n", "\n").split("\n"):
        s = line.strip()
        if QUOTE_HEADER.match(s) or s in ("--", "-- "):
            break
        if s.startswith(">"):
            continue
        line = re.sub(r"https?://\S{120,}", "[lien]", line)  # long tracking links
        out.append(line.rstrip())
    body = re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()
    if len(body) > max_chars:
        body = body[:max_chars].rstrip() + "\n[… tronqué]"
    return mask_secrets(body)


def _who(v) -> str:
    if isinstance(v, dict):
        return v.get("email") or v.get("name") or ""
    if isinstance(v, list):
        return ", ".join(filter(None, (_who(x) for x in v)))
    return str(v or "")


def _parse_when(v, tz_name: str = "Europe/Brussels") -> dt.datetime | None:
    """Gmail/Calendar date: ISO, RFC 2822 or epoch ms → naive local time (config timezone)."""
    if v in (None, ""):
        return None
    from zoneinfo import ZoneInfo
    tz = ZoneInfo(tz_name)
    try:
        if isinstance(v, (int, float)) or str(v).isdigit():
            return dt.datetime.fromtimestamp(int(v) / 1000, tz).replace(tzinfo=None)
        d = dt.datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        from email.utils import parsedate_to_datetime
        try:
            d = parsedate_to_datetime(str(v))
        except (TypeError, ValueError):
            return None
    return d.astimezone(tz).replace(tzinfo=None) if d.tzinfo else d


def _unique_path(root: Path, day: str, kind: str, title: str) -> Path:
    base = f"{day}_{kind}_{slugify(title, 40)}"
    p = root / "inbox" / f"{base}.md"
    n = 2
    while p.exists() or (root / "inbox" / "_processed" / p.name).exists():
        p = root / "inbox" / f"{base}-{n}.md"
        n += 1
    return p


# --------------------------------------------------------------------------- mail


def is_invoice(msg: dict) -> bool:
    names = " ".join(str(a.get("filename") or a.get("name") or "") for a in (msg.get("attachments") or []))
    has_pdf = ".pdf" in names.lower()
    return has_pdf and bool(INVOICE_WORDS.search(f"{msg.get('subject') or ''} {names}"))


def ingest_mail(root: Path, messages: list[dict]) -> dict:
    ok, why = guard(root)
    if not ok:
        raise SystemExit(f"collection refused: {why}")
    cfg = collect_config(root)
    now = now_fn(load_config(root))
    st = load_state(root)
    excl = [x.lower() for x in cfg["mail"]["exclude_from"]]
    out = {"written": [], "skipped": {"seen": 0, "sent_by_owner": 0, "excluded": 0}, "downloads": []}
    tz = load_config(root)["timezone"]
    for msg in sorted(messages, key=lambda m: str(_parse_when(m.get("date"), tz) or "")):
        mid = msg.get("id") or msg.get("messageId")
        if not mid:
            continue
        key = _h(f"gmail:{mid}")
        if key in st["mail"]["seen"]:
            out["skipped"]["seen"] += 1
            continue
        labels = msg.get("labelIds") or []
        sender = _who(msg.get("sender") or msg.get("from"))
        st["mail"]["seen"][key] = str(now.date())
        if "SENT" in labels and "INBOX" not in labels:
            out["skipped"]["sent_by_owner"] += 1
            continue
        if any(x in sender.lower() for x in excl):
            out["skipped"]["excluded"] += 1
            continue
        when = _parse_when(msg.get("date"), tz) or now
        kind = "facture" if is_invoice(msg) else "mail"
        subject = (msg.get("subject") or "(sans objet)").strip()
        path = _unique_path(root, f"{when:%Y-%m-%d}", kind, subject)
        atts = msg.get("attachments") or []
        raw = "none"
        lines = [f"- Objet : {subject}", f"- De : {sender}", f"- À : {_who(msg.get('toRecipients'))}"]
        if msg.get("ccRecipients"):
            lines.append(f"- Cc : {_who(msg.get('ccRecipients'))}")
        if atts:
            lines.append("- Pièces jointes : " + ", ".join(str(a.get("filename") or a.get("name") or "?") for a in atts))
        if kind == "facture":
            for a in atts:
                fname = str(a.get("filename") or a.get("name") or "")
                if fname.lower().endswith(".pdf"):
                    target = f"inbox/_raw/{when:%Y-%m-%d}_{slugify(Path(fname).stem, 40)}.pdf"
                    out["downloads"].append({"messageId": mid, "attachmentId": a.get("attachmentId") or a.get("id"),
                                             "filename": fname, "mimeType": a.get("mimeType"), "target": target,
                                             "item": str(path.relative_to(root))})
                    raw = raw if raw != "none" else target
        body = clean_body(msg.get("plaintextBody") or msg.get("body") or msg.get("snippet") or "",
                          int(cfg["mail"]["max_body_chars"]))
        meta = {"date": f"{when:%Y-%m-%d %H:%M}", "type": kind, "from": sender, "project_hint": None, "raw": raw,
                "added": f"{now:%Y-%m-%d %H:%M}", "collected": f"gmail:{key}"}
        write_md(path, meta, "## Contenu\n" + "\n".join(lines) + "\n\n" + body + "\n")
        out["written"].append(str(path.relative_to(root)))
    save_state(root, st)
    return out


# --------------------------------------------------------------------------- calendar


def _event_times(ev: dict, tz: str) -> tuple[dt.datetime | None, dt.datetime | None, bool]:
    s, e = ev.get("start") or {}, ev.get("end") or {}
    if s.get("date"):
        return (dt.datetime.fromisoformat(s["date"]), dt.datetime.fromisoformat(e.get("date") or s["date"]), True)
    return _parse_when(s.get("dateTime"), tz), _parse_when(e.get("dateTime"), tz), False


def ingest_events(root: Path, alias: str, events: list[dict]) -> dict:
    ok, why = guard(root)
    if not ok:
        raise SystemExit(f"collection refused: {why}")
    now = now_fn(load_config(root))
    st = load_state(root)
    cal = st["calendars"].setdefault(alias, {"last_sync": None, "events": {}})
    out = {"new": [], "changed": [], "cancelled": [], "unchanged": 0}
    busy = []
    for ev in events:
        eid = ev.get("id")
        if not eid:
            continue
        key = _h(f"gcal:{alias}:{eid}")
        start, end, all_day = _event_times(ev, load_config(root)["timezone"])
        if not start:
            continue
        status = ev.get("status") or "confirmed"
        stamp = f"{ev.get('updated')}|{status}"
        prev = cal["events"].get(key)
        title = (ev.get("summary") or "(sans titre)").strip()
        if status != "cancelled" and not all_day and end:
            busy.append({"date": f"{start:%Y-%m-%d}", "window": f"{start:%H:%M}-{end:%H:%M}" if end.date() == start.date()
                         else f"{start:%H:%M}-23:59", "title": title, "calendar": alias})
        if prev == stamp:
            out["unchanged"] += 1
            continue
        if prev is None and status == "cancelled":
            cal["events"][key] = stamp
            continue
        change = "annulé" if status == "cancelled" else ("nouveau" if prev is None else "modifié")
        cal["events"][key] = stamp
        when = (f"{start:%Y-%m-%d}" + (f" → {end - dt.timedelta(days=1):%Y-%m-%d}" if end and (end - start).days > 1 else "")
                + " (journée entière)") if all_day else f"{start:%Y-%m-%d %H:%M}–{end:%H:%M}" if end else f"{start:%Y-%m-%d %H:%M}"
        lines = [f"- Changement : {change}", f"- Titre : {title}", f"- Quand : {when}", f"- Agenda : {alias}"]
        if ev.get("location"):
            lines.append(f"- Lieu : {ev['location']}")
        att = [a.get("email") for a in ev.get("attendees") or [] if not a.get("self")]
        if att:
            lines.append(f"- Participants : {', '.join(filter(None, att))}")
        desc = clean_body(ev.get("description") or "", 2000)
        path = _unique_path(root, f"{start:%Y-%m-%d}", "rdv", title)
        meta = {"date": f"{start:%Y-%m-%d %H:%M}", "type": "rdv", "from": _who(ev.get("organizer")) or alias,
                "project_hint": None, "raw": "none", "added": f"{now:%Y-%m-%d %H:%M}", "collected": f"gcal:{key}"}
        write_md(path, meta, "## Contenu\n" + "\n".join(lines) + ("\n\n" + desc if desc else "") + "\n")
        out[{"nouveau": "new", "modifié": "changed", "annulé": "cancelled"}[change]].append(str(path.relative_to(root)))
    # busy snapshot: replace this calendar's entries, keep the others
    bpath = root / "agenda" / "busy.yaml"
    import yaml
    cur = (yaml.safe_load(bpath.read_text(encoding="utf-8")) if bpath.exists() else None) or []
    cur = [b for b in cur if b.get("calendar") != alias and b.get("date", "") >= str(now.date())]
    cur += [b for b in busy if b["date"] >= str(now.date())]
    bpath.parent.mkdir(parents=True, exist_ok=True)
    bpath.write_text("# generated by scripts/collect.py (calendar busy slots, read by weather.py) — do not edit\n"
                     + dump_yaml(sorted(cur, key=lambda b: (b["date"], b["window"]))), encoding="utf-8")
    save_state(root, st)
    return out


def mark_done(root: Path, mail: bool = False, calendar: str | None = None) -> None:
    st = load_state(root)
    stamp = now_fn(load_config(root)).strftime("%Y-%m-%dT%H:%M")
    if mail:
        st["mail"]["last_sync"] = stamp
    if calendar:
        st["calendars"].setdefault(calendar, {"last_sync": None, "events": {}})["last_sync"] = stamp
    save_state(root, st)


def load_busy(root: Path) -> list[dict]:
    p = root / "agenda" / "busy.yaml"
    if not p.exists():
        return []
    import yaml
    return yaml.safe_load(p.read_text(encoding="utf-8")) or []


# --------------------------------------------------------------------------- cli


def _load_list(path: str, key: str) -> list[dict]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, dict):
        if key in data:
            return data[key]
        if "messages" in data:  # a whole get_thread response
            return data["messages"]
        return [data]
    out = []
    for x in data:  # list of threads or of messages
        out.extend(x["messages"] if isinstance(x, dict) and "messages" in x else [x])
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("guard").add_argument("--json", action="store_true")
    sub.add_parser("plan").add_argument("--json", action="store_true")
    m = sub.add_parser("ingest-mail"); m.add_argument("--file", required=True); m.add_argument("--json", action="store_true")
    e = sub.add_parser("ingest-events"); e.add_argument("--calendar", required=True); e.add_argument("--file", required=True)
    e.add_argument("--json", action="store_true")
    d = sub.add_parser("done"); d.add_argument("--mail-synced", action="store_true"); d.add_argument("--calendar-synced")
    args = ap.parse_args(argv)
    root = get_root(args.root)

    if args.cmd == "guard":
        ok, why = guard(root)
        print(json.dumps({"ok": ok, "reason": why}) if args.json else why)
        return 0 if ok else 1
    if args.cmd == "plan":
        p = plan(root)
        if args.json:
            print(json.dumps(p, ensure_ascii=False, indent=1))
        else:
            for q in p["mail_queries"]:
                print(f"gmail: {q}")
            for c in p["calendars"]:
                print(f"agenda {c['alias']}: {c['startTime']} → {c['endTime']}")
        return 0
    if args.cmd == "ingest-mail":
        res = ingest_mail(root, _load_list(args.file, "messages"))
    elif args.cmd == "ingest-events":
        res = ingest_events(root, args.calendar, _load_list(args.file, "events"))
    else:
        mark_done(root, args.mail_synced, args.calendar_synced)
        print("sync recorded")
        return 0
    print(json.dumps(res, ensure_ascii=False, indent=1) if args.json else
          "\n".join(f"{k}: {v}" for k, v in res.items()))
    return 0


if __name__ == "__main__":
    from common import run_main
    sys.exit(run_main(main, __file__))
