"""Turn a raw source value into what a form field expects, with an honest confidence.

Every converter returns a Conv: the value, how sure we are (0 to 1), and an assumption in plain words when a choice
was made (03/04/2005 read as 3 April, "AMARA" written as "Amara"). Assumptions may quote the source, so they are
stored encrypted. A value that cannot be converted raises ConvError; a value that converts but will fail the form's
own rules (an impossible phone number) is passed through with low confidence, so validation reports it exactly.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from difflib import SequenceMatcher
from typing import Any

import phonenumbers

from app.forms.base import FieldSpec, Option

DEFAULT_REGION = "GB"


class ConvError(ValueError):
    """The value cannot be read as this field's type. The message never contains the value."""


@dataclass
class Conv:
    value: Any
    confidence: float
    assumption: str | None = None
    candidates: list[str] = field(default_factory=list)   # equally good options: the field is ambiguous


def norm(text: str) -> str:
    """Lowercase words only: 'Part-time (evenings)' -> 'part time evenings'."""
    return " ".join(re.findall(r"[a-z0-9]+", text.lower()))


# ---------------------------------------------------------------- text, names, email, phone, postcode

def to_text(raw: Any) -> Conv:
    s = " ".join(str(raw).split())
    if not s:
        raise ConvError("empty")
    return Conv(s, 1.0)


def _title(word: str) -> str:
    out = word[:1].upper() + word[1:].lower()
    out = re.sub(r"(['\-])(\w)", lambda m: m.group(1) + m.group(2).upper(), out)   # O'Neill, Smith-Jones
    return re.sub(r"^(Mc)(\w)", lambda m: m.group(1) + m.group(2).upper(), out)   # McDonald


def to_name(raw: Any) -> Conv:
    s = to_text(raw).value
    letters = [c for c in s if c.isalpha()]
    if letters and (all(c.isupper() for c in letters) or all(c.islower() for c in letters)):
        fixed = " ".join(_title(w) for w in s.split())
        return Conv(fixed, 0.97, f"Changed the capitalisation of '{s}' to '{fixed}'.")
    return Conv(s, 1.0)


def to_email(raw: Any) -> Conv:
    s = str(raw).strip().removeprefix("mailto:").strip("<> ")
    spelled = re.fullmatch(r"(.+?)\s*[\[(]?\s*at\s*[\])]?\s*(.+?)\s*[\[(]?\s*dot\s*[\])]?\s*(\w+)", s, re.I)
    if "@" not in s and spelled:
        fixed = f"{spelled[1]}@{spelled[2]}.{spelled[3]}".replace(" ", "").lower()
        return Conv(fixed, 0.75, f"Read the spelled-out address '{s}' as '{fixed}'.")
    compact = s.replace(" ", "").lower()
    if compact != s.lower():
        return Conv(compact, 0.9, "Removed spaces from the email address.")
    return Conv(compact, 1.0 if re.fullmatch(r"[^@\s]+@[^@\s]+\.[a-z]{2,}", compact) else 0.5)


def to_phone(raw: Any) -> Conv:
    s = str(raw).strip().replace("(0)", "")
    if not s:
        raise ConvError("empty")
    try:
        number = phonenumbers.parse(s, DEFAULT_REGION)
        if phonenumbers.is_valid_number(number):
            return Conv(phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164), 1.0)
    except phonenumbers.NumberParseException:
        pass
    return Conv(s, 0.5, "Could not read this as a valid phone number; it was left as given.")


def to_postcode(raw: Any) -> Conv:
    compact = re.sub(r"\s+", "", str(raw).upper())
    if not compact:
        raise ConvError("empty")
    if len(compact) >= 5:
        return Conv(compact[:-3] + " " + compact[-3:], 1.0)
    return Conv(compact, 0.5)


# ---------------------------------------------------------------- yes / no

_YES = {"yes", "y", "true", "t", "1", "x", "checked", "on", "agree", "agreed", "i agree", "accept", "accepted",
        "signed", "consented", "ok", "opt in", "opted in", "subscribe"}
_NO = {"no", "n", "false", "f", "0", "off", "unchecked", "declined", "disagree", "none", "opt out", "opted out",
       "unsubscribe", "not given", "no thanks"}


