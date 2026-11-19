---
name: today
description: Write today.md at the repo root — tasks in progress, fixed-day tasks, due dates and overdue, open P1, follow-ups due, open questions, deliverables to validate in outbox/, doppel's own changes (briefs to approve, merges, reverts), plus 1–3 focus lines. Readable in one minute. Scheduled daily at the end of the morning pass; also manual.
argument-hint: ""
---

# /today

> **Run & retro** (CLAUDE.md § Runs and retro): first `uv run scripts/signals.py run start --skill today --args "<arguments>"` (keep the `R-…`); last, the **retro** — emit a signal only if something really got in the way (missing file, contradictory instruction, ambiguity worked around, context limit, missing tool, script error; never « tout va bien ») — then `uv run scripts/signals.py run end --run R-… --outcome ok|error|partial [--signals S-…]`.

## Steps
1. `git pull --rebase origin main`.
2. `uv run scripts/today.py --write` — deterministic sections (never edit them by hand; re-run the script instead),
   including « doppel lui-même »: briefs to approve, PRs to arbitrate, changes merged since yesterday, reverts, kill switch.
3. **reporter**: replace the Focus placeholder with 1–3 lines — what matters today and why (e.g. « Rendre T-0012 :
   échéance demain », « Relancer jean-exemple : plan attendu depuis le 14/11 »). Use only facts present in the sheet.
4. Commit `doppel(today): AAAA-MM-JJ`; push. Print `today.md`.

## Reads / writes
Reads tasks, questions, outbox, evolution briefs, config. Writes `today.md` only (overwritten daily).

## Unattended
Runs fully (last step of the daily pass); commit to `main`.
