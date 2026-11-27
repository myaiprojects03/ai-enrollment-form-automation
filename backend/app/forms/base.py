"""The contract every target form is described by: its fields, options, conditions and error codes.

Each form has two halves that must agree (a test checks it):
- a FormSpec: what the mapper and the browser engine need to know (labels, options, steps, conditions);
- a Pydantic model: the strict contract a mapped payload must pass before any submission is attempted.
"""
from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from pydantic_core import PydanticCustomError


class ErrorCode(StrEnum):
    REQUIRED_MISSING = "REQUIRED_MISSING"          # a mandatory field is absent or empty
    CONDITIONAL_REQUIRED = "CONDITIONAL_REQUIRED"  # required because of another field's value
    INVALID_FORMAT = "INVALID_FORMAT"              # wrong shape (postcode, student id, yes/no)
    INVALID_EMAIL = "INVALID_EMAIL"
    INVALID_PHONE = "INVALID_PHONE"
    INVALID_DATE = "INVALID_DATE"
    OUT_OF_RANGE = "OUT_OF_RANGE"                  # dates and numbers outside their allowed range
    NOT_AN_OPTION = "NOT_AN_OPTION"                # not one of the form's dropdown or radio values
    TOO_LONG = "TOO_LONG"
    MUST_ACCEPT = "MUST_ACCEPT"                    # a consent box that must be ticked
    NOT_APPLICABLE = "NOT_APPLICABLE"              # filled although its condition is not met
    UNKNOWN_FIELD = "UNKNOWN_FIELD"                # a key the form does not have


class Outcome(StrEnum):
    PASS = "PASS"                  # every rule passed: ready to submit
    NEEDS_REVIEW = "NEEDS_REVIEW"  # a person must look (low confidence, ambiguity, sign-off)
    BLOCKED = "BLOCKED"            # cannot be submitted as it is


class Issue(BaseModel):
    """One problem with one field. Never carries the field's value (it may be personal data)."""
    field: str
    code: ErrorCode
    message: str


FieldType = Literal["text", "email", "phone", "date", "select", "combobox", "radio", "checkbox", "multiselect",
                    "number", "postcode"]


class Option(BaseModel):
    value: str
    label: str
    also: list[str] = []             # other ways people write it ("FT" for full-time): a hint for the mapper


class Condition(BaseModel):
    """The field applies (and is then required, if marked so) only when `field` has one of `values`."""
    field: str
    values: list[Any]


class FieldSpec(BaseModel):
    name: str
    label: str                       # the visible label on the portal: what browser locators look for first
    type: FieldType
    step: int = 1                    # wizard step on a multi-step form
    required: bool = False
    options: list[Option] = []
    when: Condition | None = None
    hint: str = ""                   # format help for the mapper and reviewers
    aliases: list[str] = []          # common source names (mobile_no -> phone), a hint for the AI mapper
    test_id: str = ""                # data-testid on the portal (one of several locator strategies)


class FormSpec(BaseModel):
    id: str
    name: str
    portal: str                      # the organisation running the form
    url_path: str                    # where the browser form lives on the portal site
    api_path: str = ""               # the portal's API for the same submission ("" = browser only)
    lookup_path: str = ""            # keyed read API: read-back, and finding a submission whose reply was lost
    ref_pattern: str = ""            # what the portal's confirmation reference looks like (a regex)
    steps: list[str] = ["Details"]
    signoff_required: bool = False   # a person approves every final submission
    fields: list[FieldSpec]
    model: type[BaseModel] = Field(exclude=True)
    model_config = ConfigDict(arbitrary_types_allowed=True)

    def field(self, name: str) -> FieldSpec:
        return next(f for f in self.fields if f.name == name)

    @property
    def names(self) -> list[str]:
        return [f.name for f in self.fields]


# ---- helpers the form models share ----

def today_from(info: Any) -> date:
    ctx = info.context or {} if info is not None else {}
    today = ctx.get("today")
    return today if isinstance(today, date) else date.today()


def age_on(born: date, day: date) -> int:
    return day.year - born.year - ((day.month, day.day) < (born.month, born.day))


def fail(code: ErrorCode, message: str) -> PydanticCustomError:
    return PydanticCustomError(code.value, message)


_BUILTIN: dict[str, ErrorCode] = {
    "missing": ErrorCode.REQUIRED_MISSING,
    "enum": ErrorCode.NOT_AN_OPTION,
    "literal_error": ErrorCode.NOT_AN_OPTION,
    "date_parsing": ErrorCode.INVALID_DATE,
    "date_from_datetime_parsing": ErrorCode.INVALID_DATE,
    "date_type": ErrorCode.INVALID_DATE,
    "bool_parsing": ErrorCode.INVALID_FORMAT,
    "bool_type": ErrorCode.INVALID_FORMAT,
    "string_too_long": ErrorCode.TOO_LONG,
    "string_too_short": ErrorCode.REQUIRED_MISSING,
    "extra_forbidden": ErrorCode.UNKNOWN_FIELD,
    "int_parsing": ErrorCode.INVALID_FORMAT,
    "greater_than_equal": ErrorCode.OUT_OF_RANGE,
    "less_than_equal": ErrorCode.OUT_OF_RANGE,
    "too_short": ErrorCode.REQUIRED_MISSING,
    "value_error": ErrorCode.INVALID_FORMAT,
}


def issues_from(exc: ValidationError) -> list[Issue]:
    """Pydantic's errors as the system's own codes, without echoing any input value."""
    out: list[Issue] = []
    for e in exc.errors(include_input=False, include_url=False):
        loc = [str(p) for p in e["loc"] if not isinstance(p, int)]
        field = loc[0] if loc else "__form__"
        kind = e["type"]
        code = ErrorCode(kind) if kind in ErrorCode.__members__ else _BUILTIN.get(kind, ErrorCode.INVALID_FORMAT)
        msg = e["msg"] if kind in ErrorCode.__members__ else _plain(code, e["msg"])
        # model-level checks name their field in the context
        if field == "__form__" and isinstance(e.get("ctx"), dict) and "field" in e["ctx"]:
            field = str(e["ctx"]["field"])
        out.append(Issue(field=field, code=code, message=msg))
    return out


def _plain(code: ErrorCode, msg: str) -> str:
    return {
        ErrorCode.REQUIRED_MISSING: "This field is required.",
        ErrorCode.NOT_AN_OPTION: "Not one of the form's options.",
        ErrorCode.INVALID_DATE: "Not a valid date (YYYY-MM-DD).",
        ErrorCode.UNKNOWN_FIELD: "The form has no such field.",
        ErrorCode.TOO_LONG: "Too long for this field.",
    }.get(code, msg.removeprefix("Value error, "))
