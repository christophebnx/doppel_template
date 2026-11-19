---
name: signal
description: The owner reports a problem with doppel itself (wrong output, friction, missing capability, a skill that misbehaves) in free text; doppel rewrites it as a well-formed `user` signal (Attendu · Observé · Preuves · Impact · Hypothèse, pointers only), shows it, records it with deduplication. Manual.
argument-hint: "<texte libre>  e.g. « le status est trop long », « /ingest a créé deux fois la même tâche »"
---

# /signal

> **Run & retro** (CLAUDE.md § Runs and retro): first `uv run scripts/signals.py run start --skill signal --args "<arguments>"` (keep the `R-…`); last, the **retro** — emit a signal only if something really got in the way (missing file, contradictory instruction, ambiguity worked around, context limit, missing tool, script error; never « tout va bien ») — then `uv run scripts/signals.py run end --run R-… --outcome ok|error|partial [--signals S-…]`.

## Steps
1. `git pull --rebase origin main`.
2. Identify the **component** at fault (skill / agent / script / template file) from the text and the recent context
   (`log/`, `evolution/runs/`, the file the owner mentions). Unsure → the most specific skill, and say so.
3. Write the signal fields:
   - `kind` (bug · wrong-output · limitation · friction · missing-capability · cost · user-correction), `severity`
     (high = wrong data or blocked work; medium = rework needed; low = annoyance);
   - `fingerprint` `<skill-or-agent>.<problem>` in a few words (`status.too-long`) — check
     `evolution/signals/_index.md` for an existing fingerprint of the same problem and reuse it;
   - Attendu / Observé / Preuves / Impact / Hypothèse: **pointers only** — IDs (T-, Q-, R-, S-…), paths, the command;
     never the content of a deliverable, a mail or a transcript (« le status outbox/2026-11-25_status-demo-project.md
     fait 12 lignes », not its text). Hypothesis explicitly marked.
4. Show the signal to the owner (interactive) and adjust once if asked.
5. `uv run scripts/signals.py emit --emitter user --origin user --kind … --component … --fingerprint … --severity …
   --evidence owner:AAAA-MM-JJ[-n] --expected "…" --observed "…" --proof "…" --impact "…" --hypothesis "…"`
   (dedup: same open fingerprint → occurrences +1).
6. Commit `doppel(signal): S-nnnn <fingerprint>`; push. Print the id and whether it was created or incremented.

## Unattended
Not applicable (owner input).
