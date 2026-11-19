---
date:                      # YYYY-MM-DD HH:MM of the original message/event (not of the ingestion)
type: mail                 # mail | meeting | message | ticket | note | image | audio | video | doc | conversation (+ domain types)
from: <slug ou nom>        # person slug when known
project_hint:              # slug when known, else empty
raw:                       # inbox/_raw/<file> | none (pasted text)
added:                     # YYYY-MM-DD HH:MM (by /add)
---

<!-- File name: inbox/AAAA-MM-JJ_<type>_<slug>.md -> moved to inbox/_processed/ by /ingest.
     Normalized content: signatures, disclaimers, quoted history and tracking noise removed.
     Keep the original language. For images: what is shown + extracted text. For audio/video: transcript.
     type conversation (written by /wrap): only what the owner said or decided in a Claude conversation and that is
     not yet in the repo, one section per kind (Décisions · Tâches et temps · Infos projets/personnes · Réponses aux
     questions · Préférences doppel), each line quoting or closely paraphrasing the owner. from: owner. -->

## Contenu
