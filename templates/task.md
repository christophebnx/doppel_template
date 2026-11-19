---
id: T-0000                 # scripts/tasks.py new assigns it
project: <slug>
title: <verbe à l'infinitif + objet, en français>
status: todo               # clarify | todo | doing | blocked | waiting | done | dropped
priority: P2               # P1 (must this week) | P2 (should) | P3 (could)
executor: me               # me | doppel | extra executors of config.yaml
estimate_h:                # raw point estimate in hours (correction applied by scripts, never by hand)
estimate_range_h: []       # optional [low, high]
confidence:                # low | medium | high
actual_h:
deadline:                  # YYYY-MM-DD — the day it is DUE (« pour jeudi »)
scheduled_on:              # YYYY-MM-DD — the day the owner wants to DO it (« jeudi »)
scheduled_window:          # optional HH:MM-HH:MM on that day (« jeudi matin » = 08:30-12:30)
depends_on: []             # [T-nnnn, person:<slug>] — what MY work needs (blocked)
waiting_on:                # person:<slug> — status waiting only: someone else must deliver this item
expected_by:               # YYYY-MM-DD date announced by that person (optional)
follow_up_after:           # YYYY-MM-DD computed by scripts/tasks.py (expected_by + 1 workday, else + 3 workdays)
sources: []                # [inbox/_processed/...]
created:
updated:
---

## Contexte
<!-- 2–5 lines, factual. Who asked what, why, constraints. -->

## Questions ouvertes
<!-- each also exists in questions.md as Q-nnn -->

## Progression
<!-- - AAAA-MM-JJ · note courte · source -->