def to_bool(raw: Any) -> Conv:
    if isinstance(raw, bool):
        return Conv(raw, 1.0)
    s = norm(str(raw))
    if s in _YES or str(raw).strip() in {"✓", "✔"}:
        return Conv(True, 1.0)
    if s in _NO:
        return Conv(False, 1.0)
    raise ConvError("not a yes or no")


# ---------------------------------------------------------------- dates

_MONTHS = {m: i for i, names in enumerate(
    [("jan", "january"), ("feb", "february"), ("mar", "march"), ("apr", "april"), ("may",), ("jun", "june"),
     ("jul", "july"), ("aug", "august"), ("sep", "sept", "september"), ("oct", "october"), ("nov", "november"),
     ("dec", "december")], start=1) for m in names}
_LONG = "%d %B %Y"


def _real(y: int, m: int, d: int) -> date:
    try:
        return date(y, m, d)
    except ValueError:
        raise ConvError("not a real date") from None


def _century(yy: int, past: bool, today: date) -> int:
    if not past:
        return 2000 + yy
    return 2000 + yy if 2000 + yy <= today.year else 1900 + yy


def to_date(raw: Any, *, past: bool, today: date) -> Conv:
    """`past` says which century a two-digit year belongs to (a birth date, or a start date)."""
    if isinstance(raw, date):
        return Conv(raw.isoformat(), 1.0)
    s = str(raw).strip()
    if not s:
        raise ConvError("empty")
    s = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", s, flags=re.I).replace(",", " ")
    s = re.sub(r"\bof\b", " ", s, flags=re.I)
    s = " ".join(s.split())

    m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})(?:[T ][\d:.]+Z?)?", s)
    if m:
        return Conv(_real(int(m[1]), int(m[2]), int(m[3])).isoformat(), 1.0)
    m = re.fullmatch(r"(\d{4})[/.](\d{1,2})[/.](\d{1,2})", s)
    if m:
        return Conv(_real(int(m[1]), int(m[2]), int(m[3])).isoformat(), 0.98)

    m = re.fullmatch(r"(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4}|\d{2})", s)
    if m:
        a, b, y = int(m[1]), int(m[2]), int(m[3])
        conf, note = 0.98, None
        if len(m[3]) == 2:
            y = _century(y, past, today)
        if a > 12 >= b:
            d = _real(y, b, a)
        elif b > 12 >= a:
            d = _real(y, a, b)
            conf, note = 0.7, f"Read '{s}' month first (US order), as {d.strftime(_LONG)}."
        elif a == b:
            d = _real(y, a, b)
        else:
            d = _real(y, b, a)
            conf, note = 0.75, f"Read '{s}' day first (UK order), as {d.strftime(_LONG)}; it could also be month first."
        if len(m[3]) == 2:
            conf = min(conf, 0.8)
            note = (note + " " if note else "") + f"Took the two-digit year as {y}."
        return Conv(d.isoformat(), conf, note)

    m = re.fullmatch(r"(\d{1,2})[ \-]([a-z]+)\.?[ \-](\d{4}|\d{2})", s, re.I) or None
    swapped = re.fullmatch(r"([a-z]+)\.? (\d{1,2}) (\d{4}|\d{2})", s, re.I)
    if m or swapped:
        day, month, year = (m[1], m[2], m[3]) if m else (swapped[2], swapped[1], swapped[3])  # type: ignore[index]
        mon = _MONTHS.get(month.lower())
        if mon:
            y = int(year) if len(year) == 4 else _century(int(year), past, today)
            d = _real(y, mon, int(day))
            if len(year) == 2:
                return Conv(d.isoformat(), 0.8, f"Took the two-digit year in '{s}' as {y}.")
            return Conv(d.isoformat(), 0.97)

    m = re.fullmatch(r"(\d{5})(?:\.0+)?", s)
    if m and 20000 <= int(m[1]) <= 60000:   # a spreadsheet date serial that lost its formatting
        d = date(1899, 12, 30) + timedelta(days=int(m[1]))
        return Conv(d.isoformat(), 0.6, f"Read the number {s} as a spreadsheet date, {d.strftime(_LONG)}.")
    raise ConvError("not a date in a known format")


# ---------------------------------------------------------------- numbers

_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
          "ten": 10}


