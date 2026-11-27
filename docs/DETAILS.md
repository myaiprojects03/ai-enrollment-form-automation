# How it works, in detail

## Intake, encryption and the practice portals

**Engine (`backend/`)**
- `POST /api/enrollments` receives a record exactly once. A replay with the same idempotency key (body field or
  `Idempotency-Key` header) returns the first enrollment with `200`; a new one returns `201`. Without a key, a keyed
  hash of the form and the record is used, so the same record sent twice is still recognised.
- Two gates: Redis `SET NX` stops concurrent duplicates before they reach the database, and a unique key in Postgres
  holds even if Redis is emptied. Tested with 12 simultaneous replays producing one row.
- Records are sealed with AES-256-GCM before they are written, with the row id as associated data so a payload cannot
  be moved to another row. Keys rotate (each blob carries its key id).
- Logs and audit entries mask emails, phone numbers, dates and postcodes; audit details record field names, not values.
  Viewing decrypted data (`?reveal=true`) is itself audited.
- The same applicant (matched by an HMAC fingerprint of the email, never the email itself) on a second record is
  flagged as a possible duplicate for a reviewer rather than merged.
- Form definitions for both portals: every field with its label, type, step, options, aliases and conditions, plus a
  Pydantic model that returns exact, value-free reasons (`REQUIRED_MISSING`, `CONDITIONAL_REQUIRED`, `INVALID_PHONE`,
  `NOT_APPLICABLE`, ...). Cross-field rules: guardian details for under-18s, a previous student ID for returning
  students, student and family memberships, contact numbers that must differ.

**Practice portals (`frontend/`)**, standing in for third-party sites:
- **Riverside Academy** `/portals/riverside/enroll`: a five-step wizard with a searchable programme combobox, a typed
  or calendar-picked date of birth, a guardian step that appears only for under-18s, an error summary, a review page and
  a confirmation page that shows what was stored (for read-back). Browser only, like many real portals.
- **Harbour Sports Club** `/portals/harbour/join`: a one-page form with conditional fields, plus a partner API
  `POST /api/portals/harbour/members` (`X-Portal-Key`) returning `201`, `409` or `422` with a reason per field.
- `?variant=b` serves a drifted page: reworded labels, swapped sections and no test ids, to prove locators heal.
- `?chaos=slow|flaky|down|lost|captcha` (or the `X-Portal-Chaos` header) simulates delays, transient failures, outages,
  a saved submission whose reply was lost, and a security check that must stop automation.

## Ingest, AI mapping and validation

**Ways in**
- `POST /api/intake/upload` takes a CSV export (one enrollment per row), JSON (one object, a list, or `{"records": [...]}`,
  nested objects allowed), a PDF (fillable form fields, or the text of a letter) or a text file.
- `POST /api/intake/notes` takes pasted call notes or an email.
- `POST /api/webhooks/intake` for n8n, a CRM or a form tool, signed with HMAC-SHA256 (`X-Signature: sha256=...`)
  instead of the operator token. Retries are safe: the same key or body returns the first enrollment.
- Uploading the same file twice creates nothing new.

**Mapping: rules first, the AI only for what is left**
- Source columns are matched to fields by name, label and known aliases ("D.O.B", "Mobile No", "Intake", "Mode"), then
  derived fields: a full name split into first and last, first and last joined, a one-line address split into street,
  town and postcode, a previous student ID implying a returning student.
- Values are converted with an honest confidence: dates in UK, US, ISO and written forms (03/04/2005 is flagged as a
  day-first guess), spreadsheet date numbers, phone numbers to E.164, yes/no words, options by value, label, common
  synonyms ("PT", "Sept 2027", "Instagram") and typos.
- The AI is called only when a required field is still missing. For a structured record it sees the left-over column
  names and the shape of each value (`Xxxxx Xxxxxx`, `99999 999999`), never the values themselves. For free text it
  reads the text, and every value it returns must be found in the text: one that is not is kept at 30% confidence for
  a person to check. Consent read from free text always goes to a person.
- Groq's free tier by default (`openai/gpt-oss-120b`, strict JSON schema), Claude as a one-line switch, or rules only.

**Validation: PASS, NEEDS_REVIEW or BLOCKED, with the exact reasons**
- BLOCKED: the form would refuse it and only the applicant can fix it: consent missing or refused, too young, a
  required answer not in the source.
- NEEDS_REVIEW: a field below 85% confidence, two source columns that disagree, a value in the wrong format, a
  possible duplicate applicant, data the AI could not read.
- PASS: every rule met and every field above the threshold. Harbour Sports Club still asks for a person's sign-off.
- Reasons name fields and source columns, never values. Each field keeps its confidence, method (rule, derived, AI,
  default, edited), source columns and any assumption (encrypted, shown only when revealed).
- `PATCH /api/enrollments/{id}/fields` applies a reviewer's corrections and checks the record again; re-mapping from
  the source keeps them.

Raw samples to try are in `samples/raw/`: a messy CSV export, nested JSON sign-ups and call notes.

## Submission

