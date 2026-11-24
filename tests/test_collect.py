"""Mail + calendar intake (/collect): guard, dedup, classification, cleaning, calendar changes, busy slots."""
import json

import pytest

import collect
import common
import tasks
import weather
from weather_fixture import add_home, install


def enable(root, **extra):
    common.write_config_block(root, "collect", {"enabled": True, "private_repo": True,
                                                "mail": {"exclude_from": ["newsletter@"]}, **extra})


def msg(mid, subject="Devis cuisine", sender="jean@exemple.be", body="Bonjour,\nVoici le devis.\n", **kw):
    return {"id": mid, "subject": subject, "sender": sender, "toRecipients": ["owner@exemple.be"],
            "date": "2026-11-23T09:15:00+01:00", "labelIds": ["INBOX"], "plaintextBody": body, **kw}


@pytest.fixture
def on(repo, monkeypatch):
    monkeypatch.setenv("DOPPEL_NOW", "2026-11-23 10:00")
    enable(repo.root)
    return repo


def test_guard_refuses_unless_enabled_and_private(repo):
    assert collect.guard(repo.root)[0] is False
    common.write_config_block(repo.root, "collect", {"enabled": True, "private_repo": False})
    ok, why = collect.guard(repo.root)
    assert not ok and "PRIVATE" in why
    with pytest.raises(SystemExit):
        collect.ingest_mail(repo.root, [msg("a")])
    assert not (repo.root / "inbox").exists()


def test_template_config_ships_disabled():
    cfg = collect.collect_config(common.REPO_ROOT)
    assert cfg["enabled"] is False and cfg["private_repo"] is False and cfg["calendars"] == []


def test_mail_items_are_written_once_and_cleaned(on):
    body = ("Bonjour,\nLe devis est en pièce jointe.\nmot de passe: Hunter2024!\n\n\n\nCordialement\n-- \nJean\n"
            "Le lun. 20 nov. 2026, Owner a écrit :\n> ancien message\n")
    res = collect.ingest_mail(on.root, [msg("m1", body=body), msg("m1")])
    assert res["written"] == ["inbox/2026-11-23_mail_devis-cuisine.md"] and res["skipped"]["seen"] == 1
    meta, text = common.read_md(on.root / res["written"][0])
    assert meta["type"] == "mail" and meta["from"] == "jean@exemple.be" and meta["date"] == "2026-11-23 09:15"
    assert meta["collected"].startswith("gmail:") and "m1" not in json.dumps(collect.load_state(on.root))
    assert "Le devis est en pièce jointe." in text and "Hunter2024" not in text and "[SECRET MASQUÉ]" in text
    assert "ancien message" not in text and "\n\n\n" not in text
    assert collect.ingest_mail(on.root, [msg("m1")])["written"] == []  # next run: still deduplicated


def test_sent_and_excluded_mails_are_skipped(on):
    res = collect.ingest_mail(on.root, [msg("s", labelIds=["SENT"]), msg("n", sender="newsletter@shop.be")])
    assert res["written"] == [] and res["skipped"] == {"seen": 0, "sent_by_owner": 1, "excluded": 1}


def test_invoice_is_classified_and_its_pdf_requested(on):
    m = msg("f1", subject="Votre facture n° 2026-118", sender="compta@electricien.be",
            attachments=[{"filename": "Facture_2026-118.pdf", "attachmentId": "att9", "mimeType": "application/pdf"}])
    res = collect.ingest_mail(on.root, [m])
    assert res["written"] == ["inbox/2026-11-23_facture_votre-facture-n-2026-118.md"]
    assert res["downloads"] == [{"messageId": "f1", "attachmentId": "att9", "filename": "Facture_2026-118.pdf",
                                 "mimeType": "application/pdf", "target": "inbox/_raw/2026-11-23_facture-2026-118.pdf",
                                 "item": res["written"][0]}]
    assert common.read_md(on.root / res["written"][0])[0]["raw"] == "inbox/_raw/2026-11-23_facture-2026-118.pdf"
    # a PDF without invoice words stays a mail
    other = msg("p", subject="Photos", attachments=[{"filename": "album.pdf", "attachmentId": "x"}])
    assert "_mail_" in collect.ingest_mail(on.root, [other])["written"][0]


