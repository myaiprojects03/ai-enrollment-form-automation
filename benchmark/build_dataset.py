"""Writes dataset.json: 24 synthetic applicant records in the shapes they really arrive in, each with the values a
careful person would enter and the outcome the system should reach. All people, emails and numbers are made up.

Dates that must stay in the future are written "+14d" and resolved when the benchmark runs."""
import json
from pathlib import Path


def e164(n: str) -> str:
    return "+44" + n.replace(" ", "")[1:]


R, H = "riverside-enrollment", "harbour-membership"
records = []


def add(id_, form, source, record, outcome, fields, note, needs_ai=False):
    records.append({"id": id_, "form": form, "source": source, "record": record, "expected_outcome": outcome,
                    "expected": fields, "note": note, "needs_ai": needs_ai})


def ra(first, last, dob, email, phone, program, term, mode, line1, city, pc, **more):
    out = {"first_name": first, "last_name": last, "date_of_birth": dob, "email": email, "phone": e164(phone),
           "program": program, "start_term": term, "study_mode": mode, "address_line1": line1, "city": city,
           "postcode": pc, "consent_terms": True}
    out.update(more)
    return out


# ---------------------------------------------------------------- Riverside Academy (12)
add("R01", R, "csv", {"Student Name": "Amara Okafor", "D.O.B": "14/05/1998", "E-mail": "amara.okafor@example.com",
    "Mobile No": "07911 123456", "Course": "Data Analytics", "Intake": "Jan 2027", "Mode": "Part time",
    "Address": "14 Mill Lane, Leeds, LS1 4AP", "Terms Accepted": "Yes"}, "PASS",
    ra("Amara", "Okafor", "1998-05-14", "amara.okafor@example.com", "07911 123456", "data-analytics", "2027-01",
       "part_time", "14 Mill Lane", "Leeds", "LS1 4AP"), "Export headers, full name and one-line address")
add("R02", R, "csv", {"Student Name": "Leo Grant", "D.O.B": "14/02/2010", "E-mail": "leo.grant@example.com",
    "Mobile No": "+44 7911 234567", "Course": "Web Development", "Intake": "Sept 2027", "Mode": "FT",
    "Address": "3 Canal Wharf, Leeds, LS11 5PS", "Guardian": "Hannah Grant", "Relationship": "Mother",
    "Guardian Mobile": "07400 234567", "Terms Accepted": "Yes"}, "PASS",
    ra("Leo", "Grant", "2010-02-14", "leo.grant@example.com", "07911 234567", "web-development", "2027-09",
       "full_time", "3 Canal Wharf", "Leeds", "LS11 5PS", guardian_name="Hannah Grant",
       guardian_relationship="parent", guardian_phone=e164("07400 234567")), "Under 18 with a guardian")
add("R03", R, "csv", {"Student Name": "Priya Shah", "D.O.B": "04/03/2001", "E-mail": "PRIYA.SHAH@EXAMPLE.COM",
    "Mobile No": "07912 345678", "Course": "Accounting", "Intake": "April 2027", "Mode": "Online",
    "Address": "9 Park Row, Leeds, LS1 5HD", "Terms Accepted": "Yes"}, "NEEDS_REVIEW",
    ra("Priya", "Shah", "2001-03-04", "priya.shah@example.com", "07912 345678", "accounting", "2027-04", "online",
       "9 Park Row", "Leeds", "LS1 5HD"), "Day and month could be either way round")
add("R04", R, "csv", {"Student Name": "Tom Hughes", "D.O.B": "22/11/1995", "E-mail": "tom.hughes@example.com",
    "Mobile No": "07913 456789", "Course": "Project Management", "Intake": "Jan 2027", "Mode": "Part-time",
    "Address": "88 Kirkstall Road, Leeds, LS3 1LH"}, "BLOCKED",
    {k: v for k, v in ra("Tom", "Hughes", "1995-11-22", "tom.hughes@example.com", "07913 456789",
                         "project-management", "2027-01", "part_time", "88 Kirkstall Road", "Leeds",
                         "LS3 1LH").items() if k != "consent_terms"}, "No consent in the source")
add("R05", R, "csv", {"Student Name": "Grace O'Neill", "D.O.B": "19/09/1999", "E-mail": "grace.oneill@example.com",
    "Mobile No": "07914 567890", "Course": "Cyber Secuirty", "Intake": "Sept 2027", "Mode": "Online",
    "Address": "5 Otley Road, Leeds, LS6 3AA", "Returning?": "Yes", "Student ID": "ra-204518",
    "Terms Accepted": "Yes"}, "PASS",
    ra("Grace", "O'Neill", "1999-09-19", "grace.oneill@example.com", "07914 567890", "cyber-security", "2027-09",
       "online", "5 Otley Road", "Leeds", "LS6 3AA", prior_enrollment=True, prior_student_id="RA-204518"),
    "Course name typo, returning student")
