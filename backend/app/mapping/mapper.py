"""Map one source record onto a form: rules first, the AI only for what the rules could not place.

What the AI sees depends on the record:
- A structured record (CSV row, JSON): only the left-over source *keys* and the *shape* of each value
  ("Xxxxx Xxxxxx", "99999 999999", "email address"). Applicant data does not leave the system. The AI says which
  key holds which field; the value is then read from the record by the same converters the rules use.
- Free text (notes, a letter, PDF text): the text itself, because there is no other way to read it. Every value
  the AI returns must be found in the text; one that is not is kept with low confidence for a person to check.

The AI never sets a value on its own authority: consent read from free text always goes to a person.
"""
from __future__ import annotations

import json
import re
from datetime import date
from difflib import SequenceMatcher
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from app.forms.base import FieldSpec, FormSpec
from app.mapping import rules
from app.mapping.llm import LLMClient, LLMError
from app.mapping.result import FieldResult, MappingResult
from app.mapping.values import ConvError, convert, norm, to_date, to_name

NOTES_KEY = "notes"
LLM_CONFIDENCE_CAP = 0.95          # an AI mapping is never as certain as an exact name match
UNGROUNDED_CAP = 0.3               # a value the AI gave that is not in the text
CONSENT_FROM_TEXT_CAP = 0.7        # consent read from free text is always confirmed by a person
NAME_HELPER = "applicant_full_name"   # asked for alongside first/last: notes usually give one whole name
KV_LINE = re.compile(r"^\s*([A-Za-z][\w /'()&.#-]{0,40}?)\s*(?::|=|\s-\s|\s–\s)\s*(.+?)\s*$")

SCHEMA: dict[str, Any] = {
    "type": "object", "additionalProperties": False, "required": ["fields"],
    "properties": {"fields": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["field", "source_keys", "value", "confidence", "reason"],
        "properties": {
            "field": {"type": "string"},
            "source_keys": {"type": "array", "items": {"type": "string"}},
            "value": {"type": ["string", "null"]},
            "confidence": {"type": "number"},
            "reason": {"type": "string"},
        }}}},
}

SYSTEM = """You map applicant data onto an enrollment form.
Rules:
- Use only information present in the input. Never guess, infer or invent a value.
- Leave out any field the input does not contain. An empty list is a valid answer.
- confidence is between 0 and 1: how sure you are that this input really is this field.
- A consent or terms field may be mapped only if the input explicitly says the person agreed.
- reason: a few words on why, without repeating personal data.
Answer only with JSON that matches the schema."""


class _Item(BaseModel):
    field: str
    source_keys: list[str] = Field(default_factory=list)
    value: str | None = None
    confidence: float = 0.0
    reason: str = ""


class _Answer(BaseModel):
    fields: list[_Item]


# ------------------------------------------------------------------ preparing the input

def split_notes(record: dict[str, Any]) -> tuple[dict[str, Any], str]:
    """Free text plus any "Label: value" lines in it, which the rules can then map like columns."""
    text = str(record.get(NOTES_KEY) or "")
    structured = {k: v for k, v in record.items() if k != NOTES_KEY}
    for line in text.splitlines():
        m = KV_LINE.match(line)
        if m and len(m[2]) <= 200 and m[1].strip().lower() not in structured:
            structured.setdefault(m[1].strip(), m[2])
    return rules.flatten(structured), text


def _vocab(form: FormSpec) -> list[str]:
    words = ["yes", "no", "true", "false", "y", "n"]
    for f in form.fields:
        for o in f.options:
            words += [norm(o.value), norm(o.label), *(norm(a) for a in o.also)]
    return [w for w in words if w]


def shape(value: Any, vocab: list[str]) -> str:
    """What a value looks like, without what it says. Short answers that are plainly option words are kept."""
    if isinstance(value, bool):
        return "yes/no value"
    if isinstance(value, (int, float)):
        return "a number"
    if isinstance(value, list):
        return "a list: " + "; ".join(shape(v, vocab) for v in value[:6])
    s = " ".join(str(value).split())
    if not s:
        return "empty"
    if re.search(r"[^\s@]+@[^\s@]+", s):
        return "an email address"
    n = norm(s)
    if len(s) <= 40 and not re.search(r"\d", s) and any(
            n == w or SequenceMatcher(None, n, w).ratio() >= 0.8 for w in vocab):
        return f'"{s}"'
    masked = re.sub(r"\d", "9", re.sub(r"[A-Z]", "X", re.sub(r"[a-z]", "x", s)))
    return masked[:48] + ("..." if len(masked) > 48 else "")


