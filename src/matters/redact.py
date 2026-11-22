"""Secrets out before anything is sent to a model or stored.

Pattern-based, so it errs towards redacting: a false positive costs a word,
a false negative leaks a credential.
"""

import re

_PATTERNS = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
    re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{10,}"),
    re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}"),
    re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}"),
    re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}"),
    re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}"),
    re.compile(r"(?i)\b(?:bearer|basic)\s+[A-Za-z0-9._~+/\-]{16,}=*"),
    re.compile(r"(?i)(?<=://)[^/\s:@]+:[^/\s@]+(?=@)"),  # credentials in URLs
]
_ASSIGNED = re.compile(
    r"(?i)\b([A-Z0-9_]*(?:api[_-]?key|secret|token|passw(?:or)?d|pwd|credential)[A-Z0-9_]*)"
    r"(\s*[:=]\s*)(['\"]?)([^\s'\"]{6,})\3"
)

MARK = "[REDACTED]"


def redact(text: str) -> str:
    for pattern in _PATTERNS:
        text = pattern.sub(MARK, text)
    return _ASSIGNED.sub(lambda m: f"{m.group(1)}{m.group(2)}{MARK}", text)
