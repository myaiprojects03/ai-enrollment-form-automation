"""The deterministic mapper: source keys to form fields by name, label and known aliases, then a few derived
fields (split a full name, join first and last, split a one-line address). Runs before any AI and needs no network.

Key confidence: an exact name, label or alias is 1.0; the same words with filler removed ("Student First Name") is
0.92; a near spelling ("Emial") is 0.8. The final confidence is the key confidence times the value's own.
"""
from __future__ import annotations

import re
from datetime import date
from difflib import SequenceMatcher
from typing import Any

from app.forms.base import FieldSpec, FormSpec
from app.mapping.result import FieldResult
from app.mapping.values import Conv, ConvError, convert, norm, to_name

FILLER = {"student", "applicant", "member", "members", "the", "your", "s", "of", "please", "enter", "applicants",
          "optional", "contact", "details", "info", "address"}
NAME_KEYS = {"name", "full name", "student name", "applicant name", "student", "applicant", "member name",
             "student full name", "applicant full name", "names"}
FIRST_KEYS = {"first name", "first", "forename", "given name", "fname", "firstname", "first names"}
LAST_KEYS = {"last name", "last", "surname", "family name", "lname", "lastname"}
UK_POSTCODE = re.compile(r"\b([A-Z]{1,2}\d[A-Z\d]?)\s*(\d[A-Z]{2})\b", re.I)


def _strip_filler(text: str) -> str:
    words = [w for w in text.split() if w not in FILLER]
    return " ".join(words) if words else text


def candidates(spec: FieldSpec) -> set[str]:
    return {norm(spec.name.replace("_", " ")), norm(spec.label), *(norm(a.replace("_", " ")) for a in spec.aliases)}


def key_score(spec: FieldSpec, key: str) -> float:
    k = norm(key.replace("_", " "))
    if not k:
        return 0.0
    names = candidates(spec)
    if k in names or k.replace(" ", "") in {n.replace(" ", "") for n in names}:   # "D.O.B" is "dob"
        return 1.0
    if _strip_filler(k) in {_strip_filler(n) for n in names}:
        return 0.92
    if len(k) < 5 or k in NAME_KEYS:   # short words are too easy to confuse ("name" is not "fname")
        return 0.0
    best = max(SequenceMatcher(None, k, n).ratio() for n in names)
    return 0.8 if best >= 0.88 else 0.0


