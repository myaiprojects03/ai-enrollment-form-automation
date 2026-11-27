"""Does what the portal stored match what we meant to send? Field by field, with each type's own idea of equal."""
from __future__ import annotations

import re
from typing import Any

from app.forms.base import FormSpec


def same(kind: str, ours: Any, theirs: Any) -> bool:
    if ours is None or ours == "" or ours == []:
        return theirs in (None, "", [], False)
    if kind == "checkbox":
        return bool(ours) == (theirs is True or str(theirs).lower() in ("true", "yes", "on", "1"))
    if kind == "phone":
        return re.sub(r"\D", "", str(ours))[-10:] == re.sub(r"\D", "", str(theirs or ""))[-10:]
    if kind == "multiselect":
        return sorted(map(str, ours)) == sorted(map(str, theirs or []))
    if kind == "number":
        try:
            return int(ours) == int(theirs)
        except (TypeError, ValueError):
            return False
    if kind == "postcode":
        return re.sub(r"\s", "", str(ours)).upper() == re.sub(r"\s", "", str(theirs or "")).upper()
    return " ".join(str(ours).split()).lower() == " ".join(str(theirs or "").split()).lower()


def mismatches(form: FormSpec, payload: dict[str, Any], stored: dict[str, Any]) -> list[str]:
    """Field names whose stored value differs from ours. Fields the portal does not keep are not compared."""
    out = []
    for spec in form.fields:
        if spec.name not in payload and spec.name not in stored:
            continue
        if spec.name not in stored and payload.get(spec.name) in (None, False, "", []):
            continue
        if not same(spec.type, payload.get(spec.name), stored.get(spec.name)):
            out.append(spec.name)
    return out