def to_number(raw: Any) -> Conv:
    if isinstance(raw, bool):
        raise ConvError("not a number")
    if isinstance(raw, int):
        return Conv(raw, 1.0)
    if isinstance(raw, float) and raw.is_integer():
        return Conv(int(raw), 1.0)
    s = norm(str(raw))
    if re.fullmatch(r"\d+( 0+)?", s):
        return Conv(int(s.split()[0]), 1.0)
    if s in _WORDS:
        return Conv(_WORDS[s], 0.95)
    found = re.findall(r"\b(\d+|" + "|".join(_WORDS) + r")\b", s)
    if len(found) == 1:
        n = int(found[0]) if found[0].isdigit() else _WORDS[found[0]]
        return Conv(n, 0.8, f"Took the number {n} from '{str(raw).strip()}'.")
    raise ConvError("not a number")


# ---------------------------------------------------------------- options

def _phrases(o: Option) -> list[str]:
    return [norm(o.value), norm(o.label), *(norm(a) for a in o.also)]


def to_option(raw: Any, options: list[Option]) -> Conv:
    s = norm(str(raw))
    if not s:
        raise ConvError("empty")
    for o in options:
        if s in (norm(o.value), norm(o.label)):
            return Conv(o.value, 1.0)
    for o in options:
        if s in (norm(a) for a in o.also):
            return Conv(o.value, 0.95, f"Matched '{str(raw).strip()}' to '{o.label}'.")
    # A known phrase inside a longer answer: "Part time (evenings)".
    inside = [o for o in options if any(p and re.search(rf"\b{re.escape(p)}\b", s) for p in _phrases(o))]
    if len(inside) == 1:
        return Conv(inside[0].value, 0.85, f"Matched '{str(raw).strip()}' to '{inside[0].label}'.")
    if len(inside) > 1:
        return Conv(inside[0].value, 0.5, f"'{str(raw).strip()}' could be any of: "
                    + ", ".join(o.label for o in inside) + ".", [o.value for o in inside])
    # Typos: "Data Analitics".
    scored = sorted(((max(SequenceMatcher(None, s, p).ratio() for p in _phrases(o) if p), o) for o in options),
                    key=lambda t: t[0], reverse=True)
    best, top = scored[0]
    if best >= 0.75:
        if len(scored) > 1 and best - scored[1][0] < 0.05:
            return Conv(top.value, 0.5, f"'{str(raw).strip()}' is close to both '{top.label}' and "
                        f"'{scored[1][1].label}'.", [top.value, scored[1][1].value])
        return Conv(top.value, round(min(0.9, best * 0.9), 2), f"Read '{str(raw).strip()}' as '{top.label}'.")
    raise ConvError("not one of the options")


def to_options(raw: Any, options: list[Option]) -> Conv:
    items = raw if isinstance(raw, list) else re.split(r"\s*(?:[,;/|+]|\band\b|&)\s*", str(raw))
    items = [i for i in items if str(i).strip()]
    if not items:
        raise ConvError("empty")
    values, conf, notes, dropped = [], 1.0, [], []
    for item in items:
        try:
            c = to_option(item, options)
        except ConvError:
            dropped.append(str(item).strip())
            continue
        if c.value not in values:
            values.append(c.value)
        conf = min(conf, c.confidence)
        if c.assumption:
            notes.append(c.assumption)
    if not values:
        raise ConvError("none of the options")
    if dropped:
        conf = min(conf, 0.6)
        notes.append("Left out answers that are not options: " + ", ".join(f"'{d}'" for d in dropped) + ".")
    return Conv(values, conf, " ".join(notes) or None)


# ---------------------------------------------------------------- dispatch

def convert(spec: FieldSpec, raw: Any, today: date) -> Conv:
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        raise ConvError("empty")
    t = spec.type
    if t == "email":
        return to_email(raw)
    if t == "phone":
        return to_phone(raw)
    if t == "postcode":
        return to_postcode(raw)
    if t == "date":
        return to_date(raw, past=spec.name == "date_of_birth", today=today)
    if t == "checkbox":
        return to_bool(raw)
    if t == "number":
        return to_number(raw)
    if t == "multiselect":
        return to_options(raw, spec.options)
    if t in ("select", "radio", "combobox"):
        return to_option(raw, spec.options)
    if "name" in spec.name:
        return to_name(raw)
    return to_text(raw)
