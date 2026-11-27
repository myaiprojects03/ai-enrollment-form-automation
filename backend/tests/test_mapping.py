"""The mapper (rules, then the AI for the rest) and the outcome it leads to. No database, no network: the AI is a
fake that records what it was sent, so the tests can also prove what never leaves the system."""
from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from typing import Any

from app.forms.base import Outcome
from app.forms.registry import get_form
from app.mapping.llm import LLMError
from app.mapping.mapper import Mapper, shape
from app.mapping.result import MappingResult
from app.validation.outcome import Verdict, judge
from tests.conftest import TODAY, academy_adult, club_adult

ACADEMY = get_form("riverside-enrollment")
CLUB = get_form("harbour-membership")
T = 0.85


class FakeLLM:
    name = "fake:test"

    def __init__(self, answer: dict[str, Any] | Callable[[dict[str, Any]], dict[str, Any]] | Exception):
        self.answer = answer
        self.prompts: list[dict[str, Any]] = []

    async def json(self, system: str, user: str, schema: dict[str, Any]) -> dict[str, Any]:
        payload = json.loads(user)
        self.prompts.append(payload)
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer(payload) if callable(self.answer) else self.answer


def run(form_id: str, record: dict[str, Any], llm: FakeLLM | None = None) -> tuple[MappingResult, Verdict]:
    form = get_form(form_id)
    mapping = asyncio.run(Mapper(llm).map(form, record, TODAY))
    return mapping, judge(form, mapping, TODAY, T)


def codes(v: Verdict, severity: str | None = None) -> set[str]:
    return {r.code for r in v.reasons if severity is None or r.severity == severity}


# ------------------------------------------------------------------ rules alone

def test_clean_record_passes_without_any_ai() -> None:
    mapping, v = run("riverside-enrollment", academy_adult())
    assert v.outcome == Outcome.PASS and v.status == "approved"
    assert mapping.mapper == "rules" and not mapping.llm_needed
    assert v.payload["phone"] == "+447911123456" and v.payload["postcode"] == "LS1 4AP"
    assert v.payload["prior_enrollment"] is False and v.payload["marketing_opt_in"] is False


def test_messy_export_headers_map_by_label_and_alias() -> None:
    record = {"Forename": "AMARA", "Surname": "okafor", "D.O.B": "14/05/1998", "E-mail": "Amara.Okafor@Example.com",
              "Mobile No": "07911 123456", "Course": "Data Analytics", "Intake": "Jan 2027", "Mode": "PT",
              "Street": "14 Mill Lane", "Town": "Leeds", "Post Code": "ls1 4ap", "Terms": "Yes"}
    mapping, v = run("riverside-enrollment", record)
    assert v.outcome == Outcome.PASS, v.reasons
    assert v.payload["first_name"] == "Amara" and v.payload["last_name"] == "Okafor"
    assert v.payload["program"] == "data-analytics" and v.payload["start_term"] == "2027-01"
    assert mapping.fields["first_name"].assumption   # capitalisation changed, and said so
    assert codes(v, "info") >= {"ASSUMPTION"}


def test_full_name_and_one_line_address_are_split() -> None:
    record = {"Name": "Amara Okafor", "DOB": "1998-05-14", "Email": "amara@example.com", "Phone": "07911 123456",
              "Programme": "Cyber Security Essentials", "Start": "September 2027", "Study mode": "Online",
              "Address": "14 Mill Lane, Headingley, Leeds, LS6 3HN", "Consent": "agreed"}
    mapping, v = run("riverside-enrollment", record)
    p = v.payload
    assert (p["first_name"], p["last_name"]) == ("Amara", "Okafor")
    assert (p["address_line1"], p["address_line2"], p["city"], p["postcode"]) == (
        "14 Mill Lane", "Headingley", "Leeds", "LS6 3HN")
    assert mapping.fields["city"].method == "derived"
    assert v.outcome == Outcome.PASS