add("R06", R, "json", {"applicant": {"first": "Tomasz", "last": "Nowak"}, "dob": "1990-11-02",
    "contact": {"email": "tomasz.nowak@example.com", "mobile": "07915 678901"},
    "course": "Business Admin", "intake": "2027-04", "mode": "part_time",
    "address": {"line1": "21 Station Road", "city": "Harrogate", "postcode": "HG1 1SX"}, "consent": True}, "PASS",
    ra("Tomasz", "Nowak", "1990-11-02", "tomasz.nowak@example.com", "07915 678901", "business-admin", "2027-04",
       "part_time", "21 Station Road", "Harrogate", "HG1 1SX"), "Nested JSON from a web form")
add("R07", R, "json", {"first_name": "Daniel", "last_name": "Reyes", "date_of_birth": "05/14/1998",
    "email": "daniel.reyes@example.com", "phone": "07916 789012", "program": "Graphic Design",
    "start_term": "January 2027", "study_mode": "Full-time", "address_line1": "4 Abbey Street", "city": "York",
    "postcode": "YO1 7HH", "consent_terms": "yes"}, "NEEDS_REVIEW",
    ra("Daniel", "Reyes", "1998-05-14", "daniel.reyes@example.com", "07916 789012", "graphic-design", "2027-01",
       "full_time", "4 Abbey Street", "York", "YO1 7HH"), "US-style date (month first)")
add("R08", R, "notes", {"notes": "Call notes, Tuesday afternoon (admissions line)\n\nSpoke to Daniel Mensah about "
    "starting the Business Administration course. He'd like to study part time and start in April 2027. Date of "
    "birth 2nd March 1994. Best number is 07917 890123 and his email is daniel.mensah@example.com.\n\nAddress: "
    "41 Chapel Street, Bradford, BD1 5DL.\nHe confirmed he has read and agrees to the enrollment terms. No "
    "marketing please."}, "NEEDS_REVIEW",
    ra("Daniel", "Mensah", "1994-03-02", "daniel.mensah@example.com", "07917 890123", "business-admin", "2027-04",
       "part_time", "41 Chapel Street", "Bradford", "BD1 5DL", marketing_opt_in=False),
    "Free-text call notes; consent read from text goes to a person", needs_ai=True)
add("R09", R, "notes", {"notes": "First name: Chloe\nLast name: Martin\nDate of birth: 17/12/2003\nEmail: "
    "chloe.martin@example.com\nMobile: 07918 901234\nCourse: Computer Science Foundation\nStart term: September "
    "2027\nStudy mode: Full-time\nAddress line 1: 12 Hyde Park Road\nCity: Leeds\nPostcode: LS6 1AH\nTerms: yes"},
    "PASS", ra("Chloe", "Martin", "2003-12-17", "chloe.martin@example.com", "07918 901234", "cs-foundation",
               "2027-09", "full_time", "12 Hyde Park Road", "Leeds", "LS6 1AH"), "An emailed form, one field a line")
add("R10", R, "csv", {"Student Name": "Sam Patel", "D.O.B": "30/06/2002", "E-mail": "sam.patel@example.com",
    "Phone": "07919 012345", "Mobile": "07920 123456", "Course": "Graphic Design", "Intake": "Jan 2027",
    "Mode": "Full-time", "Address": "12 Woodhouse Lane, Leeds, LS2 9JT", "Terms Accepted": "Yes"}, "NEEDS_REVIEW",
    ra("Sam", "Patel", "2002-06-30", "sam.patel@example.com", "07919 012345", "graphic-design", "2027-01",
       "full_time", "12 Woodhouse Lane", "Leeds", "LS2 9JT"), "Two different phone numbers")
add("R11", R, "csv", {"Student Name": "Mia Clarke", "D.O.B": "21/08/2014", "E-mail": "mia.clarke@example.com",
    "Mobile No": "07401 345678", "Course": "Web Development", "Intake": "Sept 2027", "Mode": "Online",
    "Address": "7 Mount Street, Leeds, LS2 3AB", "Guardian": "Ruth Clarke", "Relationship": "Mum",
    "Guardian Mobile": "07402 456789", "Terms Accepted": "Yes"}, "BLOCKED",
    ra("Mia", "Clarke", "2014-08-21", "mia.clarke@example.com", "07401 345678", "web-development", "2027-09",
       "online", "7 Mount Street", "Leeds", "LS2 3AB", guardian_name="Ruth Clarke", guardian_relationship="parent",
       guardian_phone=e164("07402 456789")), "Too young for the academy (under 14)")