def test_plan_queries_follow_the_last_sync(on):
    p = collect.plan(on.root)
    assert p["mail_queries"][0] == "in:inbox category:primary after:2026/11/16 -from:newsletter@"
    assert "filename:pdf" in p["mail_queries"][1]
    collect.mark_done(on.root, mail=True)
    assert "after:2026/11/22" in collect.plan(on.root)["mail_queries"][0]


def event(eid, summary="Notaire", start="2026-11-26T14:00:00+01:00", end="2026-11-26T15:00:00+01:00",
          updated="2026-11-20T08:00:00Z", status="confirmed", **kw):
    return {"id": eid, "summary": summary, "start": {"dateTime": start}, "end": {"dateTime": end},
            "updated": updated, "status": status, **kw}


def test_calendar_new_changed_cancelled_and_busy(on):
    allday = {"id": "d", "summary": "Rangement maison", "start": {"date": "2026-11-25"}, "end": {"date": "2026-11-28"},
              "updated": "x", "status": "confirmed"}
    r1 = collect.ingest_events(on.root, "perso", [event("e1", location="Rue X 1"), allday])
    assert r1["new"] == ["inbox/2026-11-26_rdv_notaire.md", "inbox/2026-11-25_rdv_rangement-maison.md"]
    _, text = common.read_md(on.root / r1["new"][0])
    assert "- Quand : 2026-11-26 14:00–15:00" in text and "- Lieu : Rue X 1" in text
    assert "2026-11-25 → 2026-11-27 (journée entière)" in (on.root / r1["new"][1]).read_text()
    assert collect.load_busy(on.root) == [{"calendar": "perso", "date": "2026-11-26", "title": "Notaire",
                                           "window": "14:00-15:00"}]  # all-day events do not block hours
    r2 = collect.ingest_events(on.root, "perso", [event("e1", location="Rue X 1"), allday])
    assert r2["unchanged"] == 2 and not (r2["new"] or r2["changed"])
    r3 = collect.ingest_events(on.root, "perso", [event("e1", start="2026-11-27T10:00:00+01:00",
                                                        end="2026-11-27T11:00:00+01:00", updated="2026-11-22T08:00:00Z")])
    assert len(r3["changed"]) == 1 and "Changement : modifié" in (on.root / r3["changed"][0]).read_text()
    r4 = collect.ingest_events(on.root, "perso", [event("e1", status="cancelled", updated="2026-11-23T08:00:00Z")])
    assert len(r4["cancelled"]) == 1 and collect.load_busy(on.root) == []


def test_weather_placement_respects_calendar_appointments(on, monkeypatch):
    add_home(on.root)
    install(on.root, monkeypatch)
    collect.ingest_events(on.root, "perso", [event("e1", summary="Dentiste", start="2026-11-26T08:00:00+01:00",
                                                   end="2026-11-26T10:00:00+01:00")])
    tasks.new_task(on.root, "p", "Traiter la terrasse", estimate=2, deadline="2026-11-29", climate="sec,hors-gel",
                   location="maison")
    plan = weather.plan_task(on.root, "T-0001")
    assert plan["slot"]["date"] == "2026-11-26" and plan["slot"]["window"] == "10:00-12:00" and plan["moves"] == []


def test_cli_reads_thread_responses(on, tmp_path):
    f = tmp_path / "mail.json"
    f.write_text(json.dumps([{"id": "t1", "messages": [msg("a"), msg("b", subject="Autre")]}]))
    assert collect.main(["--root", str(on.root), "ingest-mail", "--file", str(f)]) == 0
    assert len(list((on.root / "inbox").glob("*.md"))) == 2
