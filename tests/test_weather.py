"""Weather-constrained tasks: climate tokens, slot scoring, placement with replanning, re-check, today sheet."""
import datetime as dt

import pytest

import common
import logbook
import tasks
import today
import weather
from weather_fixture import add_home, install


@pytest.fixture
def home(repo, monkeypatch):
    monkeypatch.setenv("DOPPEL_NOW", "2026-11-23 08:00")  # monday
    add_home(repo.root)
    install(repo.root, monkeypatch)
    return repo


def test_climate_tokens_are_validated():
    c = weather.parse_climate("sec, hors-gel, vent-max:40, sec-avant:6h")
    assert c.dry and c.dry_before_h == 6 and c.temp_min == 1.0 and c.gust_max == 40
    assert weather.parse_climate(["temp-min:5", "hors-gel"]).temp_min == 5
    with pytest.raises(SystemExit):
        weather.parse_climate("ensoleillé")


def test_task_fields_climate_and_location(repo):
    p = tasks.new_task(repo.root, "p", "Peindre le volet", climate="sec,hors-gel", location="maison")
    meta, _ = common.read_md(p)
    assert meta["climate"] == ["sec", "hors-gel"] and meta["location"] == "maison"
    assert list(meta).index("location") < list(meta).index("climate") < list(meta).index("depends_on")
    assert tasks.set_fields(repo.root, "T-0001", ["climate+=vent-max:30"])["climate"] == ["sec", "hors-gel", "vent-max:30"]
    assert "climate" not in tasks.set_fields(repo.root, "T-0001", ["climate="])
    with pytest.raises(SystemExit):
        tasks.set_fields(repo.root, "T-0001", ["climate=beau"])
    plain, _ = common.read_md(tasks.new_task(repo.root, "p", "Sans météo"))
    assert "climate" not in plain and "location" not in plain


def test_best_slot_is_dry_and_frost_free(home):
    tasks.new_task(home.root, "p", "Traiter la terrasse", estimate=3, deadline="2026-11-29",
                   climate="sec,hors-gel", location="maison")
    plan = weather.plan_task(home.root, "T-0001")
    assert plan["status"] == "ok"
    assert plan["slot"]["date"] == "2026-11-26" and plan["slot"]["window"] == "08:00-11:00"  # thursday morning
    assert plan["slot"]["score"] >= 0.9 and plan["moves"] == []
    # wednesday is dry but freezing: never proposed for hors-gel, fine for « sec » alone
    assert all(a["date"] != "2026-11-25" for a in plan["alternatives"])
    only_dry = weather.parse_climate("sec")
    fc = weather.forecast_for(home.root, "maison")
    now = dt.datetime(2026, 11, 23, 8)
    assert weather.slot_score(fc, only_dry, dt.datetime(2026, 11, 25, 10), dt.datetime(2026, 11, 25, 13), now) >= 0.9


def test_placement_moves_a_task_already_planned_there(home):
    tasks.new_task(home.root, "p", "Appeler le comptable", estimate=3, deadline="2026-11-27",
                   scheduled_on="2026-11-26", scheduled_window="08:00-11:00")
    tasks.new_task(home.root, "p", "Traiter la terrasse", estimate=4, deadline="2026-11-29",
                   climate="sec,hors-gel", location="maison")
    plan = weather.plan_task(home.root, "T-0002")
    assert plan["slot"]["date"] == "2026-11-26" and plan["slot"]["window"] == "08:00-12:00"
    assert plan["moves"] == [{"task": "T-0001", "title": "Appeler le comptable",
                              "from": {"date": "2026-11-26", "window": "08:00-11:00"},
                              "to": {"date": "2026-11-26", "window": "12:00-15:00"}}]
    weather.apply_plan(home.root, plan)
    t = common.load_tasks(home.root)
    assert (str(t["T-0002"].meta["scheduled_on"]), t["T-0002"].meta["scheduled_window"]) == ("2026-11-26", "08:00-12:00")
    assert t["T-0001"].meta["scheduled_window"] == "12:00-15:00"
    assert "déplacée du 2026-11-26 08:00-11:00" in t["T-0001"].path.read_text()
    assert "placée jeudi 2026-11-26 08:00-12:00" in t["T-0002"].path.read_text()
    assert [e["type"] for e in logbook.since(home.root, 1)] == ["planned", "planned"]