add("R12", R, "csv", {"Student Name": "JAMES O'BRIEN", "D.O.B": "22/11/95", "E-mail": "james.obrien@example.com",
    "Mobile No": "07907 123456", "Course": "PRINCE2", "Intake": "Jan 2027", "Mode": "Part time",
    "Address": "30 Briggate, Leeds, LS1 6HD", "Terms Accepted": "Y"}, "NEEDS_REVIEW",
    ra("James", "O'Brien", "1995-11-22", "james.obrien@example.com", "07907 123456", "project-management",
       "2027-01", "part_time", "30 Briggate", "Leeds", "LS1 6HD"), "Capitals and a two-digit year")


# ---------------------------------------------------------------- Harbour Sports Club (12)
def hs(name, email, phone, dob, plan, start, interests, ice_name, ice_phone, **more):
    out = {"full_name": name, "email": email, "phone": e164(phone), "date_of_birth": dob, "membership_type": plan,
           "start_date": start, "interests": interests, "emergency_contact_name": ice_name,
           "emergency_contact_phone": e164(ice_phone), "accept_terms": True}
    out.update(more)
    return out


add("H01", H, "json", {"full_name": "Sofia Marin", "email": "sofia.marin@example.com", "phone": "07800 345678",
    "date_of_birth": "1991-09-30", "membership_type": "adult", "start_date": "+14d", "interests": ["swimming", "yoga"],
    "emergency_contact_name": "Dan Marin", "emergency_contact_phone": "07900 456789", "accept_terms": True}, "PASS",
    hs("Sofia Marin", "sofia.marin@example.com", "07800 345678", "1991-09-30", "adult", "+14d", ["swimming", "yoga"],
       "Dan Marin", "07900 456789"), "Clean API record (still needs sign-off)")
add("H02", H, "json", {"member": {"first": "Kwame", "last": "Asante"}, "contact": {"email": "kwame.asante@example.com",
    "phone": "07801 456789"}, "dob": "1985-03-12", "plan": "Family", "household size": "four", "start": "+21d",
    "activities": "Swimming, Climbing", "ice": {"name": "Efua Asante", "phone": "07901 567890"},
    "terms": True}, "PASS",
    hs("Kwame Asante", "kwame.asante@example.com", "07801 456789", "1985-03-12", "family", "+21d",
       ["swimming", "climbing"], "Efua Asante", "07901 567890", family_members=4), "Nested, family size in words")
add("H03", H, "json", {"member": {"first": "Jonah", "last": "Reid"}, "contact": {"email": "jonah.reid@example.com",
    "phone": "07802 567890"}, "dob": "2006-04-18", "plan": "Student", "Uni ref #": "UOL482913", "start": "+7d",
    "activities": ["gym", "squash"], "ice": {"name": "Ruth Reid", "phone": "07903 789012"}, "terms": True}, "PASS",
    hs("Jonah Reid", "jonah.reid@example.com", "07802 567890", "2006-04-18", "student", "+7d", ["gym", "squash"],
       "Ruth Reid", "07903 789012", student_id="UOL482913"), "Student card under an odd column name", needs_ai=True)
add("H04", H, "json", {"member": {"first": "Kai", "last": "Turner"}, "contact": {"email": "kai.turner@example.com",
    "phone": "07803 678901"}, "dob": "2012-07-07", "plan": "Adult", "start": "+7d", "activities": "Tennis",
    "ice": {"name": "Lisa Turner", "phone": "07804 789012"}, "terms": False}, "BLOCKED",
    {**hs("Kai Turner", "kai.turner@example.com", "07803 678901", "2012-07-07", "adult", "+7d", ["tennis"],
          "Lisa Turner", "07804 789012"), "accept_terms": False}, "Under 16, terms refused")
add("H05", H, "csv", {"Name": "Ella Brooks", "Email": "ella.brooks@example.com", "Mobile": "07904 890123",
    "DOB": "21/01/1984", "Plan": "Off peak", "Start": "+10d", "Activities": "Swimming; yoga & bouldering",
    "ICE name": "Mark Brooks", "ICE phone": "07805 890123", "Terms": "agreed"}, "PASS",
    hs("Ella Brooks", "ella.brooks@example.com", "07904 890123", "1984-01-21", "off_peak", "+10d",
       ["swimming", "yoga", "climbing"], "Mark Brooks", "07805 890123"), "Spreadsheet, interests as free text")
