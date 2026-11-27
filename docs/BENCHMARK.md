# Benchmark

24 synthetic records (12 per portal) in the shapes they arrive in: spreadsheet exports, nested JSON, an
emailed form, call and reception notes. Each has the values a careful person would enter and the outcome
the system should reach. Regenerate with `python -m scripts.benchmark --write` (and `--no-ai`).

| | rules + groq:openai/gpt-oss-120b | rules only |
|---|---|---|
| Field accuracy | 100.0% | 92.7% |
| Wrong values | 0 | 0 |
| Values not found | 0 | 20 |
| Outcome as expected | 24 of 24 | 21 of 24 |
| Passed without a person | 10 of 24 | 9 of 24 |
| Wrong or missing values in passed records | 0 | 0 |
| Records that needed the AI | 3 | 0 |
| Mean time per record | 0.24 s | 0.01 s |

## Record by record (rules + groq:openai/gpt-oss-120b)

| Record | Shape | What it tests | Expected | Got | Fields right | Reasons |
|---|---|---|---|---|---|---|
| R01 | csv | Export headers, full name and one-line address | PASS | PASS | 12/12 | - |
| R02 | csv | Under 18 with a guardian | PASS | PASS | 15/15 | - |
| R03 | csv | Day and month could be either way round | NEEDS_REVIEW | NEEDS_REVIEW | 12/12 | low confidence |
| R04 | csv | No consent in the source | BLOCKED | BLOCKED | 11/11 | required missing |
| R05 | csv | Course name typo, returning student | PASS | PASS | 14/14 | - |
| R06 | json | Nested JSON from a web form | PASS | PASS | 12/12 | - |
| R07 | json | US-style date (month first) | NEEDS_REVIEW | NEEDS_REVIEW | 12/12 | low confidence |
| R08 | notes | Free-text call notes; consent read from text goes to a person | NEEDS_REVIEW | NEEDS_REVIEW | 13/13 | low confidence |
| R09 | notes | An emailed form, one field a line | PASS | PASS | 12/12 | - |
| R10 | csv | Two different phone numbers | NEEDS_REVIEW | NEEDS_REVIEW | 12/12 | ambiguous field |
| R11 | csv | Too young for the academy (under 14) | BLOCKED | BLOCKED | 15/15 | out of range |
| R12 | csv | Capitals and a two-digit year | NEEDS_REVIEW | NEEDS_REVIEW | 12/12 | low confidence |
| H01 | json | Clean API record (still needs sign-off) | PASS | PASS | 10/10 | - |
| H02 | json | Nested, family size in words | PASS | PASS | 11/11 | - |
| H03 | json | Student card under an odd column name | PASS | PASS | 11/11 | - |
| H04 | json | Under 16, terms refused | BLOCKED | BLOCKED | 10/10 | must accept, out of range |
| H05 | csv | Spreadsheet, interests as free text | PASS | PASS | 10/10 | - |
| H06 | csv | Emergency number is the member's own | NEEDS_REVIEW | NEEDS_REVIEW | 10/10 | invalid phone |
| H07 | csv | Start date too far ahead | BLOCKED | BLOCKED | 10/10 | out of range |
| H08 | csv | First and last in separate columns | PASS | PASS | 11/11 | - |
| H09 | notes | Reception notes; consent goes to a person | NEEDS_REVIEW | NEEDS_REVIEW | 10/10 | low confidence |
| H10 | json | Email written out in words | NEEDS_REVIEW | NEEDS_REVIEW | 11/11 | low confidence |
| H11 | json | An interest the club does not offer | NEEDS_REVIEW | NEEDS_REVIEW | 10/10 | low confidence |
| H12 | csv | No emergency contact | BLOCKED | BLOCKED | 8/8 | required missing |

## Real submissions

Every record that could go to a portal, through the running engine and the real portals in Chromium, with trouble rotated across them (slow, failing then working, a reply lost after saving, a reworded page without test ids). `python -m scripts.benchmark_submit --write`.

| | |
|---|---|
| Sent to a portal | 13 of 24 (10 blocked, 1 held for a person to correct) |
| Submitted | 13 of 13 |
| Portal record matched what was sent | 13 of 13 |
| Recovered from a failing or lost-reply portal | 5 of 5 |
| Duplicates at the portal | 0 |
| Locators healed on the reworded page | 8 |
| Median time, web form | 4.7 s |
| Median time, API | 1.0 s |
| Mean time, all (including a deliberately slow portal and retries) | 3.7 s |
