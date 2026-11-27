import typing
from enum import Enum

import pytest

from app.forms.base import ErrorCode
from app.forms.registry import FORMS, check_payload
from tests.conftest import TODAY, academy_adult, academy_minor, club_adult

A, C = "riverside-enrollment", "harbour-membership"


def codes(issues):
    return {(i.field, i.code) for i in issues}


@pytest.mark.parametrize("form", list(FORMS.values()), ids=list(FORMS))
def test_spec_and_model_describe_the_same_fields(form):
    assert form.names == list(form.model.model_fields)
    for f in form.fields:
        assert f.label and f.test_id
        if f.options:  # every option on the form is a value the model accepts, and no more
            hint = form.model.model_fields[f.name].annotation
            enums = [a for a in typing.get_args(hint) or [hint] if isinstance(a, type) and issubclass(a, Enum)]
            for arg in typing.get_args(hint):
                enums += [a for a in typing.get_args(arg) if isinstance(a, type) and issubclass(a, Enum)]
            assert enums, f.name
            assert {o.value for o in f.options} == {e.value for e in enums[0]}, f.name


def test_a_complete_adult_enrollment_passes_and_is_normalised():
    model, issues = check_payload(A, academy_adult(), TODAY)
    assert issues == [] and model is not None
    assert model.phone == "+447911123456" and model.postcode == "LS1 4AP" and model.email == "amara.okafor@example.com"


def test_an_under_18_needs_a_guardian():
    _, issues = check_payload(A, academy_minor(guardian_name=None, guardian_phone=None), TODAY)
    assert codes(issues) == {("guardian_name", ErrorCode.CONDITIONAL_REQUIRED),
                             ("guardian_phone", ErrorCode.CONDITIONAL_REQUIRED)}
    model, issues = check_payload(A, academy_minor(), TODAY)
    assert issues == [] and model is not None


def test_guardian_details_are_refused_for_an_adult():
    _, issues = check_payload(A, academy_adult(guardian_name="Someone"), TODAY)
    assert codes(issues) == {("guardian_name", ErrorCode.NOT_APPLICABLE)}


def test_a_returning_student_needs_a_valid_previous_id():
    _, issues = check_payload(A, academy_adult(prior_enrollment=True), TODAY)
    assert codes(issues) == {("prior_student_id", ErrorCode.CONDITIONAL_REQUIRED)}
    _, issues = check_payload(A, academy_adult(prior_enrollment=True, prior_student_id="RA-12"), TODAY)
    assert codes(issues) == {("prior_student_id", ErrorCode.INVALID_FORMAT)}
    model, issues = check_payload(A, academy_adult(prior_enrollment=True, prior_student_id="ra-123456"), TODAY)
    assert issues == [] and model.prior_student_id == "RA-123456"


def test_every_bad_field_is_reported_at_once_with_a_code():
    bad = academy_adult(email="amara@", phone="12", postcode="NOTAPOSTCODE", program="basket weaving",
                        date_of_birth="2020-01-01", consent_terms=False, first_name="")
    _, issues = check_payload(A, bad, TODAY)
    assert codes(issues) == {("email", ErrorCode.INVALID_EMAIL), ("phone", ErrorCode.INVALID_PHONE),
                             ("postcode", ErrorCode.INVALID_FORMAT), ("program", ErrorCode.NOT_AN_OPTION),
                             ("date_of_birth", ErrorCode.OUT_OF_RANGE), ("consent_terms", ErrorCode.MUST_ACCEPT),
                             ("first_name", ErrorCode.REQUIRED_MISSING)}


def test_missing_and_unknown_fields():
    data = academy_adult(favourite_colour="blue")
    del data["city"]
    _, issues = check_payload(A, data, TODAY)
    assert codes(issues) == {("city", ErrorCode.REQUIRED_MISSING), ("favourite_colour", ErrorCode.UNKNOWN_FIELD)}


def test_issues_never_echo_the_submitted_value():
    _, issues = check_payload(A, academy_adult(email="secret.person@nowhere", phone="0000 SECRET"), TODAY)
    text = " ".join(i.message for i in issues)
    assert "secret" not in text.lower() and issues


def test_club_membership_rules():
    model, issues = check_payload(C, club_adult(interests=["yoga", "yoga", "gym"]), TODAY)
    assert issues == [] and model.interests == ["yoga", "gym"]
    _, issues = check_payload(C, club_adult(membership_type="student"), TODAY)
    assert codes(issues) == {("student_id", ErrorCode.CONDITIONAL_REQUIRED)}
    _, issues = check_payload(C, club_adult(membership_type="family", student_id="AB123456"), TODAY)
    assert codes(issues) == {("family_members", ErrorCode.CONDITIONAL_REQUIRED),
                             ("student_id", ErrorCode.NOT_APPLICABLE)}
    _, issues = check_payload(C, club_adult(membership_type="family", family_members=9), TODAY)
    assert codes(issues) == {("family_members", ErrorCode.OUT_OF_RANGE)}


def test_club_dates_and_contacts():
    _, issues = check_payload(C, club_adult(start_date="2026-11-01", date_of_birth="2012-01-01"), TODAY)
    assert codes(issues) == {("start_date", ErrorCode.OUT_OF_RANGE), ("date_of_birth", ErrorCode.OUT_OF_RANGE)}
    _, issues = check_payload(C, club_adult(start_date="2027-06-01"), TODAY)
    assert codes(issues) == {("start_date", ErrorCode.OUT_OF_RANGE)}
    _, issues = check_payload(C, club_adult(emergency_contact_phone="+447800345678"), TODAY)
    assert codes(issues) == {("emergency_contact_phone", ErrorCode.INVALID_PHONE)}
    _, issues = check_payload(C, club_adult(interests=[]), TODAY)
    assert codes(issues) == {("interests", ErrorCode.REQUIRED_MISSING)}


def test_unknown_form():
    with pytest.raises(KeyError):
        check_payload("nope", {}, TODAY)
