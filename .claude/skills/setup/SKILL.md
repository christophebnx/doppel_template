---
name: setup
description: Initialise a doppel project created from the template, in an interactive conversation with the owner — the purpose of this AI brain (owner, domain, what a project is, objectives), the tuning that follows from those objectives (brain sections, status audiences, preferences, weather places), the mail and calendar accounts it reads (Gmail / Google Calendar connectors of this project) and the scheduled tasks; records the template base for /upgrade. Run once per new project (re-run to retune). Manual only.
argument-hint: "[--retune]  (re-run on an initialised project: only what the owner wants to change)"
---

# /setup

> **Run & retro** (CLAUDE.md § Runs and retro): first `uv run scripts/signals.py run start --skill setup --args "<arguments>"` (keep the `R-…`); last, the **retro** — emit a signal only if something really got in the way (missing file, contradictory instruction, ambiguity worked around, context limit, missing tool, script error; never « tout va bien ») — then `uv run scripts/signals.py run end --run R-… --outcome ok|error|partial [--signals S-…]`.

Accounts are never named in the template: a project's mailbox and calendars are the connectors attached to ITS
sessions and scheduled tasks, and their ids are written in ITS (private) config only.

## Steps
1. **Where am I.** `git pull --rebase origin main`; `uv run scripts/template.py status --json`.
   `is_template: true` → stop: « Ceci est le template. Crée ton doppel : GitHub → Use this template → **Private** →
   ouvre une session sur ce nouveau dépôt et relance /setup. » Then `uv run scripts/setup.py status` (checklist).
2. **Template base.** `template.base` empty → `uv run scripts/template.py init --repo <template.repo>` (base = latest
   template commit; if the project was created from an older template, ask for the date and pass `--base <sha>`).
3. **Purpose of this brain** — ask, in the data language, one short block at a time (AskUserQuestion where choices
   exist), never more than 4 questions per turn:
   a. who the owner is, and the domain in one line (« gestion de la maison et de la famille », « avocat en droit social »);
   b. what a *project* is here (a client mission, a property, a case, a child's school year…) and the first projects;
   c. the **objectives**: what doppel must get right (« ne rater aucune facture », « planifier les travaux selon la
      météo », « préparer chaque rendez-vous »), what it must never do, who the audiences of status reports are;
   d. the incoming material (mails, invoices, appointments, notes, photos, audio) and the deliverables expected.
   Write the answers verbatim-ish to `inbox/_processed/AAAA-MM-JJ_conversation_setup.md` (`type: conversation`,
   `from: owner`) — it is the source cited by everything below.
4. **Write the identity** (scripts only for config): `uv run scripts/setup.py set owner="…" domain="…"
   [timezone=… data=… transcription_language=…]`; the « Domain » section of CLAUDE.md via
   `uv run scripts/setup.py domain --file <tmp>` (vocabulary, what a project is, item types, deliverables, domain
   rules, objectives); projects via `uv run scripts/project.py add <slug> --name "…"`.
5. **Tune to the objectives** — propose, then apply what the owner accepts:
   - `templates/brain.md` sections and `templates/status.md` audiences for the domain;
   - `preferences.md` lines (format in the file, source = the setup item) for each « always / never » objective;
   - weather: places (`uv run scripts/weather.py place-add <slug> --query "<commune>"`) and `climate.work_hours` /
     `work_days` if outdoor work matters;
   - domain skills worth adding (`/new-skill`), listed, not built here.
6. **Mail and calendars of this project.**
   a. Repository visibility: check it (GitHub tool or `list_repos` visibility); not private → explain that collected
      mails would be published, offer to continue without collection, never enable it.
   b. Connectors: call Gmail `list_labels` and Calendar `list_calendars`. Missing tool → tell the owner to connect
      the account (claude.ai → Settings → Connectors: Gmail, Google Calendar, signed in with the account doppel must
      read) and to add those connectors to this project's sessions / scheduled tasks; continue without.
   c. Ask (multi-select) which calendars to read — show `summary` and `description`, never assume; other people's
      calendars only if the owner picks them. Ask the mail scope (Primary tab + invoices by default; label only; whole
      inbox) and senders to exclude, in the light of the objectives.
   d. `uv run scripts/setup.py collect --enable --private --calendar <id>=<alias> … [--exclude-from …]
      [--mail-query "…"] [--no-invoices]`. Then a first `/collect --no-ingest` and show what came in.
7. **Scheduled tasks** — show the four tasks of `docs/scheduling.md` with this repository's URL; create them only
   after the owner's yes (`create_trigger`, connectors Gmail + Google Calendar for the daily one when collection is on).
8. `uv run scripts/setup.py status` (all ✓ or explained); `uv run scripts/index.py`; `uv run pytest -q`;
   commit `doppel(setup): <owner> · <domaine>`; push (restricted branch → PR to main, say so).

## Agents
None: an interview by the skill itself; project creation, config and domain writes by scripts.

## Reads / writes
Writes `config.yaml` (identity, template, collect, places, projects via scripts), CLAUDE.md « Domain »,
`templates/brain.md`, `templates/status.md`, `preferences.md`, the setup conversation item, scheduled tasks (on yes).

## Output
The checklist of `setup.py status`, the calendars and mail scope connected, the scheduled tasks created, and what
remains (e.g. « connecteur Agenda à ajouter à la tâche planifiée »).

## Unattended
Not applicable: setup is an interview. Started unattended → write one question in `questions.md`
(« Lancer /setup en conversation ») and stop.
