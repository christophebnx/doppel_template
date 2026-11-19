---
name: <nom>                 # = folder name .claude/skills/<nom>/
description: <what it does, with which agent, what it writes, when it runs (manual / scheduled …). ≥ 40 chars; this text decides when Claude triggers the skill.>
argument-hint: "<arguments>  e.g. « … »"
---

# /<nom>

> **Run & retro** (CLAUDE.md § Runs and retro): first `uv run scripts/signals.py run start --skill <nom> --args "<arguments>"` (keep the `R-…`); last, the **retro** — emit a signal only if something really got in the way (missing file, contradictory instruction, ambiguity worked around, context limit, missing tool, script error; never « tout va bien ») — then `uv run scripts/signals.py run end --run R-… --outcome ok|error|partial [--signals S-…]`.

## Arguments
<!-- each argument, its default -->

## Steps
1. `git pull --rebase origin main`; `uv run scripts/dates.py now` when time matters.
2. <read: indexes first, then only the needed files>
3. <compute with scripts: dates, counts, IDs — never by hand>
4. **<agent>** agent: <language work, output file from templates/<type>.md>
5. `uv run scripts/index.py`; commit `doppel(<nom>): <résumé>`; push.

## Agents
<!-- which agent does what -->

## Reads / writes
<!-- folders read / written -->

## Output
<!-- what is printed to the owner -->

## Unattended
<!-- scheduled? what it does without anyone watching (never ask; questions.md) — or "Not applicable" -->
