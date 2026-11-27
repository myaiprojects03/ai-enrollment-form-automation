"""Masks personal data in log lines. Installed on the root logger, so no handler can print it by accident."""
from __future__ import annotations

import logging
import re

_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "<email>"),
    # dates: 2008-03-14, 14/03/2008, 14.03.2008
    (re.compile(r"\b(?:\d{4}-\d{1,2}-\d{1,2}|\d{1,2}[/.]\d{1,2}[/.]\d{2,4})\b"), "<date>"),
    # phone numbers and long id numbers: 7+ digits, allowing spaces, dashes, dots, brackets and a leading +
    (re.compile(r"(?<![\w-])\+?\d[\d\s().-]{5,}\d(?![\w-])"), "<number>"),
    # UK postcodes
    (re.compile(r"\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b", re.I), "<postcode>"),
]
# Keys whose values are always hidden when a mapping is logged, whatever they look like.
SENSITIVE_KEYS = re.compile(r"name|email|phone|mobile|birth|dob|address|street|city|post|zip|guardian|contact|"
                            r"student_id|member", re.I)


def mask_text(text: str) -> str:
    for pattern, label in _PATTERNS:
        text = pattern.sub(label, text)
    return text


def mask_value(key: str, value: object) -> object:
    """For structured logs and audit details: hide values of personal fields, mask the rest."""
    if isinstance(value, dict):
        return {k: mask_value(k, v) for k, v in value.items()}
    if isinstance(value, list):
        return [mask_value(key, v) for v in value]
    if SENSITIVE_KEYS.search(key) and value not in (None, "", [], {}):
        return "<hidden>"
    return mask_text(value) if isinstance(value, str) else value


class MaskingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        masked = mask_text(message)
        if masked != message:
            record.msg, record.args = masked, None
        return True


def install() -> None:
    root = logging.getLogger()
    if not any(isinstance(f, MaskingFilter) for f in root.filters):
        root.addFilter(MaskingFilter())
    for handler in root.handlers:
        if not any(isinstance(f, MaskingFilter) for f in handler.filters):
            handler.addFilter(MaskingFilter())