def test_climate_task_is_never_displaced(home):
    tasks.new_task(home.root, "p", "Tailler la haie", estimate=5, deadline="2026-11-29", climate="sec",
                   location="maison", scheduled_on="2026-11-26", scheduled_window="08:00-13:00")
    tasks.new_task(home.root, "p", "Traiter la terrasse", estimate=3, deadline="2026-11-29",
                   climate="sec,hors-gel", location="maison")
    plan = weather.plan_task(home.root, "T-0002")
    assert plan["status"] == "risky" and plan["moves"] == []  # the only good morning is taken by another climate task
    assert not (plan["slot"]["date"] == "2026-11-26" and plan["slot"]["window"] < "13:00")


def test_place_pending_and_unplaceable_reasons(home):
    tasks.new_task(home.root, "p", "Sans lieu", climate="sec")
    tasks.new_task(home.root, "p", "Lieu inconnu", climate="sec", location="chalet")
    tasks.new_task(home.root, "p", "Trop long", estimate=12, climate="sec", location="maison")
    tasks.new_task(home.root, "p", "OK", estimate=2, climate="sec", location="maison", deadline="2026-11-29")
    assert weather.pending_ids(home.root) == ["T-0001", "T-0002", "T-0003", "T-0004"]
    status = {p["task"]: p["status"] for p in weather.place(home.root, weather.pending_ids(home.root), apply=True)}
    assert status == {"T-0001": "no-location", "T-0002": "unknown-place", "T-0003": "too-long", "T-0004": "ok"}
    assert weather.pending_ids(home.root) == ["T-0001", "T-0002", "T-0003"]


def test_beyond_forecast_is_left_for_later(home):
    tasks.new_task(home.root, "p", "Plus tard", climate="sec", location="maison", deadline="2026-12-20")
    assert weather.plan_task(home.root, "T-0001", d_from="2026-12-10")["status"] == "beyond-forecast"


def test_check_flags_and_replaces_a_slot_that_turned_bad(home):
    tasks.new_task(home.root, "p", "Traiter la terrasse", estimate=2, deadline="2026-11-29", climate="sec,hors-gel",
                   location="maison", scheduled_on="2026-11-24", scheduled_window="10:00-12:00")  # rainy tuesday
    res = weather.check(home.root)
    assert res["placed"][0]["risky"] and res["placed"][0]["score"] < 0.2
    res = weather.check(home.root, apply=True)
    assert res["replaced"][0]["to"]["date"] == "2026-11-26"
    assert str(common.load_tasks(home.root)["T-0001"].meta["scheduled_on"]) == "2026-11-26"


def test_today_sheet_shows_climate_tasks(home):
    tasks.new_task(home.root, "p", "Traiter la terrasse", climate="sec,hors-gel", location="maison")
    tasks.new_task(home.root, "p", "Vernir", climate="sec", location="maison",
                   scheduled_on="2026-11-24", scheduled_window="10:00-12:00")
    sheet = today.render(today.facts(home.root))
    assert "## Météo (tâches à contrainte climat)" in sheet
    assert "à placer : T-0001" in sheet and "⚠ météo défavorable : T-0002" in sheet


def test_forecast_failure_never_breaks_today(home, monkeypatch):
    monkeypatch.setenv("DOPPEL_WEATHER_FILE", str(home.root / "missing.json"))
    tasks.new_task(home.root, "p", "Vernir", climate="sec", location="maison",
                   scheduled_on="2026-11-24", scheduled_window="10:00-12:00")
    with pytest.raises(FileNotFoundError):
        weather.forecast_for(home.root, "maison")
    monkeypatch.setattr(weather, "fetch_raw", lambda *a: (_ for _ in ()).throw(SystemExit("forecast unavailable (quota)")))
    assert "prévision indisponible" in today.render(today.facts(home.root))


def test_no_network_without_climate_tasks(repo, monkeypatch):
    monkeypatch.setattr(weather, "fetch_raw", lambda *a: pytest.fail("network used"))
    tasks.new_task(repo.root, "p", "Normal")
    assert today.facts(repo.root)["climate"] == {}


def test_place_add_rounds_coordinates(repo):
    e = weather.place_add(repo.root, "maison", lat=50.466912, lon=4.867461, label="Maison")
    assert e == {"label": "Maison", "lat": 50.47, "lon": 4.87}
    assert common.load_config(repo.root)["places"]["maison"]["lat"] == 50.47
    assert common.load_config(repo.root)["projects"] == {}
