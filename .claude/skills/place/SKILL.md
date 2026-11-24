---
name: place
description: Plan weather-constrained tasks (task fields `climate` + `location`) — fetch the forecast of the task's place, choose between today and the deadline the slot where the conditions (dry, frost-free, wind, daylight…) are the most likely, move a task already planned at that moment if needed, write scheduled_on/scheduled_window, progression and log lines. Called by /ingest and /today; also manual (« place T-0012 », « où caser la terrasse cette semaine ? »).
argument-hint: "[T-id …] [--dry]  (default: every climate task not yet placed)"
---

# /place

> **Run & retro** (CLAUDE.md § Runs and retro): first `uv run scripts/signals.py run start --skill place --args "<arguments>"` (keep the `R-…`); last, the **retro** — emit a signal only if something really got in the way (missing file, contradictory instruction, ambiguity worked around, context limit, missing tool, script error; never « tout va bien ») — then `uv run scripts/signals.py run end --run R-… --outcome ok|error|partial [--signals S-…]`.

## Arguments
Task ids to (re)place; default all open climate tasks without a future `scheduled_on` (`weather.py place --pending`).
`--dry`: show the plan, write nothing.

## Steps
1. `git pull --rebase origin main`; `uv run scripts/dates.py now`.
2. Completeness of each task (read only its frontmatter): `climate` set; `location` set and present in
   `uv run scripts/weather.py places`; a range — `deadline` (« cette semaine » = last day of the week from
   `dates.py week`) or the default `climate.horizon_days`. A missing place the owner named (« à la maison ») →
   `weather.py place-add <slug> --query "<commune>"` only if the commune is known from the repo (brain, earlier
   answer); otherwise `clarify` + question « Où se trouve <lieu> (commune) ? » and skip the task.
3. Simulate: `uv run scripts/weather.py place <ids> --json` (or `--pending`). The script does all the numbers: the
   score is the probability that every condition holds at the worst hour of the slot; ties go to the slot that moves
   fewest tasks, then the earliest. A conflicting task is moved to its earliest free slot before its own deadline;
   a task that has a `climate` constraint is never moved.
4. Unless `--dry`: `uv run scripts/weather.py place <same ids> --apply`. It writes `scheduled_on`/`scheduled_window`
   of the placed and moved tasks, a `## Progression` line in each, and one `planned` log line per change (source
   `open-meteo:<forecast time>`).
5. Statuses that are not placed: `no-location` / `unknown-place` → question (step 2); `too-long` → question « découper
   T-… en sessions de ≤ <plage> ? »; `beyond-forecast` → nothing (the daily `/today` check places it once the forecast
   covers the range); `forecast-unavailable` → nothing, retried by the next `/today`; `no-slot` / `past-deadline` → question with the facts printed by the script. `risky` (best chance
   below `climate.min_score`) is placed anyway and said so — the owner asked for the most favourable moment, not a certainty.
6. `uv run scripts/index.py`; commit `doppel(place): <n> placées, <n> déplacées`; push.

## Agents
None: the placement is a script; the skill only completes missing facts and phrases questions.

## Reads / writes
Reads tasks, `config.yaml` (`climate`, `places`), the forecast (Open-Meteo, cached in `.cache/weather/`).
Writes task frontmatter + progression, `log/`, `questions.md`, `config.yaml: places` (via script).

## Output
```
Placement météo AAAA-MM-JJ (prévision HH:MM)
- T-0012 Démousser la toiture → jeudi 2026-11-26 08:00-11:00 · 91 % (sec, hors-gel; pluie ≤ 5 %, 8…8 °C)
  ↪ T-0007 Réunion de chantier : 2026-11-26 09:00-11:00 → 2026-11-26 11:00-13:00
- T-0015 Vernir le banc — non placée : prévision pas encore disponible pour 2026-12-10…12
```
Then the moved tasks, so the owner can object (`/done`, or a correction in conversation → `/wrap`).

## Unattended
Runs fully (called from /ingest and /today): never asks; missing facts become questions; moves are applied (the owner
asked doppel to replan around the weather) and listed in the commit body. Commit to `main`.