def test_three_part_name_is_split_but_sent_to_a_person() -> None:
    _, v = run("riverside-enrollment", {**academy_adult(), "first_name": None, "last_name": None,
                                        "Name": "Mary Ann Smith"})
    assert v.outcome == Outcome.NEEDS_REVIEW
    assert {r.field for r in v.reasons if r.code == "LOW_CONFIDENCE"} >= {"first_name", "last_name"}


def test_first_and_last_are_joined_for_a_full_name_form() -> None:
    record = {**club_adult(), "First name": "Sofia", "Surname": "Marin"}
    del record["full_name"]
    _, v = run("harbour-membership", record)
    assert v.payload["full_name"] == "Sofia Marin"


def test_two_columns_that_disagree_make_the_field_ambiguous() -> None:
    record = {**academy_adult(), "Mobile": "07400 999888"}
    mapping, v = run("riverside-enrollment", record)
    assert mapping.fields["phone"].state == "ambiguous"
    assert "AMBIGUOUS_FIELD" in codes(v, "review") and v.outcome == Outcome.NEEDS_REVIEW


def test_two_columns_that_agree_are_fine() -> None:
    _, v = run("riverside-enrollment", {**academy_adult(), "Mobile": "07911 123456"})
    assert v.outcome == Outcome.PASS


def test_uncertain_date_goes_to_review_not_through() -> None:
    _, v = run("riverside-enrollment", academy_adult(date_of_birth="03/04/1999"))
    assert v.outcome == Outcome.NEEDS_REVIEW
    assert any(r.code == "LOW_CONFIDENCE" and r.field == "date_of_birth" for r in v.reasons)


def test_consent_is_never_assumed() -> None:
    record = academy_adult()
    del record["consent_terms"]
    _, v = run("riverside-enrollment", record)
    assert v.outcome == Outcome.BLOCKED
    assert any(r.field == "consent_terms" and r.severity == "block" for r in v.reasons)


def test_refused_consent_and_age_block() -> None:
    _, v = run("riverside-enrollment", academy_adult(consent_terms="no", date_of_birth="2016-01-01"))
    assert v.outcome == Outcome.BLOCKED
    assert {"MUST_ACCEPT", "OUT_OF_RANGE"} <= codes(v, "block")


def test_a_format_problem_on_a_mapped_value_is_for_review() -> None:
    _, v = run("riverside-enrollment", academy_adult(phone="12345"))
    assert v.outcome == Outcome.NEEDS_REVIEW
    assert "INVALID_PHONE" in codes(v, "review")


def test_minor_without_guardian_is_blocked_and_says_why() -> None:
    _, v = run("riverside-enrollment", academy_adult(date_of_birth="2010-02-03"))
    assert v.outcome == Outcome.BLOCKED
    assert {r.field for r in v.reasons if r.code == "CONDITIONAL_REQUIRED"} == {
        "guardian_name", "guardian_relationship", "guardian_phone"}


def test_club_needs_signoff_even_when_everything_passes() -> None:
    _, v = run("harbour-membership", club_adult())
    assert v.outcome == Outcome.PASS and v.status == "needs_review" and "SIGNOFF_REQUIRED" in codes(v)


def test_reasons_never_contain_values() -> None:
    record = {**academy_adult(phone="12345", date_of_birth="03/04/1999"), "Mobile": "07400 999888",
              "Shoe size": "9"}
    _, v = run("riverside-enrollment", record)
    text = json.dumps(v.reasons_json())
    for secret in ("12345", "07400", "1999", "amara", "okafor", "Mill Lane"):
        assert secret.lower() not in text.lower()
    assert "'Shoe size'" in text   # column names are fine: they say what was not used


# ------------------------------------------------------------------ with the AI

