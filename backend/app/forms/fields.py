"""Field validators shared by the form models. Each one raises a PydanticCustomError with an ErrorCode, so a
failure reaches reviewers as a stable code and a plain message, never as the rejected value."""
from __future__ import annotations

import re
from datetime import date
from typing import Annotated, Any

import phonenumbers
from email_validator import EmailNotValidError, validate_email
from pydantic import AfterValidator, BeforeValidator, StringConstraints

from app.forms.base import ErrorCode, fail

DEFAULT_REGION = "GB"
POSTCODE = re.compile(r"^(GIR ?0AA|[A-Z]{1,2}\d[A-Z\d]? ?\d[A-Z]{2})$")


def _strip(v: Any) -> Any:
    return v.strip() if isinstance(v, str) else v


def _email(v: str) -> str:
    try:
        return validate_email(v, check_deliverability=False).normalized.lower()
    except EmailNotValidError:
        raise fail(ErrorCode.INVALID_EMAIL, "Not a valid email address.") from None


def _phone(v: str) -> str:
    """Any common way of writing a number -> E.164 (+447700900123). UK numbers may omit the country code."""
    try:
        number = phonenumbers.parse(v, DEFAULT_REGION)
    except phonenumbers.NumberParseException:
        raise fail(ErrorCode.INVALID_PHONE, "Not a valid phone number.") from None
    if not phonenumbers.is_valid_number(number):
        raise fail(ErrorCode.INVALID_PHONE, "Not a valid phone number.")
    return phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164)


def _postcode(v: str) -> str:
    compact = re.sub(r"\s+", "", v.upper())
    if len(compact) < 5 or not POSTCODE.match(compact[:-3] + " " + compact[-3:]):
        raise fail(ErrorCode.INVALID_FORMAT, "Not a valid UK postcode.")
    return compact[:-3] + " " + compact[-3:]


def _name(v: str) -> str:
    v = re.sub(r"\s+", " ", v)
    if not re.fullmatch(r"[^\d@<>{}\[\]\\/]+", v):
        raise fail(ErrorCode.INVALID_FORMAT, "Names cannot contain digits or symbols.")
    return v


Text = Annotated[str, BeforeValidator(_strip), StringConstraints(min_length=1, max_length=120)]
Name = Annotated[str, BeforeValidator(_strip), StringConstraints(min_length=1, max_length=80), AfterValidator(_name)]
Email = Annotated[str, BeforeValidator(_strip), StringConstraints(min_length=1, max_length=254), AfterValidator(_email)]
Phone = Annotated[str, BeforeValidator(_strip), StringConstraints(min_length=1, max_length=32), AfterValidator(_phone)]
Postcode = Annotated[str, BeforeValidator(_strip), StringConstraints(min_length=1, max_length=10),
                     AfterValidator(_postcode)]


def in_range(day: date, low: date, high: date, what: str) -> None:
    if not low <= day <= high:
        raise fail(ErrorCode.OUT_OF_RANGE, f"{what} must be between {low.isoformat()} and {high.isoformat()}.")
