"""Climate scenarios: a weather-constrained task lands where the conditions are the most likely, the slot it takes
is freed by moving what was planned there, and a slot that turned bad is re-placed."""
import json
import sys
from pathlib import Path

import common
import tasks
import weather

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # tests/ (synthetic forecast)
from weather_fixture import add_home, week_forecast  # noqa: E402


def _setup(doppel_root, monkeypatch):
    root = doppel_root("2026-11-23 08:00")  # monday of 2026-W48
    add_home(root)
    (root / "forecast.json").write_text(json.dumps(week_forecast()), encoding="utf-8")
    monkeypatch.setenv("DOPPEL_WEATHER_FILE", str(root / "forecast.json"))
    return root


def test_dry_frost_free_task_goes_to_the_only_favourable_morning_and_replans(doppel_root, monkeypatch):
    """« À faire à la maison cette semaine, il faut qu'il fasse sec et qu'il ne gèle pas » (≈ 3 h)."""
    root = _setup(doppel_root, monkeypatch)
    tasks.new_task(root, "p", "Réunion de chantier", estimate=2, deadline="2026-11-27",
                   scheduled_on="2026-11-26", scheduled_window="09:00-11:00")
    tasks.new_task(root, "p", "Démousser la toiture", estimate=3, deadline="2026-11-29",
                   climate="sec,hors-gel", location="maison")
    plans = weather.place(root, weather.pending_ids(root), apply=True)
    assert plans[0]["status"] == "ok" and plans[0]["slot"]["score"] >= 0.6
    t = common.load_tasks(root)
    assert (str(t["T-0002"].meta["scheduled_on"]), t["T-0002"].meta["scheduled_window"]) == ("2026-11-26", "08:00-11:00")
    moved = (str(t["T-0001"].meta["scheduled_on"]), t["T-0001"].meta["scheduled_window"])
    assert moved != ("2026-11-26", "09:00-11:00") and moved[0] <= "2026-11-27"  # moved, deadline kept
    assert "open-meteo:" in t["T-0002"].path.read_text()  # placement is traceable


def test_risky_slot_is_replaced_by_the_daily_check(doppel_root, monkeypatch):
    root = _setup(doppel_root, monkeypatch)
    tasks.new_task(root, "p", "Peindre le portail", estimate=2, deadline="2026-11-29", climate="sec,hors-gel",
                   location="maison", scheduled_on="2026-11-25", scheduled_window="10:00-12:00")  # freezing wednesday
    res = weather.check(root, apply=True)
    assert res["replaced"] and res["replaced"][0]["to"]["date"] == "2026-11-26"
