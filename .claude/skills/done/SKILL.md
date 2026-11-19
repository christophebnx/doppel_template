---
name: done
description: Record something the owner did — log line, task status update (done/doing/blocked), actual hours, new waiting items — from a short free text like "T-0004 fini 2h" or "envoyé le devis à Jean, 1h30". Manual.
argument-hint: "<texte libre>  e.g. « T-0004 fini 2h », « dossier X avancé, 3h », « Jean m'envoie le plan jeudi »"
---

# /done

> **Run & retro** (CLAUDE.md § Runs and retro): first `uv run scripts/signals.py run start --skill done --args "<arguments>"` (keep the `R-…`); last, the **retro** — emit a signal only if something really got in the way (missing file, contradictory instruction, ambiguity worked around, context limit, missing tool, script error; never « tout va bien ») — then `uv run scripts/signals.py run end --run R-… --outcome ok|error|partial [--signals S-…]`.

## Steps
1. `git pull --rebase origin main`. Parse: task id(s) (explicit `T-nnnn`, else match against open tasks in
   `tasks/_index.md`; several candidates → ask; none → log only, project from the text or ask), new state (fini →
   `done`; avancé/commencé → `doing`; bloqué → `blocked`; « reçu X de <personne> » on a `waiting` task → `done`;
   « <personne> m'enverra X le … » → new `waiting` task with `--waiting-on person:<slug> --expected-by <date>`), time
   spent as written (« 2h », « 1h30 », « 45min »), outcome text.
2. Update: `uv run scripts/tasks.py set T-nnnn status=<s> actual_h+=<durée telle qu'écrite>` (the script parses
   durations and accumulates — never add hours by hand). Add a progression line `- AAAA-MM-JJ · <texte> · owner:AAAA-MM-JJ`
   to the task body.
3. **reporter**: `logbook.py add --type done|info|blocked --project p --text "…" --source owner:AAAA-MM-JJ`.
4. Side effects: a task that others `depends_on` → mention which tasks are now unblocked (set them `todo` if they were
   `blocked` only on it). « je la fais jeudi » → `tasks.py set T-nnnn scheduled_on=<date via dates.py>`.
5. If the text implies new work or a decision, create the task / route the fact to brain-keeper (source `owner:AAAA-MM-JJ`).
6. `uv run scripts/index.py`; commit `doppel(done): T-nnnn <état>`; push. Print the log line(s) and task changes.

## Unattended
Not scheduled.
