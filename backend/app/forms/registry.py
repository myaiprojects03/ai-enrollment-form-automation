"""All target forms, and the single entry point that checks a payload against one."""
from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, ValidationError

from app.forms.academy import ACADEMY
from app.forms.base import FormSpec, Issue, issues_from
from app.forms.club import CLUB

FORMS: dict[str, FormSpec] = {f.id: f for f in (ACADEMY, CLUB)}


def get_form(form_id: str) -> FormSpec:
    try:
        return FORMS[form_id]
    except KeyError:
        raise KeyError(f"unknown form {form_id!r}; known: {', '.join(FORMS)}") from None


def check_payload(form_id: str, payload: dict[str, Any], today: date | None = None) -> tuple[BaseModel | None,
                                                                                              list[Issue]]:
    """The contract check: the typed model if the payload conforms, else every issue found (field rules first,
    then rules between fields). Issues never contain the submitted values."""
    form = get_form(form_id)
    today = today or date.today()
    try:
        model = form.model.model_validate(payload, context={"today": today})
    except ValidationError as exc:
        return None, issues_from(exc)
    issues = model.cross_field_issues(today)  # type: ignore[attr-defined]
    return (None, issues) if issues else (model, [])
