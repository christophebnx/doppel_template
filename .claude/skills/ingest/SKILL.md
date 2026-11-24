---
name: ingest
description: Process all pending inbox items — triage (tasks, decisions, deadlines, questions), brain-keeper (project knowledge), reporter (log) — then update indexes and commit. Scheduled daily on workdays; also manual.
argument-hint: "[inbox file …]  (default: all pending items)"
---

# /ingest

> **Run & retro** (CLAUDE.md § Runs and retro): first `uv run scripts/signals.py run start --skill ingest --args "<arguments>"` (keep the `R-…`); last, the **retro** — emit a signal only if something really got in the way (missing file, contradictory instruction, ambiguity worked around, context limit, missing tool, script error; never « tout va bien ») — then `uv run scripts/signals.py run end --run R-… --outcome ok|error|partial [--signals S-…]`.

## Arguments
Optional list of inbox files; default all `inbox/*.md` listed in `inbox/_index.md` (oldest first). Nothing pending → say so, no commit.

## Steps
1. `git pull --rebase origin main`; `uv run scripts/index.py`; `uv run scripts/dates.py now`.
2. **triage** agent on the items (incl. `mail`, `facture`, `rdv` items written by /collect) (batch of ≤ 10 per call, oldest first). It creates/updates tasks (incl. `waiting` with
   `follow_up_after`), raises questions, archives items to `inbox/_processed/`, and returns facts and decisions per project.
3. **brain-keeper** agent with the facts/decisions returned (grouped by project): updates `projects/<p>/brain.md`.
4. Domain agents registered for ingestion (CLAUDE.md « Domain », e.g. a comms agent drafting follow-ups) — none by default.
5. **reporter** agent: log lines — one `info` per created task (`T-nnnn créée : <titre>`), one `decision` per decision
   (with `--at` = decision time if known), `done` for completed work reported, `blocked` for new blockers. Source = processed item.
5b. Weather-constrained tasks created or updated by triage (`climate` set, no `scheduled_on`) → run the /place steps
   on them (`uv run scripts/weather.py place <ids> --apply`, questions for the missing places).
6. `uv run scripts/index.py`; sanity checks: no file left in `inbox/` without a question explaining why; every new task
   has ≥ 1 source; `uv run scripts/index.py --check` returns 0.
7. Commit `doppel(ingest): <n> items, <n> tâches (+<new>/~<updated>), <n> questions`; `git pull --rebase`; push.

## Output
```
Ingest AAAA-MM-JJ — <n> items
- <item> → T-0003 (créée), T-0001 (màj), T-0009 (waiting jean-exemple, relance le 27/11), décision « … », 1 question (Q-004)
Questions ouvertes : <n> (nouvelles : Q-004…)
```

## Unattended
Run fully; never ask. Every ambiguity becomes `clarify` + question. Commit and push directly to `main`.
