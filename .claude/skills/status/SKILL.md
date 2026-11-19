---
name: status
description: Status report for an audience (default audiences externe, interne, equipe — adapt in templates/status.md) — done in the last N days, planned for the next N days, blockers, needs — written by the reporter agent into outbox/ for validation. Manual.
argument-hint: "[Nj] [externe|interne|equipe] [projet]   (default: 5j interne, all projects)"
---

# /status

> **Run & retro** (CLAUDE.md § Runs and retro): first `uv run scripts/signals.py run start --skill status --args "<arguments>"` (keep the `R-…`); last, the **retro** — emit a signal only if something really got in the way (missing file, contradictory instruction, ambiguity worked around, context limit, missing tool, script error; never « tout va bien ») — then `uv run scripts/signals.py run end --run R-… --outcome ok|error|partial [--signals S-…]`.

## Arguments
`Nj` (default 5), audience (default `interne`), project (required for `externe`; optional otherwise).

## Steps
1. `git pull --rebase origin main`; `uv run scripts/dates.py now --json` (today).
2. Gather (scripts only for dates/hours):
   - done: `uv run scripts/logbook.py since --days N [--project p]`;
   - planned: open tasks with a deadline or `scheduled_on` in the next N days (`tasks.py list --json`; window bounds via `dates.py shift`);
   - blockers: `tasks.py list --status blocked,clarify,waiting`; open questions for the project.
3. **reporter** agent writes `outbox/AAAA-MM-JJ_status-<audience>[-<p>].md` from `templates/status.md` (`state: draft`),
   applying the audience rules of the template (externe: one project, no internal information, nothing about other projects).
4. Brain: add a line in « Historique » of each covered project (`- date · status <audience> préparé (brouillon) · outbox/<file>`).
5. `uv run scripts/index.py`; commit `doppel(status): <audience> <Nj> [<p>]`; push.
6. Print the report body ready to copy, and remind that it is a draft in `outbox/`.

## Unattended
Not scheduled.
