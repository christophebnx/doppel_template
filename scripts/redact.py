"""Redaction of secrets and private identifiers in free text (signals, evidence).  PROTECTED.

  redact(text) -> (masked_text, [(line, kind), …])   secrets reported with line numbers, never values.
"""
from __future__ import annotations

import re

SECRET_KEY = r"(?:password|passwd|pwd|secret|token|api[_-]?key|apikey|access[_-]?key|secret[_-]?key|private[_-]?key|client[_-]?secret|auth[_-]?token|credentials?|bearer)"
SECRET_PATTERNS = [
    ("private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S)),
    ("credential in URL", re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s/:@]+:[^\s/@]+@[^\s'\"]+", re.I)),
    ("aws access key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("github token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    ("slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b")),
    ("stripe-like key", re.compile(r"\b(?:sk|pk|rk)_(?:live|test)_[A-Za-z0-9]{10,}\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")),
    ("secret assignment", re.compile(rf"(?i)({SECRET_KEY}[A-Za-z0-9_]*['\"]?\s*[:=]\s*)(['\"]?)([^\s'\"#,;}}]+)(['\"]?)")),
    ("secret header", re.compile(r"(?i)(authorization\s*:\s*(?:bearer|basic)\s+)([A-Za-z0-9._~+/=-]{8,})")),
]
PRIVACY_PATTERNS = [
    ("[URL]", re.compile(r"\b(?:https?|s3|gs|abfss?|wasbs?|jdbc:[a-z]+|postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|sftp|ftp|smb)://[^\s'\")<>\]]+", re.I)),
    ("[EMAIL]", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    ("[IP]", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}(?::\d+)?\b")),
    ("[HOST]", re.compile(r"\b(?:[a-z0-9-]+\.)+(?:internal|local|corp|lan|intra|intranet|priv|private|prod|staging|svc|cluster\.local)\b", re.I)),
]
HOST_KEY = re.compile(r"(?i)^(\s*[\"']?(?:host|hostname|server|endpoint|dsn|url|uri|bucket|account)[A-Za-z0-9_]*[\"']?\s*[:=]\s*)(\S.*)$", re.M)
SECRET_PLACEHOLDER = "[SECRET MASQUÉ]"


def redact(text: str) -> tuple[str, list[tuple[int, str]]]:
    """Mask secrets (reported with line numbers, never values), URLs, e-mails, IPs and internal hosts."""
    findings: list[tuple[int, str]] = []

    def line_of(pos: int) -> int:
        return text.count("\n", 0, pos) + 1

    spans = []
    for kind, rx in SECRET_PATTERNS:
        for m in rx.finditer(text):
            if kind == "secret assignment":
                value = m.group(3)
                if len(value) < 4 or value.lower() in {"none", "null", "true", "false", "changeme", "xxx", "***", "[secret"} \
                        or value.startswith(("${", "{{", "os.environ", "env(", "getenv", "$")):
                    continue  # placeholders / env references are not secrets
                spans.append((m.start(3), m.end(3), kind))
            elif kind == "secret header":
                spans.append((m.start(2), m.end(2), kind))
            else:
                spans.append((m.start(), m.end(), kind))
    spans.sort()
    out, pos = [], 0
    for s, e, kind in spans:
        if s < pos:
            continue
        findings.append((line_of(s), kind))
        out.append(text[pos:s])
        out.append(SECRET_PLACEHOLDER)
        pos = e
    out.append(text[pos:])
    text = "".join(out)
    text = HOST_KEY.sub(lambda m: m.group(1) + ("[VALEUR MASQUÉE]" if not m.group(2).strip().startswith(("$", "{{")) else m.group(2)), text)
    for label, rx in PRIVACY_PATTERNS:
        text = rx.sub(label, text)
    return text, findings


# --------------------------------------------------------------------------- limits & workdir
