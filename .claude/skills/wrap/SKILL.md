---
name: wrap
description: End-of-conversation skill — persist everything that only exists in the current conversation (decisions, new tasks / status changes / time spent, facts about a project, answers to questions.md, the owner's preferences on doppel, corrections) as a `conversation` inbox item processed with the /ingest rules, commit + push, then confirm « Session supprimable. ». Nothing new → one line, no write, no commit. Manual; propose it before concluding any conversation that holds unpersisted information.
argument-hint: ""
---

# /wrap

> **Run & retro** (CLAUDE.md § Runs and retro): first `uv run scripts/signals.py run start --skill wrap --args "<arguments>"` (keep the `R-…`); last, the **retro** — emit a signal only if something really got in the way (missing file, contradictory instruction, ambiguity worked around, context limit, missing tool, script error; never « tout va bien ») — then `uv run scripts/signals.py run end --run R-… --outcome ok|error|partial [--signals S-…]`.

Goal: the conversation can be deleted right after without losing anything.

## Steps
1. `git pull --rebase origin main`; `uv run scripts/dates.py now`.
2. **What is already persisted**: `uv run scripts/wrap.py context --since "<start of this conversation>"` (or `--hours N`
   covering it): commits and files written during the session, uncommitted changes, `/wrap` items already written.
   Commit pending changes of a skill that forgot to (its own `doppel(<skill>)` message) before going on.
3. **Extract from the current conversation only the owner's own information that is not in the repo yet** — check each
   candidate against the files touched in step 2 and the relevant index/brain/task/`questions.md` (grep):
   - **décisions** (project or organisation decisions stated or taken while talking);
   - **tâches** : new work, status changes, time spent (`/done`-like statements), new `waiting` items (« X m'envoie … »);
   - **infos** on a project or a person (context, role, risk…);
   - **réponses** to questions of `questions.md` (by id or unambiguous subject);
   - **préférences doppel**: how the owner wants doppel to behave (« ne me propose plus X », « les status en 5 lignes max »);
   - **corrections** of what doppel produced in this conversation (« ce n'est pas ça », estimate corrected, draft
     rewritten, wrong fact fixed) → besides fixing the data, one `user-correction` signal each.
   **Ignore**: small talk; ideas explored then abandoned or left undecided — at most a question if the owner explicitly
   asked to think about it later; your own suggestions the owner did not adopt; anything already persisted (step 2);
   content of files the owner pasted that `/add` already stored.
4. **Nothing left** → answer exactly one line: « Rien de nouveau à enregistrer — session supprimable. » No file, no commit. Stop.
5. Write `inbox/AAAA-MM-JJ_conversation_<sujet>.md` (template `templates/inbox-item.md`, `type: conversation`,
   `from: owner`, `raw: none`, `date` = now): sections Décisions · Tâches et temps · Infos projets/personnes ·
   Réponses aux questions (`Q-nnn : réponse`) · Préférences doppel — only non-empty ones, one fact per line, close to
   the owner's words, project slug in each line. Uncertain extraction → keep it, flagged « (à confirmer) ».
6. **Process it immediately with the /ingest rules** (triage → brain-keeper → reporter) — the item is the source of
   everything it produces (`inbox/_processed/<file>`):
   - decisions → brain Décisions + `decision` log line; tasks via `tasks.py` (dedupe!), time via `actual_h+=`;
   - answers → as in `/answer` step 3, then remove the answered blocks from `questions.md`; the source is
     `inbox/_processed/<file>#Q-nnn` (no separate answer archive needed);
   - preferences → `preferences.md` « Actives » (`- AAAA-MM-JJ · <portée> · <préférence> · <source>`); a contradicted
     older preference moves to « Remplacées »; never into project brains;
   - « (à confirmer) » items → `clarify` / question, never applied as certain;
   - corrections → apply the corrected fact, then `uv run scripts/signals.py emit --emitter user --origin user
     --kind user-correction --component <skill or agent that produced it> --fingerprint <skill>.<what-was-wrong>
     --severity low|medium --evidence <conversation item path> --expected "…" --observed "…"` — pointers only.
7. `uv run scripts/index.py`; commit `doppel(wrap): <résumé court>`; `git pull --rebase`; push.
8. **Confirm** in ≤ 5 lines what was recorded (with ids: decisions, T-…, Q-… answered, preferences, S-… signals), then
   the sentence « Session supprimable. »

## Agents
triage (conversation item), brain-keeper (decisions, project facts), reporter (log).

## Unattended
Not applicable (needs a conversation). Scheduled runs never call it.
