---
name: upgrade
description: Update this doppel project from the doppel template it was created from — fetch the template, apply its framework changes since the recorded base (skills, agents, scripts, tests, templates, docs, CLAUDE.md) with a 3-way merge that keeps the project's own edits, add new config keys without changing the project's values, never touch data; on a branch template-sync/AAAA-MM-JJ with tests and a PR the owner merges. Manual, or scheduled monthly.
argument-hint: "[--dry-run]"
---

# /upgrade

> **Run & retro** (CLAUDE.md § Runs and retro): first `uv run scripts/signals.py run start --skill upgrade --args "<arguments>"` (keep the `R-…`); last, the **retro** — emit a signal only if something really got in the way (missing file, contradictory instruction, ambiguity worked around, context limit, missing tool, script error; never « tout va bien ») — then `uv run scripts/signals.py run end --run R-… --outcome ok|error|partial [--signals S-…]`.

## Steps
1. `git checkout main && git pull --rebase origin main`; `uv run scripts/template.py status --json`.
   `is_template` → « ceci est le template » and stop. No `base` → run /setup step 2 first. No upstream commit → « à jour », stop.
2. `uv run scripts/template.py upgrade --dry-run` → show the template commits and the files that will change.
   `--dry-run` → stop here.
3. `git checkout -b template-sync/AAAA-MM-JJ` (date from `dates.py now`); `uv run scripts/template.py upgrade --json`.
4. Conflicts (`status: conflicts`): resolve each file keeping BOTH intents — the template's change and the project's
   own edit (CLAUDE.md « Domain », tuned templates, project skills). Unsure → keep the project's version and list the
   template change in the PR as « à reprendre ». No conflict marker may remain (`git diff --check`).
5. `uv sync`; `uv run pytest -q` and `uv run scripts/index.py --check` must pass; then `uv run scripts/evals.py run`
   when the harness has scenarios, and compare to the last report on main (`evals.py compare`). A failing test caused
   by the template change → fix minimally on the branch, or leave the PR as draft with the failure explained.
6. Commit `doppel(upgrade): template <base[:7]>..<latest[:7]>`; push the branch; open a PR to main listing: template
   commits, files changed, conflicts and how they were resolved, config keys added (with their defaults — new
   features stay off until the owner turns them on), test/eval results. Never merge it: the protected core may change.

## Reads / writes
Framework files (`template.py: FRAMEWORK` minus `template.exclude`) and `config.yaml` (new keys, `template.base`),
on the branch only. Never data folders.

## Unattended
Allowed (monthly scheduled task): never asks; conflicts unresolved with confidence → PR as draft with the list.
Never pushes to main.