**Two ways to submit.** The portal's API where it has one (Harbour Sports Club), otherwise its web form in a real
Chromium browser driven by Playwright (Riverside Academy's five-step wizard). If the API keeps failing, the last
attempt goes through the web form.

**Exactly once.** Only approved enrollments are submitted, one worker at a time (a Redis lock, an atomic
`approved -> submitting` update, and a database rule allowing one running attempt). Before sending, and again
before every retry, the engine asks the portal whether it already has this applicant, so a reply that was lost
(`?chaos=lost`: saved, but the answer never arrived) is found and kept instead of being sent twice.

**In the browser**
- Each page: fill every field it shows (conditional fields appear as their trigger is set: the guardian step for
  under-18s, the student card for a student plan), read each value back from the page, screenshot it, press next.
- Custom widgets are handled as a person would: the programme combobox is typed into and its option chosen; the date
  is typed in the page's own format (DD/MM/YYYY, or ISO for a native date input).
- Before the final submit, nothing may be left unfilled; a security check (captcha) stops the run and hands it to a
  person. After it, the confirmation reference is captured and the record is read back and compared field by field.
- **Self-healing locators.** Each element is found by a chain: what worked last time, the test id, the exact label,
  the name attribute, an alias label ("Given name" for first name), then the closest label on the page if it clearly
  belongs to this field. A change is recorded as a heal (`testid:ra-first-name -> name:first_name`), audited, and
  remembered, so the next run on the drifted page needs no healing. `?variant=b` (reworded labels, swapped steps, no
  test ids) submits correctly.

**Retries and outcomes.** Temporary failures (5xx, timeouts, a page that will not load, a value that did not stick)
are retried with backoff: 2 s, 4 s, plus jitter. A refused field (422, or errors on the page) goes back to a person
with the portal's own message against the field; a captcha halts; a refused API key fails at once. Every attempt is
a run with its steps (fields, locators used, results; never values) and up to ten screenshots, encrypted at rest and
decrypted only when viewed (which is audited).

**Endpoints:** `POST /api/enrollments/{id}/approve`, `/reject`, `/submit` (`path`, `wait`, and test modes
`variant` and `chaos` outside production), `GET /api/enrollments/{id}/runs`, `GET /api/runs/{run}/screenshots/{n}`.
**Worker:** `python -m scripts.worker` submits approved enrollments in the background and returns interrupted ones to
the queue (`--once` for a scheduled job).

## Review console and n8n

**Review console** (`/console`, the "Enrollment desk"):
- **Sign-in** for named reviewers (scrypt-hashed passwords in `STAFF_ACCOUNTS`, 8-hour signed sessions, five failed
  attempts lock an address for 15 minutes). The reviewer's email is what the audit trail records. The session token
  sits in an httpOnly, same-site cookie; the page never sees it, and every call goes through a server-side proxy that
  only reaches console endpoints and refuses writes without the console's own header.
- **Exception queue**: tabs by status with counts (needs review, blocked, failed, ready to submit, submitted,
  rejected), the main reason for each record, its lowest confidence, search by enrollment ID or portal reference. The
  queue holds no personal data; opening a record reveals it and is logged. Upload a CSV, JSON, PDF or text file, or
  paste call notes, from the same page.
- **Side-by-side editor**: every field with its value, a confidence bar against the 85% threshold, how it was found
  (rule, derived, AI, default, edited) and from which source column, plus any assumption; the reasons on top. On the
  right: the source record exactly as received, the portal screenshots page by page, every submission attempt, and
  the record's history. Saving re-checks the record at once.
- **Approve & submit** (blocked until every blocking problem is fixed and changes are saved) and **Reject** with a
  reason. Harbour Sports Club records wait here for sign-off even when they pass.
- **Audit log**: every sign-in, edit, decision, submission and screenshot view, newest first.

**n8n workflows** (`n8n/`, see its README): a signed intake relay for form tools and CRMs, a five-minute scheduled
submitter that posts problems to a chat webhook, and a morning digest of what is waiting.

## Benchmark, hardening and deployment

- **Benchmark** (`benchmark/`, results in [docs/BENCHMARK.md](BENCHMARK.md)): 24 synthetic records in the
  shapes they really arrive in, each with the values a careful person would enter and the expected outcome.
  - Mapping and validation (`python -m scripts.benchmark --write`): with the AI mapper (Groq, `gpt-oss-120b`),
    100% of fields right and 24 of 24 outcomes as expected, with no wrong value anywhere; the AI was called for
    only the 3 records that need it. Rules alone: 92.7% of fields and 21 of 24 outcomes, also with no wrong value.
  - Real submissions (`python -m scripts.benchmark_submit --write`): every record that could go to a portal was
    submitted through Chromium or the API while the portals misbehaved on purpose: 13 of 13 submitted, 13 of 13
    portal records matched what was sent, 5 of 5 recovered from a failing or lost-reply portal, 0 duplicates,
    median 4.7 s through the web form and 1.0 s by API.
- **Brief contracts**: `GET /api/enrollments/{id}/mapping` returns the mapper's output as `mapped_fields`,
  `confidence_scores`, `unmapped_or_ambiguous_fields` and `assumptions_made`; the console's **Run history** lists
  every attempt with duration, retries before it, error and confirmation reference, filterable by status, portal
  and ID; failed submissions alert operators in chat (`ALERT_WEBHOOK_URL`); every web-form page records how many
  fields were read back and matched.
- **Production checks**: the engine will not start in production with a short token or secret, the default
  portal key, no Redis, or serverless dispatch without its GitHub settings. API answers carry `no-store` and the
  usual safety headers.
- **Key rotation and retention**: `python -m scripts.maintain rotate` re-encrypts everything under the newest key;
  `purge` erases the personal data of finished enrollments after `RETENTION_DAYS` (90), keeping the outcome,
  reasons, reference and audit trail. The worker applies it nightly.
- **Reviewer acceptance**: approving records which open points the reviewer accepted, and the console shows them
  as accepted, by whom.
- **Free deployment** ([docs/DEPLOY.md](DEPLOY.md)): the web app and the engine on Vercel, Neon Postgres,
  Upstash Redis, Groq, and web-form submissions in a GitHub Actions worker started on approval (the serverless API
  has no browser).