def flatten(record: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    """{"student": {"first": "A"}} -> {"student first": "A"}. Lists of plain values stay lists."""
    out: dict[str, Any] = {}
    for k, v in record.items():
        key = f"{prefix} {k}".strip()
        if isinstance(v, dict):
            out.update(flatten(v, key))
        elif v is None or (isinstance(v, str) and not v.strip()):
            continue
        else:
            out[key] = v
    return out


def _same(a: Any, b: Any) -> bool:
    return norm(str(a)) == norm(str(b))


def match_keys(form: FormSpec, record: dict[str, Any], today: date) -> tuple[dict[str, FieldResult], set[str]]:
    """Each source key goes to at most one field, highest score first. Returns results and the keys used."""
    results = {f.name: FieldResult(field=f.name) for f in form.fields}
    scored = sorted(((key_score(f, k), f, k) for f in form.fields for k in record), key=lambda t: -t[0])
    used: set[str] = set()
    taken: dict[str, float] = {}
    for score, spec, key in scored:
        if score == 0 or key in used:
            continue
        res = results[spec.name]
        if spec.name in taken:
            # A second key, as good as the first, for a field already found: the field is ambiguous
            # unless both say the same thing.
            if score >= taken[spec.name] and not _same(record[key], record[res.source_fields[0]]):
                res.state, res.confidence = "ambiguous", min(res.confidence, 0.5)
                res.candidates.append(key)
                res.note(f"Both '{res.source_fields[0]}' and '{key}' could be the {spec.label.lower()}; "
                         f"used '{res.source_fields[0]}'.")
                used.add(key)
            elif score >= taken[spec.name]:
                res.source_fields.append(key)
                used.add(key)
            continue
        try:
            conv = convert(spec, record[key], today)
        except ConvError:
            continue   # the key looked right but its value is not this field's type; leave the key for others
        used.add(key)
        taken[spec.name] = score
        res.value, res.source_fields, res.method = conv.value, [key], "rule"
        res.confidence = round(score * conv.confidence, 3)
        res.state = "ambiguous" if conv.candidates else "mapped"
        res.candidates = list(conv.candidates)
        if score < 1:
            res.note(f"Matched the source field '{key}' to '{spec.label}'.")
        res.note(conv.assumption)
    return results, used


def _set(res: FieldResult, conv: Conv, keys: list[str], method: str = "derived") -> None:
    res.value, res.confidence, res.source_fields = conv.value, round(conv.confidence, 3), keys
    res.state, res.method = "mapped", method  # type: ignore[assignment]
    res.note(conv.assumption)


def derive(form: FormSpec, record: dict[str, Any], results: dict[str, FieldResult], used: set[str],
           today: date) -> None:
    names = set(form.names)
    free = {k: v for k, v in record.items() if k not in used}
    by_norm = {norm(k.replace("_", " ")): k for k in free}
    by_norm.update({_strip_filler(n): k for n, k in list(by_norm.items()) if _strip_filler(n) not in by_norm})

    # One full name, a form that wants first and last.
    if {"first_name", "last_name"} <= names and not results["first_name"].resolved \
            and not results["last_name"].resolved:
        key = next((by_norm[n] for n in NAME_KEYS if n in by_norm), None)
        if key and isinstance(free[key], str):
            raw = " ".join(free[key].split())
            if "," in raw:   # "Okafor, Amara"
                last, first = (p.strip() for p in raw.split(",", 1))
                conf, note = 0.9, f"Read '{raw}' as surname first."
            else:
                parts = raw.split()
                if len(parts) < 2:
                    parts = []
                first, last = " ".join(parts[:-1]), parts[-1] if parts else ""
                conf = 0.9 if len(parts) == 2 else 0.6
                note = f"Split '{raw}' into first name '{first}' and last name '{last}'." if parts else ""
            if first and last:
                f_conv, l_conv = to_name(first), to_name(last)
                _set(results["first_name"], Conv(f_conv.value, min(conf, f_conv.confidence), note), [key])
                _set(results["last_name"], Conv(l_conv.value, min(conf, l_conv.confidence), f_conv.assumption), [key])
                used.add(key)

    # First and last, a form that wants one full name.
    if "full_name" in names and not results["full_name"].resolved:
        first_key = next((by_norm[n] for n in FIRST_KEYS if n in by_norm), None)
        last_key = next((by_norm[n] for n in LAST_KEYS if n in by_norm), None)
        if first_key and last_key:
            joined = to_name(f"{free[first_key]} {free[last_key]}")
            _set(results["full_name"], Conv(joined.value, min(0.98, joined.confidence), joined.assumption),
                 [first_key, last_key])
            used.update({first_key, last_key})

    # A whole address in one line: "14 Mill Lane, Leeds, LS1 4AP".
    line1 = results.get("address_line1")
    if line1 and line1.resolved and {"city", "postcode"} <= names and not results["postcode"].resolved:
        text = str(line1.value)
        pc = UK_POSTCODE.search(text)
        if pc:
            before = text[:pc.start()].strip(" ,\n")
            parts = [p.strip() for p in re.split(r"[,\n]", before) if p.strip()]
            postcode = f"{pc[1]} {pc[2]}".upper()
            note = "Split the one-line address into street, town and postcode."
            _set(results["postcode"], Conv(postcode, 0.95), line1.source_fields)
            if len(parts) >= 2 and not results["city"].resolved:
                _set(results["city"], Conv(parts[-1], 0.85, note), line1.source_fields)
                if "address_line2" in names and len(parts) > 2 and not results["address_line2"].resolved:
                    _set(results["address_line2"], Conv(", ".join(parts[1:-1]), 0.85), line1.source_fields)
                line1.value = parts[0]
                line1.confidence = min(line1.confidence, 0.9)
                line1.note(note)

    # A previous student id means they studied here before.
    if "prior_enrollment" in names and not results["prior_enrollment"].resolved \
            and results.get("prior_student_id") and results["prior_student_id"].resolved:
        _set(results["prior_enrollment"], Conv(True, 0.9, "Took the previous student ID as a returning student."),
             results["prior_student_id"].source_fields)


def applies(form: FormSpec, spec: FieldSpec, results: dict[str, FieldResult], today: date) -> bool:
    """Whether a conditional field is needed, judged from what is mapped so far. Unknown counts as needed, except
    that an unanswered tick box counts as unticked."""
    if spec.when is None:
        return True
    basis = results.get(spec.when.field)
    if basis is None or not basis.resolved:
        return form.field(spec.when.field).type != "checkbox"
    if spec.when.field == "date_of_birth" and "under_18" in spec.when.values:
        try:
            born = date.fromisoformat(str(basis.value))
        except ValueError:
            return True
        return (today.year - born.year - ((today.month, today.day) < (born.month, born.day))) < 18
    return basis.value in spec.when.values


def defaults(form: FormSpec, results: dict[str, FieldResult]) -> None:
    """Optional marketing consent left blank means no, as an unticked box would. Required consent is never
    assumed: without it the record is blocked."""
    for name in ("marketing_opt_in",):
        if name in results and not results[name].resolved:
            r = results[name]
            r.value, r.confidence, r.state, r.method = False, 1.0, "mapped", "default"
            r.note("Not in the source, so left unticked.")
    if "prior_enrollment" in results and not results["prior_enrollment"].resolved \
            and not (results.get("prior_student_id") and results["prior_student_id"].resolved):
        r = results["prior_enrollment"]
        r.value, r.confidence, r.state, r.method = False, 0.95, "mapped", "default"
        r.note("No previous student ID given, so taken as a first-time student.")
