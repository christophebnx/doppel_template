---
name: new-skill
description: Extend doppel for the owner's domain — design and add a new skill (and, when language work needs a dedicated worker, a new agent, template, script or index) from templates/skill.md and templates/agent.md, register it in CLAUDE.md and tests, and prove it with an eval scenario. Manual (interactive design with the owner).
argument-hint: "<nom> <but en une phrase>  e.g. « prep préparer une réunion avec un client »"
---

# /new-skill

> **Run & retro** (CLAUDE.md § Runs and retro): first `uv run scripts/signals.py run start --skill new-skill --args "<arguments>"` (keep the `R-…`); last, the **retro** — emit a signal only if something really got in the way (missing file, contradictory instruction, ambiguity worked around, context limit, missing tool, script error; never « tout va bien ») — then `uv run scripts/signals.py run end --run R-… --outcome ok|error|partial [--signals S-…]`.

A domain skill is a **supervised** change to doppel itself (the owner asks for it, in a conversation): it is not an
autonomous evolution, so `/evolve` and `/improve` are not involved — but principle 11 still applies (an eval scenario).

## Steps
1. `git pull --rebase origin main`. Read `docs/extending.md` (design rules, optional modules already available in
   doppel_klee) and CLAUDE.md « Domain ».
2. **Design with the owner** (interactive, ≤ 5 short questions in one message): trigger (manual / scheduled), inputs,
   output files and their format, which data folders it reads/writes, which agent does the language work, what must be
   computed by a script (dates, counts, scores — never by the LLM), unattended behaviour, privacy rules. Reuse an
   existing agent when its mission fits; a new agent only for a distinct language job.
3. **Write the components** (English, following the templates exactly):
   - `.claude/skills/<nom>/SKILL.md` from `templates/skill.md` (run & retro line, steps, agents, output, `## Unattended`);
   - if needed `.claude/agents/<agent>.md` from `templates/agent.md` (reads `preferences.md` first, `## Never` section);
   - if needed a data template `templates/<type>.md` (French headings, frontmatter field order), a script
     `scripts/<nom>.py` (stdlib + pyyaml, `--root`, `--json`, `run_main`) with its pytest in `tests/`, a new data
     folder with an index function registered in `scripts/index.py: INDEXES`, new ID kinds in `scripts/ids.py: KINDS`,
     a drafts folder in `scripts/signals.py: DRAFT_FOLDERS` and `scripts/today.py: DRAFT_FOLDERS`.
4. **Register**: CLAUDE.md tables (Skills, Agents, Scripts, Map) and « Domain » section; `tests/test_repo.py` lists
   (`SKILLS`, `AGENTS`, `TEMPLATES`); `README.md` daily-use table; `docs/scheduling.md` if scheduled.
5. **Prove it**: add at least one deterministic scenario `tests/evals/scenarios/test_eval_<nom>.py` (fixtures from
   `tests/evals/conftest.py`) — or an LLM-graded `*.yaml` scenario + a NEW rubric in `tests/evals/rubrics/` when the
   output is language. Run `uv run pytest` and `uv run scripts/evals.py run` (all green).
6. `uv run scripts/index.py`; commit `doppel(new-skill): /<nom>`; push. Print what was added and how to call it.

## Never
Touch the protected core (`evolution/protected.txt`) in this skill — a change there goes through a separate PR the
owner merges · put domain data (real names, client facts) in technical files or templates.

## Unattended
Not applicable (needs the owner's design decisions).