def test_ai_sees_keys_and_shapes_never_values() -> None:
    record = {**club_adult(membership_type="student"), "Uni card #": "UOL482913", "Why joining": "Get fit for a 10k"}
    llm = FakeLLM({"fields": [{"field": "student_id", "source_keys": ["Uni card #"], "value": None,
                               "confidence": 0.9, "reason": "card number column"}]})
    mapping, v = run("harbour-membership", record, llm)
    assert v.payload["student_id"] == "UOL482913" and mapping.fields["student_id"].method == "llm"
    sent = json.dumps(llm.prompts)
    assert "UOL482913" not in sent and "Get fit" not in sent and "sofia" not in sent.lower()
    assert "XXX999999" in sent      # the shape of the card number
    assert mapping.mapper == "rules+fake:test" and mapping.unused_source_fields == ["Why joining"]


def test_ai_answers_about_unknown_fields_or_invented_keys_are_ignored() -> None:
    record = {**club_adult(membership_type="student"), "Ref no": "UOL482913"}
    llm = FakeLLM({"fields": [
        {"field": "favourite_colour", "source_keys": ["Ref no"], "value": None, "confidence": 1, "reason": "x"},
        {"field": "student_id", "source_keys": ["Student Card Number"], "value": None, "confidence": 1, "reason": "x"},
    ]})
    mapping, v = run("harbour-membership", record, llm)
    assert not mapping.fields["student_id"].resolved
    assert any(r.field == "student_id" and r.severity == "block" for r in v.reasons)


def test_ai_confidence_is_capped() -> None:
    record = {**club_adult(membership_type="student"), "Ref no": "UOL482913"}
    llm = FakeLLM({"fields": [{"field": "student_id", "source_keys": ["Ref no"], "value": None, "confidence": 1.0,
                               "reason": "x"}]})
    mapping, _ = run("harbour-membership", record, llm)
    assert mapping.fields["student_id"].confidence == 0.95


NOTES = """Phone call with Amara Okafor, 24 Nov.
She wants Data Analytics, part time, starting January 2027.
Born 14 May 1998. Mobile 07911 123456, email amara.okafor@example.com.
Lives at 14 Mill Lane, Leeds LS1 4AP. Said yes to the enrollment terms on the call."""


