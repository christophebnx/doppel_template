---
name: add
description: Add anything that reached the owner (pasted text, mail, chat message, ticket, note, screenshot/image, audio, video, pdf/doc) to the doppel inbox as a normalized item. Use when the owner pastes or attaches content to remember or process. --now chains /ingest.
argument-hint: "[--project <slug>] [--from <person>] [--now] <content or file path>"
---

# /add

> **Run & retro** (CLAUDE.md § Runs and retro): first `uv run scripts/signals.py run start --skill add --args "<arguments>"` (keep the `R-…`); last, the **retro** — emit a signal only if something really got in the way (missing file, contradictory instruction, ambiguity worked around, context limit, missing tool, script error; never « tout va bien ») — then `uv run scripts/signals.py run end --run R-… --outcome ok|error|partial [--signals S-…]`.

## Arguments
- `--project <slug>`: project hint (else guessed later by triage; leave empty if unsure).
- `--from <person>`: sender (person slug or name).
- `--now`: run `/ingest` right after.
- Content: pasted text, attached image, or file path(s) (audio, video, pdf, docx, image).

## Steps
1. `git pull --rebase origin main`; `uv run scripts/dates.py now --json` (for `added`).
2. Detect `type`: mail · meeting (transcript/notes) · message (chat) · ticket · note · image · audio · video · doc
   (+ types added by domain modules, see CLAUDE.md « Domain »).
3. Normalize the content (keep original language, never summarize away facts):
   - **text/mail/message/ticket**: remove signatures, legal disclaimers, quoted history already in the repo (grep
     `inbox/_processed/` for the quoted subject), tracking links, greetings noise. Keep sender, recipients (roles),
     date, subject, body, attachment names.
   - **image**: describe what is shown in 1–3 lines + transcribe all readable text verbatim.
   - **audio/video**: `uv run scripts/transcribe.py <file> --language <config transcription.language>` if the audio
     extra is installed (`uv sync --extra audio`); otherwise write `## Contenu` = "Transcription indisponible", add a
     question asking the owner for a transcript, and continue.
   - **pdf**: read it (Read tool); **docx**: `unzip -p <f> word/document.xml | sed -e 's/<[^>]*>/ /g'`; keep the structure.
   - **secrets** (passwords, tokens, keys) seen in the content → replace them by `[SECRET MASQUÉ]` before writing.
3b. Doing day vs due day: keep the owner's words as written (« jeudi matin », « pour vendredi ») — triage turns
   « jeudi » into `scheduled_on` and « pour jeudi » into `deadline`.
4. Date of the item = date of the original (mail date, meeting date); if unknown, now. Use `dates.py` for any relative date.
5. Raw original: when a file is provided, copy it to `inbox/_raw/AAAA-MM-JJ_<slug>.<ext>` (heavy audio/video are
   git-ignored: say so). Pasted-only content: `raw: none`.
6. Write `inbox/AAAA-MM-JJ_<type>_<slug>.md` from `templates/inbox-item.md` (slug: 3–5 words of the subject). Several
   distinct messages pasted at once → one item each.
7. `uv run scripts/index.py`; commit `doppel(add): <type> <slug>`; push.
8. `--now` → run `/ingest`.

## Agents
None (the skill itself). /ingest does the extraction.

## Output
One line per item: `inbox/<file> · <type> · <from> · <project_hint>` + warnings (raw not kept, transcription missing).

## Unattended
Not scheduled. If ever run unattended, never ask: unknown sender/project stay empty.
