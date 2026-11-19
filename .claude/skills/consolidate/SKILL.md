---
name: consolidate
description: Weekly consolidation by the curator agent on a branch consolidate/AAAA-Wnn with a pull request — contradictions (reported, never decided), duplicates, brain compression, archiving done tasks > 30 days, log roll-up > 8 weeks, index regeneration, estimate_correction recalibration. Scheduled Friday evening; also manual.
argument-hint: "[AAAA-Wnn]"
---

# /consolidate

> **Run & retro** (CLAUDE.md § Runs and retro): first `uv run scripts/signals.py run start --skill consolidate --args "<arguments>"` (keep the `R-…`); last, the **retro** — emit a signal only if something really got in the way (missing file, contradictory instruction, ambiguity worked around, context limit, missing tool, script error; never « tout va bien ») — then `uv run scripts/signals.py run end --run R-… --outcome ok|error|partial [--signals S-…]`.

## Steps
1. `git checkout main && git pull --rebase origin main`; week = `dates.py now` week.
2. `git checkout -b consolidate/W` (exists already → `consolidate/W-2`).
3. **curator** agent (all steps of `.claude/agents/curator.md`, incl. stale `waiting` tasks).
4. `uv run pytest -q` and `uv run scripts/index.py --check` must pass; otherwise fix or revert the offending change.
5. Commit `doppel(consolidate): W — <résumé>`; `git push -u origin consolidate/W`.
6. Open a PR to `main` (GitHub MCP `create_pull_request`, or `gh pr create` if available) titled `doppel(consolidate): W`, body: counts per step, contradictions found (also in questions.md), calibration old → new, archived/rolled-up files. If no PR tool is available, add a question « PR à ouvrir pour consolidate/W » and say so.
7. Never merge it. Print the PR link.
8. Then `/evolve` runs (scheduled right after, or chained manually): contradictions found here were emitted as signals.

## Unattended
Runs fully; never pushes to `main`. A consolidation branch from a previous week still open → mention it in the PR body (do not rebase it).
