"""Harbour Sports Club: a one-page membership registration, also available as a JSON API."""
from __future__ import annotations

import re
from datetime import date, timedelta
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

from app.forms.base import Condition, ErrorCode, FieldSpec, FormSpec, Issue, Option, age_on, fail, today_from
from app.forms.fields import Email, Name, Phone, in_range

STUDENT_ID = re.compile(r"^[A-Z0-9]{6,12}$")
MAX_START_DAYS = 90


class Membership(StrEnum):
    ADULT = "adult"
    STUDENT = "student"
    FAMILY = "family"
    OFF_PEAK = "off_peak"


class Interest(StrEnum):
    SWIMMING = "swimming"
    TENNIS = "tennis"
    GYM = "gym"
    YOGA = "yoga"
    SQUASH = "squash"
    CLIMBING = "climbing"


INTEREST_ALSO = {
    Interest.SWIMMING: ["swim", "pool", "lane swimming"],
    Interest.TENNIS: ["tennis courts"],
    Interest.GYM: ["fitness", "weights", "strength"],
    Interest.YOGA: ["pilates", "stretching"],
    Interest.SQUASH: ["squash courts"],
    Interest.CLIMBING: ["bouldering", "climb", "climbing wall"],
}


class Referral(StrEnum):
    FRIEND = "friend"
    SOCIAL = "social"
    SEARCH = "search"
    EVENT = "event"
    OTHER = "other"