def _field_brief(spec: FieldSpec) -> dict[str, Any]:
    out: dict[str, Any] = {"field": spec.name, "label": spec.label, "type": spec.type}
    if spec.hint:
        out["hint"] = spec.hint
    if spec.options:
        out["options"] = {o.value: o.label for o in spec.options}
    if spec.aliases:
        out["also_called"] = spec.aliases
    return out


# ------------------------------------------------------------------ grounding free-text answers

_DATEISH = re.compile(r"\b(\d{1,2}(?:st|nd|rd|th)?[ ./-](?:\d{1,2}|[A-Za-z]{3,9})\.?[ ./-]\d{2,4}"
                      r"|\d{4}-\d{1,2}-\d{1,2}"
                      r"|[A-Za-z]{3,9}\.? \d{1,2}(?:st|nd|rd|th)?,? \d{4})\b")


def grounded(spec: FieldSpec, raw: str, converted: Any, text: str, today: date) -> bool:
    t = norm(text)
    if spec.type == "phone":
        digits = re.sub(r"\D", "", str(converted))[-9:]
        return bool(digits) and digits in re.sub(r"\D", "", text)
    if spec.type == "date":
        for found in _DATEISH.findall(text):
            try:
                if to_date(found, past=spec.name == "date_of_birth", today=today).value == converted:
                    return True
            except ConvError:
                continue
        return False
    if spec.options:
        chosen = converted if isinstance(converted, list) else [converted]
        for value in chosen:
            o = next((o for o in spec.options if o.value == value), None)
            phrases = [norm(o.value), norm(o.label), *(norm(a) for a in o.also)] if o else []
            if not any(p and re.search(rf"\b{re.escape(p)}\b", t) for p in phrases):
                return False
        return True
    if spec.type == "checkbox":
        return True   # capped separately: a person confirms consent read from text
    if spec.type == "email":
        return norm(str(converted)) in t or str(converted).lower() in text.lower()
    return bool(norm(raw)) and norm(raw) in t


# ------------------------------------------------------------------ the mapper

