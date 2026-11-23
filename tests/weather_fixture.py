"""Synthetic Open-Meteo forecasts for the tests (week 2026-W48, Mon 2026-11-23 .. Sun 2026-11-29)."""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

START = dt.date(2026, 11, 23)


def week_forecast(days: int = 7) -> dict:
    """Mon–Tue rain · Wed dry but freezing · Thu dry and mild 08:00–13:00 then rain · Fri–Sun rain."""
    times, temp, pp, pr, gust, day = [], [], [], [], [], []
    for i in range(days):
        d = START + dt.timedelta(days=i)
        for h in range(24):
            times.append(f"{d}T{h:02d}:00")
            wd = d.weekday()
            if wd == 2:  # wednesday: dry, -3 °C
                t, p = -3.0, 5
            elif wd == 3:  # thursday: mild; dry until 13:00, rain after
                t, p = 8.0, (5 if h < 13 else 80)
            else:
                t, p = 6.0, 85
            temp.append(t); pp.append(p); pr.append(1.2 if p > 50 else 0.0); gust.append(20.0)
            day.append(1 if 8 <= h < 17 else 0)
    return {"hourly": {"time": times, "temperature_2m": temp, "precipitation_probability": pp, "precipitation": pr,
                       "wind_gusts_10m": gust, "is_day": day}}


def install(root: Path, monkeypatch, data: dict | None = None) -> Path:
    path = root / "forecast.json"
    path.write_text(json.dumps(data or week_forecast()), encoding="utf-8")
    monkeypatch.setenv("DOPPEL_WEATHER_FILE", str(path))
    return path


def add_home(root: Path) -> None:
    import common
    common.write_config_block(root, "places", {"maison": {"label": "Maison", "lat": 50.47, "lon": 4.87}})
