"""Collect scenarios: nothing is collected into a repository not declared private; a mail, an invoice and an
appointment arrive once each as inbox items; a calendar appointment is never overwritten by a weather placement."""
import json
import sys
from pathlib import Path

import collect
import common
import tasks
import weather

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # tests/ (synthetic forecast)
from weather_fixture import add_home, week_forecast  # noqa: E402

MAIL = {"id": "m1", "subject": "Facture 118", "sender": "compta@artisan.be", "date": "2026-11-23T08:00:00+01:00",
        "labelIds": ["INBOX"], "plaintextBody": "Ci-joint la facture, échéance 30 jours.",
        "attachments": [{"filename": "facture-118.pdf", "attachmentId": "a1"}]}
EVENT = {"id": "e1", "summary": "Réunion syndic", "start": {"dateTime": "2026-11-26T08:00:00+01:00"},
         "end": {"dateTime": "2026-11-26T11:00:00+01:00"}, "updated": "2026-11-20T08:00:00Z", "status": "confirmed"}


def test_default_config_never_collects(doppel_root):
    root = doppel_root("2026-11-23 08:00")
    assert collect.guard(root)[0] is False


def test_mail_invoice_and_appointment_arrive_once_and_are_respected(doppel_root, monkeypatch):
    root = doppel_root("2026-11-23 08:00")
    common.write_config_block(root, "collect", {"enabled": True, "private_repo": True})
    for _ in range(2):  # a second pass must not duplicate anything
        collect.ingest_mail(root, [MAIL])
        collect.ingest_events(root, "perso", [EVENT])
    items = sorted(p.name for p in (root / "inbox").glob("*.md"))
    assert items == ["2026-11-23_facture_facture-118.md", "2026-11-26_rdv_reunion-syndic.md"]
    add_home(root)
    (root / "forecast.json").write_text(json.dumps(week_forecast()), encoding="utf-8")
    monkeypatch.setenv("DOPPEL_WEATHER_FILE", str(root / "forecast.json"))
    tasks.new_task(root, "p", "Démousser la toiture", estimate=3, deadline="2026-11-29", climate="sec,hors-gel",
                   location="maison")
    plan = weather.plan_task(root, "T-0001")
    assert plan["slot"]["date"] != "2026-11-26" or plan["slot"]["window"] >= "11:00"  # the meeting stays put