add("H06", H, "csv", {"Name": "Omar Haddad", "Email": "omar.haddad@example.com", "Mobile": "07905 901234",
    "DOB": "28/02/1990", "Plan": "Adult", "Start": "+10d", "Activities": "Gym", "ICE name": "Layla Haddad",
    "ICE phone": "07905 901234", "Terms": "yes"}, "NEEDS_REVIEW",
    hs("Omar Haddad", "omar.haddad@example.com", "07905 901234", "1990-02-28", "adult", "+10d", ["gym"],
       "Layla Haddad", "07905 901234"), "Emergency number is the member's own")
add("H07", H, "csv", {"Name": "Lucy Evans", "Email": "lucy.evans@example.com", "Mobile": "07806 901234",
    "DOB": "15/06/1996", "Plan": "Adult", "Start": "+200d", "Activities": "Tennis", "ICE name": "Ben Evans",
    "ICE phone": "07906 012345", "Terms": "yes"}, "BLOCKED",
    hs("Lucy Evans", "lucy.evans@example.com", "07806 901234", "1996-06-15", "adult", "+200d", ["tennis"],
       "Ben Evans", "07906 012345"), "Start date too far ahead")
add("H08", H, "csv", {"First name": "Aisha", "Surname": "Khan", "Email": "aisha.khan@example.com",
    "Mobile": "07807 012345", "DOB": "23/10/1993", "Plan": "Adult", "Start": "+5d", "Activities": "Yoga, Gym",
    "ICE name": "Imran Khan", "ICE phone": "07908 234567", "Terms": "yes", "How did you hear?": "Google"}, "PASS",
    hs("Aisha Khan", "aisha.khan@example.com", "07807 012345", "1993-10-23", "adult", "+5d", ["yoga", "gym"],
       "Imran Khan", "07908 234567", how_heard="search"), "First and last in separate columns")
add("H09", H, "notes", {"notes": "Walk-in at reception. Hannah Wright, born 9 August 1988, wants an adult membership "
    "starting {{+12d}}. Mobile 07808 123456, email hannah.wright@example.com. Interested in swimming and tennis. "
    "Emergency contact is her partner Joe Wright on 07401 345678. She read the membership terms and agreed."},
    "NEEDS_REVIEW",
    hs("Hannah Wright", "hannah.wright@example.com", "07808 123456", "1988-08-09", "adult", "+12d",
       ["swimming", "tennis"], "Joe Wright", "07401 345678"), "Reception notes; consent goes to a person",
    needs_ai=True)
add("H10", H, "json", {"full_name": "Noah Fischer", "email": "noah.fischer at example dot com",
    "phone": "07912 345678", "date_of_birth": "1979-12-24", "membership_type": "Adult", "start_date": "+8d",
    "interests": "squash", "emergency_contact_name": "Mila Fischer", "emergency_contact_phone": "07913 456789",
    "how_heard": "Instagram", "accept_terms": "yes"}, "NEEDS_REVIEW",
    hs("Noah Fischer", "noah.fischer@example.com", "07912 345678", "1979-12-24", "adult", "+8d", ["squash"],
       "Mila Fischer", "07913 456789", how_heard="social"), "Email written out in words")
add("H11", H, "json", {"full_name": "Zara Ali", "email": "zara.ali@example.com", "phone": "07914 567890",
    "date_of_birth": "2001-05-05", "membership_type": "Adult", "start_date": "+9d", "interests": "Swimming, darts",
    "emergency_contact_name": "Sami Ali", "emergency_contact_phone": "07915 678901", "accept_terms": True},
    "NEEDS_REVIEW",
    hs("Zara Ali", "zara.ali@example.com", "07914 567890", "2001-05-05", "adult", "+9d", ["swimming"],
       "Sami Ali", "07915 678901"), "An interest the club does not offer")
add("H12", H, "csv", {"Name": "Ben Carter", "Email": "ben.carter@example.com", "Mobile": "07916 789012",
    "DOB": "11/11/1992", "Plan": "Adult", "Start": "+6d", "Activities": "Gym", "Terms": "yes"}, "BLOCKED",
    {k: v for k, v in hs("Ben Carter", "ben.carter@example.com", "07916 789012", "1992-11-11", "adult", "+6d",
                         ["gym"], "", "07400 234567").items() if not k.startswith("emergency")},
    "No emergency contact")

Path(__file__).with_name("dataset.json").write_text(json.dumps({"records": records}, indent=1))
print(f"{len(records)} records")
