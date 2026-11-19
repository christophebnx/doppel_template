# Adapting doppel to a domain

doppel is a **framework**: a file-based AI double whose kernel (inbox → triage → tasks/knowledge → log, questions,
`/wrap`, self-evolution) is domain-agnostic. A concrete doppel = this kernel + a few domain skills, agents, templates
and scripts. The reference implementation for a data-engineering consultant is the `doppel_klee` repository: it adds
planning, people, meetings, multi-client isolation, Claude Code briefs and onboarding on top of the same kernel.

## 1. Fill in the identity (15 minutes)

1. `config.yaml`: `owner`, `domain`, `timezone`, `language.data`, `executors` (extra task executors, e.g.
   `claude-code` for a developer, `assistant` for a human assistant).
2. `CLAUDE.md` « Domain » section: vocabulary, what a project is, the item types that arrive, the deliverables
   doppel prepares, domain rules (confidentiality, regulation). This section is **outside** the protected core, so
   doppel may refine it later through `/improve`.
3. `templates/brain.md`: add the sections that matter in the domain (e.g. « Technique » for software, « Budget » and
   « Pièces » for a renovation, « Procédure » for a legal case). brain-keeper uses whatever sections the template has.
4. `templates/status.md`: rename the audiences (`externe | interne | equipe`) and their rules.
5. `README.md`: replace the intro and the daily-use table with the domain's wording.
6. Create projects: `uv run scripts/project.py add <slug> --name "…"`.

## 2. Add domain skills

Use `/new-skill <nom> <but>` in a conversation: it designs the skill with you, writes it from `templates/skill.md`
(and `templates/agent.md` when a new language job is needed), registers it in CLAUDE.md, `tests/test_repo.py`,
README and `docs/scheduling.md`, and proves it with an eval scenario.

Design rules (they are what makes doppel reliable — keep them):

| Rule | Why |
|---|---|
| One skill = one entry point with numbered steps, a run & retro line and an `## Unattended` section | any session (even scheduled, nobody watching) can run it from the file alone |
| Language work in agents, numbers in scripts | LLMs are bad at dates and sums; scripts are testable |
| Every data folder has a generated `_index.md` (register a builder in `scripts/index.py: INDEXES`) | agents read one line per item instead of whole folders |
| Every ID from a script (`scripts/ids.py: KINDS`) | no collisions across sessions and accounts |
| Every fact cites a source in `inbox/_processed/` | traceability, contradictions can be arbitrated |
| Drafts go to a folder with `state: draft` (register it in `signals.py`/`today.py: DRAFT_FOLDERS`) | the owner validates; owner rewrites become `user-correction` signals automatically |
| Ambiguity → `clarify` + `questions.md` | unattended runs never block |
| A new component comes with a scenario in `tests/evals/scenarios/` | principle 11; the evolution loop needs a harness to compare against |

## 3. Optional modules available in `doppel_klee`

Each module below is a set of files that can be ported as a block (copy, then generalize wording). File paths are
those of `doppel_klee`.

| Module | What it brings | Files |
|---|---|---|
| **Planning** | weekly agenda (meetings, work slots, days off), capacity ceiling, block placement by script, weekly plan draft → `ok`, replanning of the rest of the week | `scripts/agenda.py`, `scripts/capacity.py`, skills `agenda`, `plan`, `replan`, agent `planner`, templates `plan.md`, `agenda/recurring.yaml`; `config.yaml: capacity` keys; tests `test_capacity.py` |
| **People & comms** | one file per person (roles per project), pending topics, follow-up (relance) drafts, prep sheets for meetings/people | `scripts/people.py`, skills `prep`, `run-doppel-tasks`, agent `comms`, templates `person.md`, `interaction.md`; folders `people/`, `interactions/` |
| **Meetings** | meeting minutes `M-nnn` written by triage from transcripts, searchable memory (`meetings.py search`), « what was said last month about X » | `scripts/meetings.py`, template `meeting.md`, triage step 2b, CLAUDE.md « A past meeting » |
| **Multi-client isolation** | client identity cards, routing of every item by score, leak check of every deliverable | `scripts/route.py`, `scripts/crosscheck.py`, `config.yaml: clients`, tests `test_clients.py` (protected in klee) |
| **Claude Code bridge** | briefs for a coding session at a client, DEV-STATUS export prompt and its ingestion | skills `brief`, `export-prompt`, templates `brief.md`, `dev-status.md` |
| **Onboarding** | build a running project's knowledge from an untrusted lot (zips, mails, repos) with zip-slip/bomb guards and redaction | `scripts/onboard.py` (its `redact()` is the origin of `scripts/redact.py`), skill `onboard`, template `onboarding.md` (protected in klee) |
| **Project closing** | closing report, archive, recalibration | skill `close-project`, template `project-closure.md` (`scripts/project.py close` is already in the kernel) |
| **Radar** | cross-project quick wins, duplicates, hidden dependencies, stale topics | skill `radar`, template `radar.md`, brain-keeper « Radar analysis » |
| **Day page** | interactive claude.ai Artifact for today with checkboxes applied at the next `/today` | `scripts/today_page.py`, `artifacts.yaml`, `/today` step 1b/3b |

When porting a module: register its indexes/ID kinds/draft folders (§ 2), add its paths to `evolution/protected.txt`
if it is a security boundary (as klee does for routing and onboarding), and port its tests.

## 4. Evolution settings

Start with `evolution.autonomy: propose` and `merge: pr`: doppel proposes briefs, you approve, `/improve` opens PRs
you merge. Raise autonomy only once the harness has at least `evals_min_scenarios` scenarios and a reference run on
`main` (`uv run scripts/evals.py run`): the startup guard refuses `execute`/`auto` otherwise.
