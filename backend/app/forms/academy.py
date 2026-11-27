"""Riverside Academy: a five-step course enrollment with a guardian step for under-18s."""
from __future__ import annotations

import re
from datetime import date
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, ValidationInfo, field_validator

from app.forms.base import Condition, ErrorCode, FieldSpec, FormSpec, Issue, Option, age_on, fail, today_from
from app.forms.fields import Email, Name, Phone, Postcode, Text

PRIOR_ID = re.compile(r"^RA-\d{6}$")


class Program(StrEnum):
    CS_FOUNDATION = "cs-foundation"
    DATA_ANALYTICS = "data-analytics"
    CYBER_SECURITY = "cyber-security"
    BUSINESS_ADMIN = "business-admin"
    GRAPHIC_DESIGN = "graphic-design"
    ACCOUNTING = "accounting"
    WEB_DEVELOPMENT = "web-development"
    PROJECT_MANAGEMENT = "project-management"


PROGRAM_LABELS = {
    Program.CS_FOUNDATION: "Computer Science Foundation",
    Program.DATA_ANALYTICS: "Data Analytics (Level 4)",
    Program.CYBER_SECURITY: "Cyber Security Essentials",
    Program.BUSINESS_ADMIN: "Business Administration",
    Program.GRAPHIC_DESIGN: "Graphic Design",
    Program.ACCOUNTING: "Accounting (AAT Level 3)",
    Program.WEB_DEVELOPMENT: "Web Development Bootcamp",
    Program.PROJECT_MANAGEMENT: "Project Management (PRINCE2)",
}


PROGRAM_ALSO = {
    Program.CS_FOUNDATION: ["computer science", "cs", "comp sci", "computing"],
    Program.DATA_ANALYTICS: ["data analysis", "analytics", "data"],
    Program.CYBER_SECURITY: ["cybersecurity", "cyber", "security", "infosec"],
    Program.BUSINESS_ADMIN: ["business admin", "business", "admin"],
    Program.GRAPHIC_DESIGN: ["graphics", "design"],
    Program.ACCOUNTING: ["accountancy", "accounts", "aat"],
    Program.WEB_DEVELOPMENT: ["web dev", "web", "coding bootcamp", "bootcamp"],
    Program.PROJECT_MANAGEMENT: ["prince2", "pm"],
}


class Term(StrEnum):
    JAN = "2027-01"
    APR = "2027-04"
    SEP = "2027-09"


class StudyMode(StrEnum):
    FULL_TIME = "full_time"
    PART_TIME = "part_time"
    ONLINE = "online"


class Relationship(StrEnum):
    PARENT = "parent"
    GUARDIAN = "guardian"
    OTHER = "other"