class Mapper:
    def __init__(self, llm: LLMClient | None, allow_free_text: bool = True):
        self.llm = llm
        self.allow_free_text = allow_free_text

    async def map(self, form: FormSpec, record: dict[str, Any], today: date) -> MappingResult:
        structured, text = split_notes(record)
        results, used = rules.match_keys(form, structured, today)
        rules.derive(form, structured, results, used, today)
        result = MappingResult(fields=results, mapper="rules")

        missing = [f for f in form.fields if not results[f.name].resolved]
        left = {k: v for k, v in structured.items() if k not in used}
        # The AI is called only when something the form needs is still missing; it is then asked about every
        # missing field, optional ones included.
        needed = any(f.required and rules.applies(form, f, results, today) for f in missing)
        wants_text = needed and bool(text.strip())
        wants_keys = needed and bool(left)
        result.llm_needed = wants_text or wants_keys
        if result.llm_needed and self.llm is None:
            result.llm_error = "no AI mapper is configured"
        elif result.llm_needed and self.llm is not None:
            result.mapper = f"rules+{self.llm.name}"
            try:
                if wants_keys:
                    await self._from_keys(form, missing, left, results, used, today)
                    missing = [f for f in form.fields if not results[f.name].resolved]
                if wants_text and missing:
                    if self.allow_free_text:
                        await self._from_text(form, missing, text, results, today)
                    else:
                        result.llm_error = "reading free text with the AI mapper is switched off"
                result.llm_used = True
            except LLMError as exc:
                result.llm_error = str(exc)

        rules.derive(form, structured, results, used, today)
        rules.defaults(form, results)
        result.unused_source_fields = sorted(k for k in structured if k not in used)
        return result

    async def _ask(self, payload: dict[str, Any]) -> list[_Item]:
        assert self.llm is not None
        raw = await self.llm.json(SYSTEM, json.dumps(payload, ensure_ascii=False, indent=1), SCHEMA)
        try:
            return _Answer.model_validate(raw).fields
        except ValidationError:
            raise LLMError("the model's answer did not match the schema") from None

    async def _from_keys(self, form: FormSpec, missing: list[FieldSpec], left: dict[str, Any],
                         results: dict[str, FieldResult], used: set[str], today: date) -> None:
        vocab = _vocab(form)
        items = await self._ask({
            "task": "For each form field, name the source key or keys that hold it. Values are hidden: you see "
                    "only what each value looks like (X = letter, 9 = digit). Set value to null.",
            "form_fields": [_field_brief(f) for f in missing],
            "source_keys": [{"key": k, "looks_like": shape(v, vocab)} for k, v in left.items()],
        })
        wanted = {f.name: f for f in missing}
        for item in items:
            spec = wanted.get(item.field)
            keys = [k for k in item.source_keys if k in left and k not in used]
            if spec is None or not keys or results[spec.name].resolved:
                continue   # unknown field, invented key, or already placed: ignored
            raw: Any = " ".join(str(left[k]) for k in keys) if spec.type == "text" and len(keys) > 1 else left[keys[0]]
            try:
                conv = convert(spec, raw, today)
            except ConvError:
                continue
            res = results[spec.name]
            res.value, res.source_fields, res.method = conv.value, keys, "llm"
            res.confidence = round(min(max(item.confidence, 0.0), LLM_CONFIDENCE_CAP, conv.confidence), 3)
            res.state = "ambiguous" if conv.candidates else "mapped"
            res.candidates = list(conv.candidates)
            res.note(conv.assumption)
            used.update(keys)

    async def _from_text(self, form: FormSpec, missing: list[FieldSpec], text: str,
                         results: dict[str, FieldResult], today: date) -> None:
        briefs = [_field_brief(f) for f in missing]
        split_name = {"first_name", "last_name"} <= {f.name for f in missing}
        if split_name:
            briefs.append({"field": NAME_HELPER, "label": "The applicant's full name, exactly as written",
                           "type": "text"})
        items = await self._ask({
            "task": "Find these form fields in the notes. For value, copy the words from the notes exactly; for an "
                    "option field you may give the option value. Use source_keys [\"notes\"].",
            "form_fields": briefs,
            "notes": text[:8000],
        })
        wanted = {f.name: f for f in missing}
        for item in items:
            if item.field == NAME_HELPER:
                continue
            spec = wanted.get(item.field)
            if spec is None or item.value is None or not item.value.strip() or results[spec.name].resolved:
                continue
            try:
                conv = convert(spec, item.value, today)
            except ConvError:
                continue
            res = results[spec.name]
            res.value, res.source_fields, res.method = conv.value, [NOTES_KEY], "llm"
            res.confidence = min(max(item.confidence, 0.0), LLM_CONFIDENCE_CAP, conv.confidence)
            res.state = "ambiguous" if conv.candidates else "mapped"
            res.candidates = list(conv.candidates)
            res.note(conv.assumption)
            if not grounded(spec, item.value, conv.value, text, today):
                res.confidence = min(res.confidence, UNGROUNDED_CAP)
                res.note("This value was not found in the notes as written; check it against the original.")
            if spec.type == "checkbox" and conv.value is True:   # saying no is safe to take as read
                res.confidence = min(res.confidence, CONSENT_FROM_TEXT_CAP)
                res.note("Consent read from free text needs a person to confirm it.")
            res.confidence = round(res.confidence, 3)
        if split_name and not results["first_name"].resolved and not results["last_name"].resolved:
            whole = next((i for i in items if i.field == NAME_HELPER and i.value and i.value.strip()), None)
            if whole is not None:
                self._split_name(whole, text, results)

    @staticmethod
    def _split_name(item: _Item, text: str, results: dict[str, FieldResult]) -> None:
        parts = " ".join(str(item.value).split()).split(" ")
        if len(parts) < 2:
            return
        conf = min(max(item.confidence, 0.0), LLM_CONFIDENCE_CAP, 0.9 if len(parts) == 2 else 0.6)
        found = norm(" ".join(parts)) in norm(text)
        if not found:
            conf = min(conf, UNGROUNDED_CAP)
        for name, value in (("first_name", " ".join(parts[:-1])), ("last_name", parts[-1])):
            conv = to_name(value)
            res = results[name]
            res.value, res.source_fields, res.method, res.state = conv.value, [NOTES_KEY], "llm", "mapped"
            res.confidence = round(min(conf, conv.confidence), 3)
            res.note(f"The AI mapper read the name '{' '.join(parts)}' from the notes; it was split into first and "
                     "last name.")
            res.note(conv.assumption)
            if not found:
                res.note("This name was not found in the notes as written; check it against the original.")
