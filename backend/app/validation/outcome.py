"""PASS, NEEDS_REVIEW or BLOCKED, with the exact reasons. Deterministic: the same mapping always gets the same
outcome, and no model is involved.

- BLOCKED: the form would refuse the record, and the fix needs the applicant (no consent, too young, a required
  answer missing from the source). A reviewer can still correct it, then it is checked again.
- NEEDS_REVIEW: it might be right, but a person should look: a field mapped below the confidence threshold, two
  source fields that disagree, a value in the wrong format, a possible duplicate, data the AI could not read.
- PASS: every rule met and every field above the threshold.

Reasons name fields and source columns, never values, because they are stored and shown without decryption.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

from app.forms.base import ErrorCode, FormSpec, Issue, Outcome
from app.forms.registry import check_payload
from app.mapping.result import MappingResult

Severity = Literal["block", "review", "info"]

# Issues the applicant has to resolve.
APPLICANT_ONLY = {ErrorCode.MUST_ACCEPT, ErrorCode.OUT_OF_RANGE}
MISSING = {ErrorCode.REQUIRED_MISSING, ErrorCode.CONDITIONAL_REQUIRED}


@dataclass
class Reason:
    code: str
    message: str
    severity: Severity
    field: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"code": self.code, "field": self.field, "message": self.message, "severity": self.severity}


@dataclass
class Verdict:
    outcome: Outcome
    reasons: list[Reason]
    payload: dict[str, Any]
    status: str           # what the enrollment becomes: approved, needs_review or blocked

    def reasons_json(self) -> list[dict[str, Any]]:
        return [r.as_dict() for r in self.reasons]


def _label(form: FormSpec, name: str) -> str:
    try:
        return form.field(name).label
    except StopIteration:
        return name


def judge(form: FormSpec, mapping: MappingResult, today: date, threshold: float,
          possible_duplicates: list[str] | None = None) -> Verdict:
    payload = mapping.payload()
    model, issues = check_payload(form.id, payload, today)
    if model is not None:
        # The form's own normalising (E.164 phones, upper-case IDs, ISO dates) is what gets submitted and compared.
        payload = model.model_dump(mode="json", exclude_none=True)
    reasons: list[Reason] = []
    low = {n for n, f in mapping.fields.items() if f.resolved and f.confidence < threshold and f.method != "edited"}

    for issue in issues:
        reasons.append(_from_issue(form, mapping, issue, low))

    for name, f in mapping.fields.items():
        if f.state == "ambiguous" and f.method != "edited":
            others = ", ".join(f"'{c}'" for c in f.candidates)
            reasons.append(Reason("AMBIGUOUS_FIELD", f"{_label(form, name)}: more than one possible answer "
                                  f"({others}). Choose the right one.", "review", name))
        elif name in low:
            src = ", ".join(f"'{s}'" for s in f.source_fields) or "the source"
            reasons.append(Reason("LOW_CONFIDENCE", f"{_label(form, name)} was mapped from {src} with "
                                  f"{round(f.confidence * 100)}% confidence (threshold "
                                  f"{round(threshold * 100)}%). Check it.", "review", name))
        elif f.resolved and f.assumption and f.method not in ("edited", "default"):
            reasons.append(Reason("ASSUMPTION", f"{_label(form, name)}: an assumption was made while mapping; it "
                                  "is shown with the field.", "info", name))

    if possible_duplicates:
        reasons.append(Reason("POSSIBLE_DUPLICATE", "The same applicant is already in: "
                              + ", ".join(possible_duplicates) + ".", "review"))
    if mapping.llm_needed and mapping.llm_error and any(r.severity != "info" for r in reasons):
        reasons.append(Reason("AI_MAPPER_UNAVAILABLE", f"Some source data needed the AI mapper, which was not used "
                              f"({mapping.llm_error}).", "review"))
    if mapping.unused_source_fields:
        reasons.append(Reason("UNUSED_SOURCE_FIELDS", "Not used for any field: "
                              + ", ".join(f"'{k}'" for k in mapping.unused_source_fields[:12])
                              + ("..." if len(mapping.unused_source_fields) > 12 else "") + ".", "info"))

    if any(r.severity == "block" for r in reasons):
        outcome = Outcome.BLOCKED
    elif any(r.severity == "review" for r in reasons):
        outcome = Outcome.NEEDS_REVIEW
    else:
        outcome = Outcome.PASS

    status = {Outcome.BLOCKED: "blocked", Outcome.NEEDS_REVIEW: "needs_review", Outcome.PASS: "approved"}[outcome]
    if outcome == Outcome.PASS and form.signoff_required:
        status = "needs_review"
        reasons.append(Reason("SIGNOFF_REQUIRED", f"{form.portal} asks for a person to approve every submission.",
                              "info"))
    order = {"block": 0, "review": 1, "info": 2}
    reasons.sort(key=lambda r: order[r.severity])
    return Verdict(outcome, reasons, payload, status)


def _from_issue(form: FormSpec, mapping: MappingResult, issue: Issue, low: set[str]) -> Reason:
    f = mapping.fields.get(issue.field)
    mapped = bool(f and f.resolved)
    label = _label(form, issue.field)
    message = f"{label}: {issue.message}"
    if issue.code in MISSING and not mapped:
        hint = (" It may be in source data the AI mapper could not read." if mapping.llm_error
                else " Ask the applicant.")
        return Reason(issue.code, f"{label}: not found in the source. {issue.message}{hint}", "block", issue.field)
    if issue.code in APPLICANT_ONLY and issue.field not in low:
        return Reason(issue.code, message, "block", issue.field)
    # A format problem on a value we did map: likely a typo, or the wrong source column. A person can fix it.
    return Reason(issue.code, message, "review", issue.field)