class ClubMembership(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    full_name: Name
    email: Email
    phone: Phone
    date_of_birth: date
    membership_type: Membership
    student_id: str | None = None
    family_members: int | None = Field(default=None, ge=2, le=6)
    start_date: date
    interests: list[Interest] = Field(min_length=1)
    emergency_contact_name: Name
    emergency_contact_phone: Phone
    how_heard: Referral | None = None
    accept_terms: bool

    @field_validator("date_of_birth")
    @classmethod
    def _age(cls, v: date, info: ValidationInfo) -> date:
        age = age_on(v, today_from(info))
        if age < 16 or age > 110:
            raise fail(ErrorCode.OUT_OF_RANGE, "Members must be 16 or older.")
        return v

    @field_validator("start_date")
    @classmethod
    def _start(cls, v: date, info: ValidationInfo) -> date:
        today = today_from(info)
        in_range(v, today, today + timedelta(days=MAX_START_DAYS), "The start date")
        return v

    @field_validator("student_id")
    @classmethod
    def _student_id(cls, v: str | None) -> str | None:
        if v is None or not v.strip():
            return None
        v = re.sub(r"[\s-]", "", v.upper())
        if not STUDENT_ID.match(v):
            raise fail(ErrorCode.INVALID_FORMAT, "Student ID must be 6 to 12 letters or digits.")
        return v

    @field_validator("interests")
    @classmethod
    def _unique(cls, v: list[Interest]) -> list[Interest]:
        return list(dict.fromkeys(v))

    @field_validator("accept_terms")
    @classmethod
    def _terms(cls, v: bool) -> bool:
        if v is not True:
            raise fail(ErrorCode.MUST_ACCEPT, "The membership terms must be accepted.")
        return v

    def cross_field_issues(self, today: date) -> list[Issue]:
        out: list[Issue] = []
        student = self.membership_type == Membership.STUDENT
        family = self.membership_type == Membership.FAMILY
        if student and not self.student_id:
            out.append(Issue(field="student_id", code=ErrorCode.CONDITIONAL_REQUIRED,
                             message="Required for a student membership."))
        if not student and self.student_id:
            out.append(Issue(field="student_id", code=ErrorCode.NOT_APPLICABLE,
                             message="Only for student memberships."))
        if family and self.family_members is None:
            out.append(Issue(field="family_members", code=ErrorCode.CONDITIONAL_REQUIRED,
                             message="Required for a family membership."))
        if not family and self.family_members is not None:
            out.append(Issue(field="family_members", code=ErrorCode.NOT_APPLICABLE,
                             message="Only for family memberships."))
        if self.emergency_contact_phone == self.phone:
            out.append(Issue(field="emergency_contact_phone", code=ErrorCode.INVALID_PHONE,
                             message="The emergency contact needs a different number from the member's."))
        return out


CLUB = FormSpec(
    id="harbour-membership",
    name="Membership registration",
    portal="Harbour Sports Club",
    url_path="/portals/harbour/join",
    api_path="/api/portals/harbour/members",
    lookup_path="/api/portals/harbour/members",
    ref_pattern=r"HSC-\d{6}",
    steps=["Details"],
    signoff_required=True,
    model=ClubMembership,
    fields=[
        FieldSpec(name="full_name", label="Full name", type="text", required=True,
                  aliases=["name", "member_name", "applicant_name"]),
        FieldSpec(name="email", label="Email", type="email", required=True, aliases=["email_address", "mail"]),
        FieldSpec(name="phone", label="Phone", type="phone", required=True,
                  aliases=["mobile_no", "mobile", "phone_number", "tel"]),
        FieldSpec(name="date_of_birth", label="Date of birth", type="date", required=True,
                  hint="YYYY-MM-DD; members are 16 or older", aliases=["dob", "birth_date"]),
        FieldSpec(name="membership_type", label="Membership", type="select", required=True,
                  options=[Option(value="adult", label="Adult", also=["standard", "full", "individual"]),
                           Option(value="student", label="Student", also=["uni", "university", "student rate"]),
                           Option(value="family", label="Family", also=["household", "family plan"]),
                           Option(value="off_peak", label="Off-peak", also=["off peak", "offpeak", "daytime"])],
                  aliases=["plan", "membership", "tier"]),
        FieldSpec(name="student_id", label="Student card number", type="text", required=True,
                  when=Condition(field="membership_type", values=["student"]), hint="6 to 12 letters or digits",
                  aliases=["student_card", "nus_number"]),
        FieldSpec(name="family_members", label="People on the membership", type="number", required=True,
                  when=Condition(field="membership_type", values=["family"]), hint="2 to 6",
                  aliases=["household_size", "members_count"]),
        FieldSpec(name="start_date", label="Start date", type="date", required=True,
                  hint=f"today to {MAX_START_DAYS} days ahead", aliases=["joining_date", "start"]),
        FieldSpec(name="interests", label="Interests", type="multiselect", required=True,
                  options=[Option(value=i.value, label=i.value.capitalize(), also=INTEREST_ALSO[i]) for i in Interest],
                  aliases=["activities", "sports"]),
        FieldSpec(name="emergency_contact_name", label="Emergency contact name", type="text", required=True,
                  aliases=["ice_name", "next_of_kin"]),
        FieldSpec(name="emergency_contact_phone", label="Emergency contact phone", type="phone", required=True,
                  aliases=["ice_phone", "next_of_kin_phone"]),
        FieldSpec(name="how_heard", label="How did you hear about us?", type="select",
                  options=[Option(value="friend", label="A friend",
                                  also=["friend", "word of mouth", "referral", "colleague"]),
                           Option(value="social", label="Social media",
                                  also=["instagram", "facebook", "tiktok", "twitter", "x", "social"]),
                           Option(value="search", label="Search engine",
                                  also=["google", "bing", "search", "online search"]),
                           Option(value="event", label="Local event", also=["event", "open day", "fair", "festival"]),
                           Option(value="other", label="Other")],
                  aliases=["referral", "source", "how_did_you_hear", "heard_about_us", "referral_source"]),
        FieldSpec(name="accept_terms", label="I accept the membership terms", type="checkbox", required=True,
                  aliases=["terms", "consent", "terms_accepted", "accepted_terms", "agreed_terms"]),
    ],
)
for _f in CLUB.fields:
    _f.test_id = f"hsc-{_f.name.replace('_', '-')}"