class AcademyEnrollment(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    # step 1: student
    first_name: Name
    last_name: Name
    date_of_birth: date
    email: Email
    phone: Phone
    # step 2: guardian (only for students under 18)
    guardian_name: Name | None = None
    guardian_relationship: Relationship | None = None
    guardian_phone: Phone | None = None
    guardian_email: Email | None = None
    # step 3: course
    program: Program
    start_term: Term
    study_mode: StudyMode
    prior_enrollment: bool = False
    prior_student_id: str | None = None
    # step 4: address
    address_line1: Text
    address_line2: Text | None = None
    city: Text
    postcode: Postcode
    # step 5: consent
    consent_terms: bool
    marketing_opt_in: bool = False

    @field_validator("date_of_birth")
    @classmethod
    def _age(cls, v: date, info: ValidationInfo) -> date:
        age = age_on(v, today_from(info))
        if age < 14 or age > 99:
            raise fail(ErrorCode.OUT_OF_RANGE, "Students must be aged 14 to 99.")
        return v

    @field_validator("prior_student_id")
    @classmethod
    def _prior_id(cls, v: str | None) -> str | None:
        if v is None or not v.strip():
            return None
        v = v.strip().upper()
        if not PRIOR_ID.match(v):
            raise fail(ErrorCode.INVALID_FORMAT, "Student ID must look like RA-123456.")
        return v

    @field_validator("consent_terms")
    @classmethod
    def _consent(cls, v: bool) -> bool:
        if v is not True:
            raise fail(ErrorCode.MUST_ACCEPT, "The terms must be accepted to enroll.")
        return v

    def cross_field_issues(self, today: date) -> list[Issue]:
        """Rules between fields, checked once each field is valid on its own."""
        out: list[Issue] = []
        minor = age_on(self.date_of_birth, today) < 18
        guardian = {"guardian_name": self.guardian_name, "guardian_relationship": self.guardian_relationship,
                     "guardian_phone": self.guardian_phone}
        for name, value in guardian.items():
            if minor and value in (None, ""):
                out.append(Issue(field=name, code=ErrorCode.CONDITIONAL_REQUIRED,
                                 message="Required because the student is under 18."))
        if not minor and any(v not in (None, "") for v in [*guardian.values(), self.guardian_email]):
            out.append(Issue(field="guardian_name", code=ErrorCode.NOT_APPLICABLE,
                             message="Guardian details are only taken for students under 18."))
        if minor and self.guardian_phone and self.guardian_phone == self.phone:
            out.append(Issue(field="guardian_phone", code=ErrorCode.INVALID_PHONE,
                             message="The guardian's number must differ from the student's."))
        if self.prior_enrollment and not self.prior_student_id:
            out.append(Issue(field="prior_student_id", code=ErrorCode.CONDITIONAL_REQUIRED,
                             message="Required because the student has enrolled before."))
        if not self.prior_enrollment and self.prior_student_id:
            out.append(Issue(field="prior_student_id", code=ErrorCode.NOT_APPLICABLE,
                             message="Only for students who have enrolled before."))
        return out


_UNDER_18 = Condition(field="date_of_birth", values=["under_18"])
_PRIOR = Condition(field="prior_enrollment", values=[True])

ACADEMY = FormSpec(
    id="riverside-enrollment",
    name="Course enrollment",
    portal="Riverside Academy",
    url_path="/portals/riverside/enroll",
    api_path="",
    lookup_path="/api/portals/riverside/applications",
    ref_pattern=r"RVA-\d{4}-[A-Z2-9]{5}",
    steps=["Student", "Guardian", "Course", "Address", "Review"],
    signoff_required=False,
    model=AcademyEnrollment,
    fields=[
        FieldSpec(name="first_name", label="First name", type="text", step=1, required=True,
                  aliases=["given_name", "forename", "fname", "first"]),
        FieldSpec(name="last_name", label="Last name", type="text", step=1, required=True,
                  aliases=["surname", "family_name", "lname", "last"]),
        FieldSpec(name="date_of_birth", label="Date of birth", type="date", step=1, required=True,
                  hint="YYYY-MM-DD; students are 14 to 99", aliases=["dob", "birth_date", "birthday"]),
        FieldSpec(name="email", label="Email address", type="email", step=1, required=True,
                  aliases=["email_address", "e_mail", "mail"]),
        FieldSpec(name="phone", label="Mobile number", type="phone", step=1, required=True,
                  hint="UK numbers may omit +44", aliases=["mobile_no", "mobile", "phone_number", "cell"]),
        FieldSpec(name="guardian_name", label="Guardian's full name", type="text", step=2, required=True,
                  when=_UNDER_18, aliases=["parent_name", "guardian"]),
        FieldSpec(name="guardian_relationship", label="Relationship to student", type="radio", step=2, required=True,
                  when=_UNDER_18, options=[Option(value="parent", label="Parent",
                                                  also=["mother", "father", "mum", "mom", "dad", "mam"]),
                                           Option(value="guardian", label="Legal guardian", also=["guardian"]),
                                           Option(value="other", label="Other")],
                  aliases=["relationship", "relation", "relationship_to_student"]),
        FieldSpec(name="guardian_phone", label="Guardian's mobile number", type="phone", step=2, required=True,
                  when=_UNDER_18, aliases=["parent_phone", "guardian_mobile"]),
        FieldSpec(name="guardian_email", label="Guardian's email (optional)", type="email", step=2,
                  when=_UNDER_18, aliases=["parent_email"]),
        FieldSpec(name="program", label="Programme", type="combobox", step=3, required=True,
                  options=[Option(value=k.value, label=v, also=PROGRAM_ALSO[k]) for k, v in PROGRAM_LABELS.items()],
                  aliases=["course", "programme", "course_name"]),
        FieldSpec(name="start_term", label="Start term", type="radio", step=3, required=True,
                  options=[Option(value="2027-01", label="January 2027",
                                  also=["jan 2027", "january", "jan", "2027 01"]),
                           Option(value="2027-04", label="April 2027", also=["apr 2027", "april", "apr", "2027 04"]),
                           Option(value="2027-09", label="September 2027",
                                  also=["sep 2027", "sept 2027", "september", "sept", "sep", "2027 09",
                                        "autumn 2027"])],
                  aliases=["intake", "start"]),
        FieldSpec(name="study_mode", label="Study mode", type="select", step=3, required=True,
                  options=[Option(value="full_time", label="Full-time", also=["ft", "full time", "fulltime", "day"]),
                           Option(value="part_time", label="Part-time",
                                  also=["pt", "part time", "parttime", "evenings", "evening"]),
                           Option(value="online", label="Online", also=["remote", "distance", "distance learning"])],
                  aliases=["attendance", "mode"]),
        FieldSpec(name="prior_enrollment", label="I have studied at Riverside Academy before", type="checkbox",
                  step=3, aliases=["returning_student", "previously_enrolled"]),
        FieldSpec(name="prior_student_id", label="Previous student ID", type="text", step=3, required=True,
                  when=_PRIOR, hint="RA- followed by 6 digits", aliases=["student_id", "previous_id"]),
        FieldSpec(name="address_line1", label="Address line 1", type="text", step=4, required=True,
                  aliases=["street", "address", "address1"]),
        FieldSpec(name="address_line2", label="Address line 2 (optional)", type="text", step=4,
                  aliases=["address2", "flat"]),
        FieldSpec(name="city", label="Town or city", type="text", step=4, required=True, aliases=["town"]),
        FieldSpec(name="postcode", label="Postcode", type="postcode", step=4, required=True,
                  aliases=["post_code", "zip", "postal_code"]),
        FieldSpec(name="consent_terms", label="I agree to the enrollment terms", type="checkbox", step=5,
                  required=True, aliases=["terms", "consent", "terms_accepted", "accepted_terms", "agreed_terms"]),
        FieldSpec(name="marketing_opt_in", label="Send me news about courses and events", type="checkbox", step=5,
                  aliases=["marketing", "newsletter"]),
    ],
)
for _f in ACADEMY.fields:
    _f.test_id = f"ra-{_f.name.replace('_', '-')}"
