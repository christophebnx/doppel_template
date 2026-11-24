"""Weather-constrained tasks: forecast, best slot, placement and re-check (task fields `climate` + `location`).

A task may carry `climate: [sec, hors-gel]` (conditions it needs) and `location: <place slug>` (where it happens,
declared in config.yaml: places). This script finds, between today and the task's deadline, the slot where those
conditions are the most likely, and plans it — moving, if needed, a task already scheduled at that moment.

  weather.py places                                   configured places
  weather.py place-add maison --query "Namur"         geocode (Open-Meteo) → config.yaml: places (coords rounded)
  weather.py place-add maison --lat 50.47 --lon 4.87 [--label "Maison"]
  weather.py forecast maison [--days 7] [--json]      daily summary (rain probability, min/max temperature, gusts)
  weather.py best --task T-0001 [--from D] [--to D] [--top 5] [--json]
  weather.py best --place maison --climate sec,hors-gel --hours 3 [--from D] [--to D]
  weather.py place T-0001 [T-0002 …] | --pending [--apply] [--json]
                                                      choose the slot (+ moves of conflicting tasks); --apply writes
                                                      scheduled_on/scheduled_window, progression lines and log lines
  weather.py check [--apply] [--json]                 climate tasks: unplaced, placed and still favourable, placed and
                                                      now risky; --apply re-places the risky ones when a better slot exists

Climate tokens (task field `climate`, comma list):
  sec            no rain during the slot              sec-avant:6h   …and none during the 6 h before (ground dry)
  hors-gel       temperature ≥ climate.frost_c (1 °C)  temp-min:5 / temp-max:28   temperature bounds (°C)
  vent-max:40    gusts ≤ 40 km/h                       jour           daylight only

Score of a slot = probability that every condition holds, taken at the worst hour of the slot (conservative):
per hour, P(dry) = 1 − precipitation_probability, temperatures and gusts through a normal law whose spread grows
with the lead time. Numbers come from here, never from the LLM.

Forecast: Open-Meteo (free, no key, ≤ 16 days). Only the place's rounded coordinates are sent. Cached 3 h in
.cache/weather/ (git-ignored). Tests/replays: $DOPPEL_WEATHER_FILE = a JSON in the Open-Meteo response format.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import re
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from common import (CLOSED_STATUSES, DAY_FR, day_index, get_root, load_config, load_tasks, now as now_fn, parse_date,
                    read_md, write_config_block, write_md)

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
HOURLY_VARS = "temperature_2m,precipitation_probability,precipitation,wind_gusts_10m,is_day"
CACHE_TTL_H = 3
COORD_DECIMALS = 2  # ≈ 1 km: enough for a forecast, nothing more precise leaves the repo

DEFAULTS = {
    "work_hours": "08:00-18:00",
    "work_days": ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"],
    "min_score": 0.6,
    "default_duration_h": 2,
    "step_min": 30,
    "frost_c": 1.0,
    "horizon_days": 7,  # search range when the task has no deadline
}
TOKEN_RE = re.compile(r"^(sec|hors-gel|jour|sec-avant:(\d+)h?|temp-min:(-?\d+(?:\.\d+)?)|temp-max:(-?\d+(?:\.\d+)?)"
                      r"|vent-max:(\d+(?:\.\d+)?))$")
NOT_PLANNABLE = CLOSED_STATUSES + ("waiting",)


# --------------------------------------------------------------------------- config & constraints


def climate_config(root: Path) -> dict:
    cfg = load_config(root)
    return {**DEFAULTS, **(cfg.get("climate") or {})}


def places(root: Path) -> dict:
    return load_config(root).get("places") or {}


@dataclass
class Constraints:
    dry: bool = False
    dry_before_h: int = 0
    temp_min: float | None = None
    temp_max: float | None = None
    gust_max: float | None = None
    daylight: bool = False
    tokens: list = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not self.tokens


def parse_climate(value, frost_c: float = DEFAULTS["frost_c"]) -> Constraints:
    """'sec,hors-gel' or ['sec', 'hors-gel'] → Constraints. Unknown token → SystemExit (triage raises a question)."""
    tokens = value if isinstance(value, list) else [t for t in str(value or "").split(",")]
    c = Constraints()
    for raw in tokens:
        tok = str(raw).strip().lower()
        if not tok:
            continue
        m = TOKEN_RE.match(tok)
        if not m:
            raise SystemExit(f"unknown climate token '{raw}' (sec, sec-avant:6h, hors-gel, temp-min:5, temp-max:28, "
                             f"vent-max:40, jour)")
        c.tokens.append(tok)
        if tok == "sec":
            c.dry = True
        elif tok.startswith("sec-avant"):
            c.dry, c.dry_before_h = True, max(c.dry_before_h, int(m.group(2)))
        elif tok == "hors-gel":
            c.temp_min = max(c.temp_min if c.temp_min is not None else -99, frost_c)
        elif tok.startswith("temp-min"):
            c.temp_min = max(c.temp_min if c.temp_min is not None else -99, float(m.group(3)))
        elif tok.startswith("temp-max"):
            c.temp_max = min(c.temp_max if c.temp_max is not None else 99, float(m.group(4)))
        elif tok.startswith("vent-max"):
            c.gust_max = min(c.gust_max if c.gust_max is not None else 999, float(m.group(5)))
        elif tok == "jour":
            c.daylight = True
    return c


# --------------------------------------------------------------------------- forecast


def _fetch_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "doppel-weather/1.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def _round(x: float) -> float:
    return round(float(x), COORD_DECIMALS)


def fetch_raw(root: Path, lat: float, lon: float) -> tuple[dict, str]:
    """Open-Meteo hourly response + fetch time ('YYYY-MM-DD HH:MM'). $DOPPEL_WEATHER_FILE overrides (tests)."""
    cfg = load_config(root)
    now = now_fn(cfg)
    fixture = os.environ.get("DOPPEL_WEATHER_FILE")
    if fixture:
        return json.loads(Path(fixture).read_text(encoding="utf-8")), now.strftime("%Y-%m-%d %H:%M")
    lat, lon = _round(lat), _round(lon)
    cache = root / ".cache" / "weather" / f"{lat}_{lon}.json"
    if cache.exists():
        try:
            c = json.loads(cache.read_text(encoding="utf-8"))
            if now - dt.datetime.fromisoformat(c["fetched_at"]) < dt.timedelta(hours=CACHE_TTL_H):
                return c["data"], c["fetched_at"]
        except Exception:  # corrupt cache: refetch
            pass
    q = urllib.parse.urlencode({"latitude": lat, "longitude": lon, "hourly": HOURLY_VARS,
                                "timezone": cfg["timezone"], "forecast_days": 16})
    try:
        data = _fetch_json(f"{FORECAST_URL}?{q}")
    except Exception as exc:  # network, quota…: the caller degrades gracefully
        raise SystemExit(f"forecast unavailable ({type(exc).__name__}: {exc})")
    if data.get("error"):
        raise SystemExit(f"forecast unavailable ({data.get('reason')})")
    fetched = now.strftime("%Y-%m-%d %H:%M")
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({"fetched_at": fetched, "data": data}), encoding="utf-8")
    return data, fetched


def hourly(data: dict) -> dict[dt.datetime, dict]:
    h = data["hourly"]
    n = len(h["time"])

    def col(name):
        return h.get(name) or [None] * n

    out = {}
    for t, temp, pp, pr, gust, day in zip(h["time"], col("temperature_2m"), col("precipitation_probability"),
                                          col("precipitation"), col("wind_gusts_10m"), col("is_day")):
        out[dt.datetime.fromisoformat(t)] = {"t": temp, "pp": pp, "pr": pr, "gust": gust, "day": day}
    return out


@dataclass
class Forecast:
    hours: dict
    fetched_at: str
    place: str

    @property
    def end(self) -> dt.datetime:
        return max(self.hours) + dt.timedelta(hours=1)


def forecast_for(root: Path, place: str) -> Forecast:
    p = places(root).get(place)
    if not p:
        raise SystemExit(f"unknown place '{place}': add it with `weather.py place-add {place} --query \"<commune>\"`")
    data, fetched = fetch_raw(root, p["lat"], p["lon"])
    return Forecast(hourly(data), fetched, place)


# --------------------------------------------------------------------------- scoring


def _phi(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def p_dry(h: dict) -> float:
    pp = h.get("pp")
    if pp is None:  # no probability in the model: fall back on the forecast amount
        pp = 70 if (h.get("pr") or 0) >= 0.1 else 15
    return max(0.0, 1 - float(pp) / 100)


def hour_prob(h: dict, c: Constraints, lead_days: float, during: bool = True) -> float:
    """Probability that the constraints hold during this hour. `during=False`: hour before the slot (dryness only)."""
    if not during:
        return p_dry(h)
    p = 1.0
    sig_t = 1.0 + 0.3 * max(lead_days, 0)
    sig_w = 6.0 + 1.5 * max(lead_days, 0)
    if c.dry:
        p *= p_dry(h)
    if c.temp_min is not None:
        p *= _phi((float(h["t"]) - c.temp_min) / sig_t) if h.get("t") is not None else 0.5
    if c.temp_max is not None:
        p *= _phi((c.temp_max - float(h["t"])) / sig_t) if h.get("t") is not None else 0.5
    if c.gust_max is not None:
        p *= _phi((c.gust_max - float(h["gust"])) / sig_w) if h.get("gust") is not None else 0.5
    if c.daylight and h.get("day") is not None and not h["day"]:
        p = 0.0
    return p


def _hours_between(start: dt.datetime, end: dt.datetime) -> list[dt.datetime]:
    h = start.replace(minute=0)
    out = []
    while h < end:
        out.append(h)
        h += dt.timedelta(hours=1)
    return out


def slot_score(fc: Forecast, c: Constraints, start: dt.datetime, end: dt.datetime, now: dt.datetime) -> float | None:
    """Worst-hour probability over the slot (and the dry-before hours). None if the forecast does not cover it."""
    probs = []
    for h in _hours_between(start, end):
        if h not in fc.hours:
            return None
        probs.append(hour_prob(fc.hours[h], c, (h - now).total_seconds() / 86400))
    if c.dry_before_h:
        for h in _hours_between(start - dt.timedelta(hours=c.dry_before_h), start):
            if h in fc.hours:  # past hours may be missing: only the covered ones count
                probs.append(hour_prob(fc.hours[h], c, 0, during=False))
    return round(min(probs), 2) if probs else None


def slot_weather(fc: Forecast, start: dt.datetime, end: dt.datetime) -> dict:
    hs = [fc.hours[h] for h in _hours_between(start, end) if h in fc.hours]
    temps = [h["t"] for h in hs if h.get("t") is not None]
    return {"rain_prob_max": max((h.get("pp") or 0 for h in hs), default=None),
            "rain_mm": round(sum(h.get("pr") or 0 for h in hs), 1),
            "t_min": min(temps, default=None), "t_max": max(temps, default=None),
            "gust_max": max((h.get("gust") or 0 for h in hs), default=None)}


# --------------------------------------------------------------------------- slots & agenda


def _hm(s: str) -> dt.time:
    return dt.time.fromisoformat(s)


def parse_window(day: dt.date, window: str) -> tuple[dt.datetime, dt.datetime]:
    a, b = window.split("-")
    return dt.datetime.combine(day, _hm(a)), dt.datetime.combine(day, _hm(b))


def fmt_window(start: dt.datetime, end: dt.datetime) -> str:
    return f"{start:%H:%M}-{end:%H:%M}"


def _ceil_step(t: dt.datetime, step: int) -> dt.datetime:
    m = t.hour * 60 + t.minute
    m2 = -(-m // step) * step
    return dt.datetime.combine(t.date(), dt.time()) + dt.timedelta(minutes=m2)


def work_days(ccfg: dict) -> set[int]:
    return {day_index(d) for d in ccfg["work_days"]}


def candidate_starts(day_from: dt.date, day_to: dt.date, minutes: int, ccfg: dict, now: dt.datetime):
    step = int(ccfg["step_min"])
    days = work_days(ccfg)
    d = day_from
    while d <= day_to:
        if d.weekday() in days:
            ws, we = parse_window(d, ccfg["work_hours"])
            s = max(ws, _ceil_step(now, step)) if d == now.date() else ws
            while s + dt.timedelta(minutes=minutes) <= we:
                yield s
                s += dt.timedelta(minutes=step)
        d += dt.timedelta(days=1)


def busy_slots(tasks: dict, exclude: set) -> list[tuple[dt.datetime, dt.datetime, str]]:
    """Time slots already taken by open tasks with a scheduled day AND window."""
    out = []
    for t in tasks.values():
        if t.id in exclude or t.status in NOT_PLANNABLE:
            continue
        d, w = parse_date(t.meta.get("scheduled_on")), t.meta.get("scheduled_window")
        if d and w:
            s, e = parse_window(d, str(w))
            out.append((s, e, t.id))
    return out


def _overlaps(s, e, busy):
    return [b for b in busy if s < b[1] and b[0] < e]


def duration_min(task, root: Path, ccfg: dict) -> int:
    corr = float(load_config(root)["capacity"]["estimate_correction"]) or 1.0
    h = task.remaining_h(corr) if task.meta.get("estimate_h") else 0
    h = h or float(ccfg["default_duration_h"])
    return int(-(-round(h * 60) // int(ccfg["step_min"])) * int(ccfg["step_min"]))


def free_slot(root: Path, task, busy: list, ccfg: dict, now: dt.datetime, not_before: dt.date) -> tuple | None:
    """Earliest slot of the same length for a displaced task, from `not_before` until its deadline (or horizon)."""
    s0, e0 = parse_window(parse_date(task.meta["scheduled_on"]), str(task.meta["scheduled_window"]))
    minutes = int((e0 - s0).total_seconds() // 60)
    limit = parse_date(task.meta.get("deadline")) or not_before + dt.timedelta(days=int(ccfg["horizon_days"]))
    for s in candidate_starts(max(not_before, now.date()), limit, minutes, ccfg, now):
        e = s + dt.timedelta(minutes=minutes)
        if not _overlaps(s, e, busy):
            return s, e
    return None


# --------------------------------------------------------------------------- best slot / placement


def search_range(task_meta: dict, now: dt.datetime, ccfg: dict, d_from=None, d_to=None) -> tuple[dt.date, dt.date]:
    start = parse_date(d_from) or now.date()
    end = parse_date(d_to) or parse_date(task_meta.get("deadline")) or start + dt.timedelta(days=int(ccfg["horizon_days"]) - 1)
    return start, end


def rank_slots(fc: Forecast, c: Constraints, minutes: int, day_from, day_to, ccfg, now) -> list[dict]:
    out = []
    for s in candidate_starts(day_from, day_to, minutes, ccfg, now):
        e = s + dt.timedelta(minutes=minutes)
        if e > fc.end:
            break
        sc = slot_score(fc, c, s, e, now)
        if sc is not None:
            out.append({"start": s, "end": e, "score": sc})
    out.sort(key=lambda x: (-x["score"], x["start"]))
    return out


def _slot_out(x: dict, fc: Forecast | None = None) -> dict:
    d = {"date": str(x["start"].date()), "weekday": DAY_FR[x["start"].weekday()],
         "window": fmt_window(x["start"], x["end"]), "score": x["score"]}
    if fc:
        d["weather"] = slot_weather(fc, x["start"], x["end"])
    return d


def plan_task(root: Path, tid: str, *, d_from=None, d_to=None, tasks: dict | None = None,
              extra_busy: list | None = None) -> dict:
    """Best feasible slot for one climate task: weather score first (by 0.05 steps), then fewest moves, then earliest.
    A conflicting task is moved to its earliest free slot before its deadline; tasks with a climate constraint are
    never moved (they were placed for the weather). Returns the plan (nothing written)."""
    ccfg = climate_config(root)
    now = now_fn(load_config(root))
    tasks = tasks if tasks is not None else load_tasks(root)
    t = tasks.get(tid)
    if not t:
        raise SystemExit(f"{tid} not found")
    c = parse_climate(t.meta.get("climate"), float(ccfg["frost_c"]))
    place = t.meta.get("location")
    base = {"task": tid, "title": t.meta.get("title"), "project": t.meta.get("project"), "place": place,
            "climate": c.tokens}
    if c.empty:
        return {**base, "status": "no-climate", "reason": "la tâche n'a pas de contrainte climat"}
    if not place:
        return {**base, "status": "no-location", "reason": "lieu inconnu : renseigner location (config.yaml: places)"}
    if place not in places(root):
        return {**base, "status": "unknown-place", "reason": f"lieu « {place} » absent de config.yaml: places"}
    minutes = duration_min(t, root, ccfg)
    ws, we = parse_window(now.date(), ccfg["work_hours"])
    if minutes > (we - ws).total_seconds() / 60:
        return {**base, "status": "too-long", "reason": f"{minutes / 60:g} h > plage {ccfg['work_hours']} : découper la tâche"}
    day_from, day_to = search_range(t.meta, now, ccfg, d_from, d_to)
    if day_to < day_from:
        return {**base, "status": "past-deadline", "reason": f"échéance {day_to} dépassée"}
    fc = forecast_for(root, place)
    ranked = rank_slots(fc, c, minutes, day_from, day_to, ccfg, now)
    base.update(duration_h=round(minutes / 60, 2), range=[str(day_from), str(day_to)], forecast_at=fc.fetched_at)
    if not ranked:
        return {**base, "status": "beyond-forecast",
                "reason": f"aucune prévision entre {day_from} et {day_to} (horizon {fc.end:%Y-%m-%d}) : replacer plus tard"}
    busy = busy_slots(tasks, {tid}) + list(extra_busy or [])
    feasible = []
    for x in ranked:
        conflicts = _overlaps(x["start"], x["end"], busy)
        moves, ok = [], True
        taken = [b for b in busy if b not in conflicts] + [(x["start"], x["end"], tid)]
        for (_, _, cid) in conflicts:
            ct = tasks[cid]
            if ct.meta.get("climate"):
                ok = False
                break
            slot = free_slot(root, ct, taken, ccfg, now, x["start"].date())
            if not slot:
                ok = False
                break
            taken.append((slot[0], slot[1], cid))
            moves.append({"task": cid, "title": ct.meta.get("title"),
                          "from": {"date": str(ct.meta["scheduled_on"]), "window": str(ct.meta["scheduled_window"])},
                          "to": {"date": str(slot[0].date()), "window": fmt_window(*slot)}})
        if ok:
            feasible.append({**x, "moves": moves})
    if not feasible:
        return {**base, "status": "no-slot", "reason": "tous les créneaux favorables sont pris par des tâches non déplaçables"}
    feasible.sort(key=lambda x: (-int(x["score"] * 20 + 1e-9), len(x["moves"]), x["start"]))
    best = feasible[0]
    same_day = [o.id for o in tasks.values() if o.id != tid and o.status not in NOT_PLANNABLE
                and parse_date(o.meta.get("scheduled_on")) == best["start"].date() and not o.meta.get("scheduled_window")]
    return {**base, "status": "risky" if best["score"] < float(ccfg["min_score"]) else "ok",
            "slot": _slot_out(best, fc), "moves": best["moves"], "same_day_unwindowed": same_day,
            "alternatives": [_slot_out(x) for x in feasible[1:4]], "min_score": float(ccfg["min_score"])}


def _append_progress(path: Path, line: str) -> None:
    meta, body = read_md(path)
    if "## Progression" not in body:
        body = body.rstrip("\n") + "\n\n## Progression\n"
    write_md(path, meta, body.rstrip("\n") + "\n" + line + "\n")


def apply_plan(root: Path, plan: dict) -> list[str]:
    """Write a plan: scheduled_on/window of the task and of the moved tasks, progression lines, log lines."""
    import logbook
    from tasks import set_fields
    if plan.get("status") not in ("ok", "risky"):
        return []
    today = now_fn(load_config(root)).date()
    source = f"open-meteo:{plan['forecast_at']}"
    s, tid = plan["slot"], plan["task"]
    changed = []
    for mv in plan["moves"]:
        set_fields(root, mv["task"], [f"scheduled_on={mv['to']['date']}", f"scheduled_window={mv['to']['window']}"])
        _append_progress(root / "tasks" / f"{mv['task']}.md",
                         f"- {today} · déplacée du {mv['from']['date']} {mv['from']['window']} au {mv['to']['date']} "
                         f"{mv['to']['window']} pour {tid} (créneau météo) · {source}")
        proj = load_tasks(root)[mv["task"]].meta.get("project") or "-"
        logbook.add(root, proj, "planned", f"{mv['task']} déplacée au {mv['to']['date']} {mv['to']['window']} "
                    f"(créneau météo pris par {tid})", source)
        changed.append(mv["task"])
    set_fields(root, tid, [f"scheduled_on={s['date']}", f"scheduled_window={s['window']}"])
    risk = " — risqué, aucun créneau sûr" if plan["status"] == "risky" else ""
    w = s.get("weather") or {}
    wtxt = f"pluie ≤ {w.get('rain_prob_max')} %, {w.get('t_min')}…{w.get('t_max')} °C" if w else ""
    _append_progress(root / "tasks" / f"{tid}.md",
                     f"- {today} · placée {s['weekday']} {s['date']} {s['window']} ({', '.join(plan['climate'])} : "
                     f"{round(s['score'] * 100)} % de chances{risk}; {wtxt}) · {source}")
    logbook.add(root, plan.get("project") or "-", "planned",
                f"{tid} placée {s['weekday']} {s['date']} {s['window']} — météo favorable à {round(s['score'] * 100)} %{risk}",
                source)
    return [tid, *changed]


def pending_ids(root: Path) -> list[str]:
    """Open, plannable climate tasks without a (future) scheduled day."""
    today = now_fn(load_config(root)).date()
    out = []
    for t in load_tasks(root).values():
        if t.status in NOT_PLANNABLE or not t.meta.get("climate"):
            continue
        d = parse_date(t.meta.get("scheduled_on"))
        if not d or d < today:
            out.append(t.id)
    return out


def place(root: Path, ids: list[str], apply: bool = False) -> list[dict]:
    """Place several tasks one after the other (each placement is busy for the next). P1 first, then deadline."""
    tasks = load_tasks(root)
    ids = sorted(ids, key=lambda i: (str(tasks[i].meta.get("priority") or "P9") if i in tasks else "P9",
                                     str(tasks[i].meta.get("deadline") or "9999") if i in tasks else "9999", i))
    plans = []
    for tid in ids:
        try:
            plan = plan_task(root, tid, tasks=tasks)
        except SystemExit as e:  # forecast unavailable for this place: the others are still placed
            plan = {"task": tid, "title": tasks[tid].meta.get("title") if tid in tasks else None,
                    "status": "forecast-unavailable", "reason": str(e)}
        plans.append(plan)
        if apply and plan.get("status") in ("ok", "risky"):
            apply_plan(root, plan)
            tasks = load_tasks(root)
        elif plan.get("status") in ("ok", "risky"):  # dry run: simulate so the next task sees this slot as taken
            for mv in plan["moves"]:
                tasks[mv["task"]].meta.update(scheduled_on=mv["to"]["date"], scheduled_window=mv["to"]["window"])
            tasks[tid].meta.update(scheduled_on=plan["slot"]["date"], scheduled_window=plan["slot"]["window"])
    return plans


def check(root: Path, apply: bool = False) -> dict:
    """Climate tasks: to place, placed (score of the current slot with the latest forecast), re-placed (--apply)."""
    ccfg = climate_config(root)
    now = now_fn(load_config(root))
    min_score = float(ccfg["min_score"])
    out = {"to_place": [], "placed": [], "replaced": [], "errors": []}
    pend = set(pending_ids(root))
    for t in load_tasks(root).values():
        if t.status in NOT_PLANNABLE or not t.meta.get("climate"):
            continue
        item = {"task": t.id, "title": t.meta.get("title"), "place": t.meta.get("location"),
                "climate": parse_climate(t.meta.get("climate"), float(ccfg["frost_c"])).tokens}
        if t.id in pend:
            out["to_place"].append(item)
            continue
        d, w = parse_date(t.meta.get("scheduled_on")), t.meta.get("scheduled_window")
        item.update(date=str(d), window=w)
        if not w or t.meta.get("location") not in places(root):
            item["score"] = None
            out["placed"].append(item)
            continue
        try:
            fc = forecast_for(root, t.meta["location"])
        except SystemExit as e:
            out["errors"].append(f"{t.id}: {e}")
            continue
        s, e = parse_window(d, str(w))
        item["score"] = slot_score(fc, parse_climate(t.meta["climate"], float(ccfg["frost_c"])), s, e, now)
        item["risky"] = item["score"] is not None and item["score"] < min_score
        out["placed"].append(item)
    if apply:
        for item in [i for i in out["placed"] if i.get("risky")]:
            try:
                plan = plan_task(root, item["task"])
            except SystemExit as e:
                out["errors"].append(f"{item['task']}: {e}")
                continue
            if plan.get("status") == "ok" and plan["slot"]["score"] >= item["score"] + 0.1:
                apply_plan(root, plan)
                out["replaced"].append({"task": item["task"], "from": {"date": item["date"], "window": item["window"],
                                                                         "score": item["score"]},
                                        "to": plan["slot"], "moves": plan["moves"]})
                item.update(date=plan["slot"]["date"], window=plan["slot"]["window"], score=plan["slot"]["score"],
                            risky=False)
    return out


# --------------------------------------------------------------------------- places


def geocode(query: str) -> dict:
    q = urllib.parse.urlencode({"name": query, "count": 1, "language": "fr", "format": "json"})
    try:
        res = (_fetch_json(f"{GEOCODE_URL}?{q}").get("results") or [])
    except Exception as exc:
        raise SystemExit(f"geocoding unavailable ({type(exc).__name__})")
    if not res:
        raise SystemExit(f"no place found for '{query}'")
    r = res[0]
    label = ", ".join(x for x in (r.get("name"), r.get("admin1"), r.get("country_code")) if x)
    return {"label": label, "lat": r["latitude"], "lon": r["longitude"]}


def place_add(root: Path, slug: str, *, query=None, lat=None, lon=None, label=None) -> dict:
    if lat is None or lon is None:
        if not query:
            raise SystemExit("give --query or --lat/--lon")
        g = geocode(query)
        lat, lon, label = g["lat"], g["lon"], label or g["label"]
    entry = {"label": label or slug, "lat": _round(lat), "lon": _round(lon)}
    cur = dict(places(root))
    cur[slug] = entry
    write_config_block(root, "places", cur)
    return entry


# --------------------------------------------------------------------------- cli


def _daily(fc: Forecast, days: int) -> list[dict]:
    by = {}
    for h, v in sorted(fc.hours.items()):
        by.setdefault(h.date(), []).append(v)
    out = []
    for d, vs in list(by.items())[:days]:
        temps = [v["t"] for v in vs if v.get("t") is not None]
        day_hours = [v for v in vs if v.get("day")] or vs
        out.append({"date": str(d), "weekday": DAY_FR[d.weekday()],
                    "rain_prob_max_day": max((v.get("pp") or 0 for v in day_hours), default=None),
                    "rain_mm": round(sum(v.get("pr") or 0 for v in vs), 1),
                    "t_min": min(temps, default=None), "t_max": max(temps, default=None),
                    "gust_max": max((v.get("gust") or 0 for v in vs), default=None)})
    return out


def _plan_line(p: dict) -> str:
    if p["status"] not in ("ok", "risky"):
        return f"{p['task']} {p.get('title')} — non placée : {p['reason']}"
    s = p["slot"]
    line = f"{p['task']} {p.get('title')} → {s['weekday']} {s['date']} {s['window']} · {round(s['score'] * 100)} %"
    if p["status"] == "risky":
        line += " ⚠ risqué"
    for mv in p["moves"]:
        line += f"\n  ↪ {mv['task']} {mv.get('title')} : {mv['from']['date']} {mv['from']['window']} → {mv['to']['date']} {mv['to']['window']}"
    if p.get("same_day_unwindowed"):
        line += f"\n  · même jour (sans heure) : {', '.join(p['same_day_unwindowed'])}"
    if p.get("alternatives"):
        line += "\n  alternatives : " + "; ".join(f"{a['weekday']} {a['date']} {a['window']} {round(a['score'] * 100)} %"
                                                    for a in p["alternatives"])
    return line


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("places")
    pa = sub.add_parser("place-add"); pa.add_argument("slug"); pa.add_argument("--query"); pa.add_argument("--label")
    pa.add_argument("--lat", type=float); pa.add_argument("--lon", type=float)
    fo = sub.add_parser("forecast"); fo.add_argument("place"); fo.add_argument("--days", type=int, default=7)
    fo.add_argument("--json", action="store_true")
    be = sub.add_parser("best"); be.add_argument("--task"); be.add_argument("--place"); be.add_argument("--climate")
    be.add_argument("--hours", type=float); be.add_argument("--from", dest="d_from"); be.add_argument("--to", dest="d_to")
    be.add_argument("--top", type=int, default=5); be.add_argument("--json", action="store_true")
    pl = sub.add_parser("place"); pl.add_argument("ids", nargs="*"); pl.add_argument("--pending", action="store_true")
    pl.add_argument("--apply", action="store_true"); pl.add_argument("--json", action="store_true")
    ch = sub.add_parser("check"); ch.add_argument("--apply", action="store_true"); ch.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    root = get_root(args.root)

    if args.cmd == "places":
        for slug, p in places(root).items():
            print(f"{slug} · {p.get('label')} · {p.get('lat')}, {p.get('lon')}")
        if not places(root):
            print("aucun lieu (weather.py place-add <slug> --query \"<commune>\")")
    elif args.cmd == "place-add":
        e = place_add(root, args.slug, query=args.query, lat=args.lat, lon=args.lon, label=args.label)
        print(f"{args.slug} · {e['label']} · {e['lat']}, {e['lon']}")
    elif args.cmd == "forecast":
        fc = forecast_for(root, args.place)
        rows = _daily(fc, args.days)
        if args.json:
            print(json.dumps({"place": args.place, "fetched_at": fc.fetched_at, "days": rows}, ensure_ascii=False, indent=1))
        else:
            print(f"{args.place} — prévision du {fc.fetched_at}")
            for r in rows:
                print(f"{r['weekday']} {r['date']} · pluie {r['rain_prob_max_day']} % ({r['rain_mm']} mm) · "
                      f"{r['t_min']}…{r['t_max']} °C · rafales {r['gust_max']} km/h")
    elif args.cmd == "best":
        ccfg = climate_config(root)
        now = now_fn(load_config(root))
        if args.task:
            t = load_tasks(root).get(args.task) or sys.exit(f"{args.task} not found")
            c = parse_climate(t.meta.get("climate"), float(ccfg["frost_c"]))
            place_slug, minutes, meta = t.meta.get("location"), duration_min(t, root, ccfg), t.meta
        else:
            if not (args.place and args.climate):
                raise SystemExit("give --task, or --place and --climate")
            c = parse_climate(args.climate, float(ccfg["frost_c"]))
            place_slug, meta = args.place, {}
            step = int(ccfg["step_min"])
            minutes = int(-(-round((args.hours or float(ccfg["default_duration_h"])) * 60) // step) * step)
        fc = forecast_for(root, place_slug)
        d0, d1 = search_range(meta, now, ccfg, args.d_from, args.d_to)
        ranked = [_slot_out(x, fc) for x in rank_slots(fc, c, minutes, d0, d1, ccfg, now)[: args.top]]
        if args.json:
            print(json.dumps({"place": place_slug, "climate": c.tokens, "forecast_at": fc.fetched_at,
                              "slots": ranked}, ensure_ascii=False, indent=1))
        else:
            for s in ranked:
                w = s["weather"]
                print(f"{s['weekday']} {s['date']} {s['window']} · {round(s['score'] * 100)} % · pluie ≤ "
                      f"{w['rain_prob_max']} % · {w['t_min']}…{w['t_max']} °C")
            print("" if ranked else "aucun créneau dans l'horizon de prévision")
    elif args.cmd == "place":
        ids = args.ids or (pending_ids(root) if args.pending else [])
        plans = place(root, ids, apply=args.apply)
        if args.json:
            print(json.dumps(plans, ensure_ascii=False, indent=1))
        else:
            for p in plans:
                print(_plan_line(p))
            print(("appliqué" if args.apply else "simulation (--apply pour écrire)") if plans else "rien à placer")
    elif args.cmd == "check":
        res = check(root, apply=args.apply)
        if args.json:
            print(json.dumps(res, ensure_ascii=False, indent=1))
        else:
            for i in res["to_place"]:
                print(f"à placer : {i['task']} {i['title']} ({', '.join(i['climate'])})")
            for i in res["placed"]:
                sc = "?" if i.get("score") is None else f"{round(i['score'] * 100)} %"
                print(f"{'⚠ ' if i.get('risky') else ''}{i['task']} {i['date']} {i.get('window') or ''} · {sc}")
            for r in res["replaced"]:
                print(f"replacée : {r['task']} {r['from']['date']} → {r['to']['date']} {r['to']['window']}")
            for e in res["errors"]:
                print(f"erreur : {e}")
    return 0


if __name__ == "__main__":
    from common import run_main
    sys.exit(run_main(main, __file__))
