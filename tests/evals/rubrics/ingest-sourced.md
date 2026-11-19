# Rubric — /ingest produces sourced, correctly dated state

Score each criterion 0 or 1; the scenario passes when the total is ≥ 4/5.

1. A task « envoyer le devis révisé » exists with `deadline: 2026-11-26` (jeudi after the mail date, computed with dates.py) and is not `scheduled_on`.
2. A `waiting` task on `person:jean-exemple` exists for the plan, with `expected_by: 2026-11-24` and a `follow_up_after` set by the script.
3. The decision « option B » is in `projects/demo-project/brain.md` « Décisions » with the date and the source `inbox/_processed/2026-11-20_mail_demande-devis.md`.
4. Every created task lists `inbox/_processed/2026-11-20_mail_demande-devis.md` in `sources`; the item was moved to `inbox/_processed/`.
5. Log lines exist (`info` for created tasks, `decision` for the decision) written via logbook.py format, and indexes pass `index.py --check`.