def _notes_answer(extra: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    def item(field: str, value: str, conf: float = 0.9) -> dict[str, Any]:
        return {"field": field, "source_keys": ["notes"], "value": value, "confidence": conf, "reason": "in notes"}
    return {"fields": [item("first_name", "Amara"), item("last_name", "Okafor"), item("date_of_birth", "14 May 1998"),
                       item("email", "amara.okafor@example.com"), item("phone", "07911 123456"),
                       item("program", "data-analytics"), item("start_term", "2027-01"),
                       item("study_mode", "part_time"), item("address_line1", "14 Mill Lane"), item("city", "Leeds"),
                       item("postcode", "LS1 4AP"), item("consent_terms", "yes"), *(extra or [])]}


def test_notes_are_read_by_the_ai_and_consent_goes_to_a_person() -> None:
    mapping, v = run("riverside-enrollment", {"notes": NOTES}, FakeLLM(_notes_answer()))
    assert v.payload["date_of_birth"] == "1998-05-14" and v.payload["phone"] == "+447911123456"
    assert mapping.fields["email"].confidence == 0.9
    assert v.outcome == Outcome.NEEDS_REVIEW
    low = {r.field for r in v.reasons if r.code == "LOW_CONFIDENCE"}
    assert low == {"consent_terms"}


def test_a_value_the_ai_made_up_is_caught() -> None:
    answer = _notes_answer()
    answer["fields"] = [f for f in answer["fields"] if f["field"] != "city"]
    answer["fields"].append({"field": "city", "source_keys": ["notes"], "value": "Manchester", "confidence": 0.95,
                             "reason": "guess"})
    mapping, v = run("riverside-enrollment", {"notes": NOTES}, FakeLLM(answer))
    assert mapping.fields["city"].confidence <= 0.3
    assert "not found in the notes" in (mapping.fields["city"].assumption or "")
    assert any(r.code == "LOW_CONFIDENCE" and r.field == "city" for r in v.reasons)


def test_label_value_lines_in_notes_need_no_ai() -> None:
    text = ("First name: Amara\nLast name: Okafor\nDate of birth: 14/05/1998\nEmail: amara.okafor@example.com\n"
            "Mobile: 07911 123456\nCourse: Web Development Bootcamp\nStart term: April 2027\nStudy mode: Full-time\n"
            "Address line 1: 14 Mill Lane\nCity: Leeds\nPostcode: LS1 4AP\nTerms: yes")
    mapping, v = run("riverside-enrollment", {"notes": text})
    assert v.outcome == Outcome.PASS, v.reasons
    assert not mapping.llm_needed


def test_without_an_ai_free_text_is_blocked_with_the_reason() -> None:
    mapping, v = run("riverside-enrollment", {"notes": NOTES})
    assert mapping.llm_error == "no AI mapper is configured"
    assert v.outcome == Outcome.BLOCKED and "AI_MAPPER_UNAVAILABLE" in codes(v)


def test_ai_failure_keeps_what_the_rules_found() -> None:
    record = {**club_adult(membership_type="student"), "Ref no": "UOL482913"}
    mapping, v = run("harbour-membership", record, FakeLLM(LLMError("the model did not answer in time")))
    assert mapping.llm_error == "the model did not answer in time" and mapping.fields["email"].resolved
    assert "AI_MAPPER_UNAVAILABLE" in codes(v)


def test_ai_is_not_called_when_rules_found_everything() -> None:
    llm = FakeLLM({"fields": []})
    run("riverside-enrollment", {**academy_adult(), "Notes": "Prefers email contact"}, llm)
    assert llm.prompts == []


def test_a_rule_match_on_a_close_column_name() -> None:
    mapping, _ = run("harbour-membership", {**club_adult(membership_type="student"), "Student card": "UOL482913"})
    assert mapping.fields["student_id"].method == "rule" and mapping.fields["student_id"].confidence == 1.0


def test_shape_hides_personal_data_but_keeps_option_words() -> None:
    vocab = ["part time", "full time", "yes", "no", "data analytics"]
    assert shape("Amara Okafor", vocab) == "Xxxxx Xxxxxx"
    assert shape("07911 123456", vocab) == "99999 999999"
    assert shape("amara@example.com", vocab) == "an email address"
    assert shape("Part time", vocab) == '"Part time"'
    assert shape("Okafor", vocab) == "Xxxxxx"


def test_a_whole_name_from_the_notes_is_split_and_an_opt_out_needs_no_review() -> None:
    answer = _notes_answer([{"field": "applicant_full_name", "source_keys": ["notes"], "value": "Amara Okafor",
                             "confidence": 0.9, "reason": "named in notes"},
                            {"field": "marketing_opt_in", "source_keys": ["notes"], "value": "no",
                             "confidence": 0.9, "reason": "declined"}])
    answer["fields"] = [f for f in answer["fields"] if f["field"] not in ("first_name", "last_name")]
    llm = FakeLLM(answer)
    mapping, v = run("riverside-enrollment", {"notes": NOTES}, llm)
    assert (v.payload["first_name"], v.payload["last_name"]) == ("Amara", "Okafor")
    assert mapping.fields["first_name"].confidence == 0.9
    assert v.payload["marketing_opt_in"] is False and mapping.fields["marketing_opt_in"].confidence == 0.9
    assert {r.field for r in v.reasons if r.severity != "info"} == {"consent_terms"}
    assert any(f["field"] == "applicant_full_name" for f in llm.prompts[0]["form_fields"])


def test_a_whole_name_the_ai_made_up_is_caught() -> None:
    answer = _notes_answer([{"field": "applicant_full_name", "source_keys": ["notes"], "value": "Jane Doe",
                             "confidence": 0.9, "reason": "x"}])
    answer["fields"] = [f for f in answer["fields"] if f["field"] not in ("first_name", "last_name")]
    mapping, _ = run("riverside-enrollment", {"notes": NOTES}, FakeLLM(answer))
    assert mapping.fields["first_name"].confidence <= 0.3
