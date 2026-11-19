---
name: ask
description: Answer a simple question about a project (state, decisions, who, what's planned or blocked) from the repo only — indexes first, then the brain, tasks and log — in the data language, with sources. Read-only on project data. Manual.
argument-hint: "[--project <slug>] <question>  e.g. « où en est le dossier X ? », « qu'a-t-on décidé sur Y ? »"
---

# /ask

> **Run & retro** (CLAUDE.md § Runs and retro): first `uv run scripts/signals.py run start --skill ask --args "<arguments>"` (keep the `R-…`); last, the **retro** — emit a signal only if something really got in the way (missing file, contradictory instruction, ambiguity worked around, context limit, missing tool, script error; never « tout va bien ») — then `uv run scripts/signals.py run end --run R-… --outcome ok|error|partial [--signals S-…]`.

## Steps
1. `git pull --rebase origin main`. Time-related question → `uv run scripts/dates.py now` (and `dates.py` for any period:
   « la semaine dernière » → `week`/`shift`, « le mois passé » → `month --offset -1`).
2. **Project**: `--project`, else the one named in the question, else match `projects/_index.md`. Still ambiguous →
   ask which one (one short question), never mix two projects' confidential information in one answer.
3. **Read in this order, stop as soon as the answer is complete** (CLAUDE.md « Reading order »):
   `projects/_index.md`, `tasks/_index.md` (filter the project) → `projects/<p>/brain.md` (relevant sections only) →
   the specific task files → `uv run scripts/logbook.py since --days N --project <p>` → `inbox/_processed/` only to
   verify a fact. Domain modules may add sources here (see CLAUDE.md « Domain »).
   Numbers (hours, dates, counts) come from scripts (`tasks.py list`, `dates.py`), never computed by hand.
4. **Answer** short (≤ 10 lines unless asked otherwise): the facts, then « Sources : » with paths / IDs (`T-…`, `Q-…`).
   Mark what is uncertain or contradictory between sources (and cite both). Unknown in the repo → say so plainly, and
   suggest how to get it (`/add`, a question to someone) — never fill the gap from general knowledge.
5. **No data change.** If the owner's question or reply contains new information (a decision, a correction, a fact),
   do not write it here: propose `/wrap` (or `/done`, `/add`) at the end.
6. Commit only the run record: `git add evolution/runs && git commit -m "doppel(ask): <projet>"`; push.

## Unattended
Not applicable (owner question).
