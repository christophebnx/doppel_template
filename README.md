# doppel (template)

A framework for building an **AI double**: a git repository that receives everything that reaches its owner in a
given domain (mails, notes, messages, documents, screenshots, audio), structures it into tasks and per-project
knowledge, executes what it can itself, prepares deliverables for validation, keeps a work log — and improves itself
only on evidence.

This repository is the **domain-agnostic skeleton**, extracted from `doppel_klee` (a doppel for a data engineering
consultant). It contains the kernel and the self-evolution machinery; domain features are added as skills
(see [`docs/extending.md`](docs/extending.md)).

The repository **is** the system: state = files, protocol = [`CLAUDE.md`](CLAUDE.md), commands = skills
(`.claude/skills/`), workers = agents (`.claude/agents/`), numbers = Python scripts (`scripts/`). Any Claude Code
session (any account, local or cloud, scheduled or interactive) can operate it from the repo alone.

## Start a new doppel

1. On GitHub: « Use this template » → **Private** repository (collected mails and appointments are committed to it;
   `/collect` refuses to run in a repository not declared private).
2. Open a Claude Code session on the new repository and run **`/setup`**: an interview that defines what this AI
   brain is for (owner, domain, what a project is, objectives), tunes doppel to those objectives (brain sections,
   status audiences, preferences, places), connects the project's mailbox and calendars (Gmail / Google Calendar
   connectors — accounts are chosen per project, never in the template) and creates the scheduled tasks.
3. Later, **`/upgrade`** brings the template's improvements into the project (framework files only, 3-way merge that
   keeps your own edits, data untouched) on a branch with a PR you merge.

Manual alternative: `uv sync && uv run pytest`, then [`docs/extending.md`](docs/extending.md) § 1.

Optional audio/video transcription: `uv sync --extra audio` (faster-whisper).

## Daily use (kernel)

| I want to… | Command |
|---|---|
| ask something about a project | `/ask où en est le dossier X ?` (answer with sources, nothing modified) |
| drop something in (paste text, screenshot, file) | `/add [--project p] [--from personne] [--now]` |
| pull new mails, invoices and appointments now (private repo, connectors) | `/collect` |
| process the inbox now | `/ingest` |
| answer doppel's questions | write after `- R:` in `questions.md`, then `/answer` |
| record what I did | `/done T-0004 fini 2h30` |
| a status for someone | `/status 5j externe demo-project` · `/status 5j interne` |
| see my day in one minute | `/today` (or open `today.md`) |
| fit a weather-dependent task (« sec, hors gel, cette semaine ») | say it, or `/place T-0012` |
| take the latest template improvements | `/upgrade` (PR to merge) |
| retune doppel (objectives, accounts, calendars) | `/setup --retune` |
| end a conversation (any account, any device) | `/wrap` → « Session supprimable. » |
| something in doppel is wrong / annoying | `/signal le status est trop long` |
| review how doppel wants to improve itself | `/evolve` (weekly) → `/evolve approve E-001` → `/improve E-001` |
| stop all self-modification at once | `/evolve stop` (creates `evolution/STOP`), `/evolve resume` |
| add a capability for my domain | `/new-skill <nom> <but>` |

## Rules worth remembering

- Conversations are disposable: everything that matters is committed; `/wrap` closes a conversation safely.
- How the owner wants doppel to behave lives in `preferences.md` (written by `/wrap` from the owner's words).
- Nothing is sent by doppel. Drafts live in `outbox/` until the owner validates them.
- Ambiguities become `clarify` tasks + questions, never guesses.
- Every task, decision and brain fact cites its source in `inbox/_processed/`.
- Dates, hours, IDs and scores come from `scripts/` — the agents never compute them.
- doppel improves itself only on evidence: signals → brief with a failing regression scenario → fix → evals → PR.
  The autonomy level (`config.yaml: evolution`) goes from « propose only » to « merge alone »; the protected core
  (`evolution/protected.txt`) always needs the owner's merge.

## Layout

See the map in [`CLAUDE.md`](CLAUDE.md), the design in [`docs/architecture.md`](docs/architecture.md), and how to
adapt it in [`docs/extending.md`](docs/extending.md).
