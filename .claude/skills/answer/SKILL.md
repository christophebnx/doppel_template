---
name: answer
description: Apply the owner's answers written in questions.md (the "- R:" lines) — unblock or update tasks, complete brains, archive answered questions with their answers as a source. Manual.
argument-hint: "[Q-nnn …]  (default: every question with a non-empty R:)"
---

# /answer

> **Run & retro** (CLAUDE.md § Runs and retro): first `uv run scripts/signals.py run start --skill answer --args "<arguments>"` (keep the `R-…`); last, the **retro** — emit a signal only if something really got in the way (missing file, contradictory instruction, ambiguity worked around, context limit, missing tool, script error; never « tout va bien ») — then `uv run scripts/signals.py run end --run R-… --outcome ok|error|partial [--signals S-…]`.

## Steps
1. `git pull --rebase origin main`. Parse `questions.md`: blocks `### Q-nnn · date · projet · T-id` whose `- R:` line is
   non-empty (answers may also be given in the chat: write them into the `- R:` lines first).
2. Archive first (so the answer becomes a citable source): append each answered block, verbatim, to
   `inbox/_processed/AAAA-MM-JJ_note_reponses.md` (today's date; create from `templates/inbox-item.md` with `type: note`,
   `from: owner`). Source for what follows: `inbox/_processed/AAAA-MM-JJ_note_reponses.md#Q-nnn`.
3. For each answer:
   - linked task in `clarify`/`blocked` → update fields (`tasks.py set`: status `todo`, deadline, executor, estimate…),
     add a progression line with the source;
   - answer is a decision or fact → **brain-keeper**; **reporter** logs `decision` or `info`;
   - answer creates new work → `tasks.py new` with the source;
   - answer "abandonner" → task `dropped` with reason;
   - partial/unclear answer → keep the question open, rephrase it under the original (`- précision demandée : …`).
4. Remove answered blocks from `questions.md`.
5. `uv run scripts/index.py`; commit `doppel(answer): <n> réponses appliquées`; push.

## Output
One line per question: `Q-nnn → <effet> (T-…)`. List questions still open.

## Unattended
Not scheduled. Only applies answers already written; never invents one.
