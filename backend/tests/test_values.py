"""Value converters: what each raw value becomes, and how sure the converter is."""
from __future__ import annotations

import pytest

from app.forms.registry import get_form
from app.mapping.values import (
    ConvError,
    to_bool,
    to_date,
    to_email,
    to_name,
    to_number,
    to_option,
    to_options,
    to_phone,
)
from tests.conftest import TODAY

ACADEMY = get_form("riverside-enrollment")
CLUB = get_form("harbour-membership")


@pytest.mark.parametrize(("raw", "iso", "sure"), [
    ("1998-05-14", "1998-05-14", True),
    ("1998-05-14T00:00:00Z", "1998-05-14", True),
    ("14/05/1998", "1998-05-14", True),          # day > 12: only one reading
    ("14.05.1998", "1998-05-14", True),
    ("14 May 1998", "1998-05-14", True),
    ("May 14th, 1998", "1998-05-14", True),
    ("14th of May 1998", "1998-05-14", True),
    ("05/05/1998", "1998-05-05", True),          # same either way
    ("03/04/2005", "2005-04-03", False),         # UK order assumed, flagged
    ("05/14/1998", "1998-05-14", False),         # only month-first works: US order, flagged
    ("14/05/98", "1998-05-14", False),           # two-digit year
    ("35929", "1998-05-14", False),              # spreadsheet serial
])
def test_dates(raw: str, iso: str, sure: bool) -> None:
    c = to_date(raw, past=True, today=TODAY)
    assert c.value == iso
    assert (c.confidence >= 0.85) is sure
    assert (c.assumption is None) is sure


def test_two_digit_years_follow_the_field() -> None:
    assert to_date("01/02/27", past=False, today=TODAY).value == "2027-02-01"   # a start date
    assert to_date("01/02/27", past=True, today=TODAY).value == "1927-02-01"    # a birth date
    assert to_date("01/02/09", past=True, today=TODAY).value == "2009-02-01"


@pytest.mark.parametrize("raw", ["31/02/2001", "yesterday", "2001-13-01", "", "99/99/9999"])
def test_not_dates(raw: str) -> None:
    with pytest.raises(ConvError):
        to_date(raw, past=True, today=TODAY)


def test_phones() -> None:
    assert to_phone("07911 123456").value == "+447911123456"
    assert to_phone("+44 (0)7911 123456").value == "+447911123456"
    assert to_phone("0044 7911 123456").value == "+447911123456"
    bad = to_phone("12345")
    assert bad.value == "12345" and bad.confidence < 0.85   # passed through for validation to report


def test_emails() -> None:
    assert to_email(" Amara.Okafor@Example.com ").value == "amara.okafor@example.com"
    assert to_email("mailto:amara@example.com").confidence == 1.0
    spelled = to_email("amara at example dot com")
    assert spelled.value == "amara@example.com" and spelled.confidence < 0.85


def test_names() -> None:
    assert to_name("Amara").assumption is None
    assert to_name("AMARA O'NEILL").value == "Amara O'Neill"
    assert to_name("smith-jones").value == "Smith-Jones"
    assert to_name("mcdonald").value == "McDonald"


@pytest.mark.parametrize(("raw", "value"), [("Yes", True), ("y", True), ("X", True), ("I agree", True),
                                            ("No", False), ("0", False), (True, True)])
def test_yes_no(raw: object, value: bool) -> None:
    assert to_bool(raw).value is value


def test_yes_no_refuses_guesses() -> None:
    with pytest.raises(ConvError):
        to_bool("maybe later")


def test_options() -> None:
    mode = ACADEMY.field("study_mode").options
    assert to_option("part_time", mode).confidence == 1.0
    assert to_option("Part-time", mode).confidence == 1.0
    assert to_option("PT", mode).value == "part_time"
    assert to_option("Part time (evenings)", mode).value == "part_time"
    programme = ACADEMY.field("program").options
    typo = to_option("Data Analitics", programme)
    assert typo.value == "data-analytics" and typo.confidence < 1
    term = ACADEMY.field("start_term").options
    assert to_option("Sept 2027", term).value == "2027-09"
    with pytest.raises(ConvError):
        to_option("Underwater basket weaving", programme)


def test_option_that_could_be_two_things_is_ambiguous() -> None:
    programme = ACADEMY.field("program").options
    c = to_option("data and web", programme)
    assert set(c.candidates) == {"data-analytics", "web-development"} and c.confidence < 0.85


def test_many_options() -> None:
    interests = CLUB.field("interests").options
    c = to_options("Swimming; yoga & bouldering", interests)
    assert c.value == ["swimming", "yoga", "climbing"]
    partial = to_options("Swimming, darts", interests)
    assert partial.value == ["swimming"] and partial.confidence <= 0.6 and "darts" in (partial.assumption or "")


def test_numbers() -> None:
    assert to_number("4").value == 4
    assert to_number("four").value == 4
    assert to_number("family of 3").value == 3
    with pytest.raises(ConvError):
        to_number("a few")
