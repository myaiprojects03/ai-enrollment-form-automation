"""Shared types for both submission paths."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Path = Literal["api", "browser"]


class SubmitError(Exception):
    """One attempt went wrong. `code` decides what happens next; `detail` is safe to store (no personal values)."""

    def __init__(self, code: str, detail: str, *, retryable: bool, field_errors: list[dict[str, str]] | None = None):
        super().__init__(f"{code}: {detail}")
        self.code, self.detail, self.retryable = code, detail, retryable
        self.field_errors = field_errors or []
        self.shots: list[Shot] = []                # what the browser saw, attached on the way out
        self.steps: list[dict[str, Any]] = []


# Codes, and what each one means for the enrollment.
UNAVAILABLE = "PORTAL_UNAVAILABLE"        # 5xx, timeouts, a page that would not load: try again later
REJECTED = "PORTAL_REJECTED"              # the portal refused a field: back to a person
HUMAN_CHECK = "HUMAN_CHECK_REQUIRED"      # a security check (captcha): automation stops, a person finishes
NOT_FOUND = "ELEMENT_NOT_FOUND"           # no locator strategy found a field or button
NOT_SET = "VALUE_NOT_SET"                 # a value did not stick in the form (read back differently)
AUTH = "PORTAL_AUTH_FAILED"               # the portal refused our API key: a configuration problem
NO_CONFIRMATION = "NO_CONFIRMATION"       # submitted, but no reference came back


@dataclass
class Shot:
    label: str
    jpeg: bytes


@dataclass
class AttemptResult:
    confirmation_ref: str
    portal_record: dict[str, Any] | None = None    # what the portal says it stored, when it can be read back
    adopted: bool = False                          # the portal already had it: nothing was sent twice
    steps: list[dict[str, Any]] = field(default_factory=list)
    shots: list[Shot] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class TestModes:
    __test__ = False   # not a pytest test class

    variant: str = ""      # "b": the portal's drifted page
    chaos: str = ""        # slow | flaky | down | lost | captcha

    def query(self) -> str:
        parts = [f"{k}={v}" for k, v in (("variant", self.variant), ("chaos", self.chaos)) if v]
        return ("?" + "&".join(parts)) if parts else ""

    def as_dict(self) -> dict[str, str]:
        return {k: v for k, v in (("variant", self.variant), ("chaos", self.chaos)) if v}
