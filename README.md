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

1. Create a repository from this template (« Use this template » on GitHub, or copy the files).
2. Install and test:

```bash
uv sync
```

```bash
uv run pytest
```

3. Fill in `config.yaml` (`owner`, `domain`, `timezone`, `language`), the « Domain » section of `CLAUDE.md`, and the
   domain sections of `templates/brain.md` — see [`docs/extending.md`](docs/extending.md) § 1.
4. Add your first project: `uv run scripts/project.py add <slug> --name "…"`.
5. Add domain skills with `/new-skill` (or port modules from `doppel_klee`: planning, people, meetings, …).
6. Create the scheduled tasks of [`docs/scheduling.md`](docs/scheduling.md).

Optional audio/video transcription: `uv sync --extra audio` (faster-whisper).

## Daily use (kernel)

| I want to… | Command |
|---|---|
| ask something about a project | `/ask où en est le dossier X ?` (answer with sources, nothing modified) |
| drop something in (paste text, screenshot, file) | `/add [--project p] [--from personne] [--now]` |
| process the inbox now | `/ingest` |
| answer doppel's questions | write after `- R:` in `questions.md`, then `/answer` |
| record what I did | `/done T-0004 fini 2h30` |
| a status for someone | `/status 5j externe demo-project` · `/status 5j interne` |
| see my day in one minute | `/today` (or open `today.md`) |
| fit a weather-dependent task (« sec, hors gel, cette semaine ») | say it, or `/place T-0012` |
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
