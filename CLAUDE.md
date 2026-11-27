# Notes for working on this repo

- Engine: `backend/` (FastAPI, asyncpg, Pydantic v2). Portals and later the console: `frontend/` (Next.js App Router).
- Run backend checks from `backend/`: `ruff check . && mypy app tests && pytest -q` (set TEST_DATABASE_URL for DB tests).
- Run frontend checks from `frontend/`: `npx tsc --noEmit && npm run build && npx playwright test`.
- Personal data never goes into logs, audit details, error messages or API responses unless `reveal=true` is asked
  for (and that is audited). `Issue` objects carry a field, a code and a message, never the value.
- Form fields are defined once in `backend/app/forms/*.py`; portal `data-testid`s follow `FieldSpec.test_id`
  (`ra-…`, `hsc-…`). Keep the two in step.
- The portals are deliberately independent of the engine (their own rules in `frontend/lib/portals`), because they
  stand in for third-party sites.
- Python 3.11 is the floor (CI tests 3.11 and 3.12). Pin exact versions in requirements files.
- Playwright is pinned to 1.63 with an npm override on playwright-core, so axe and the test runner share one version.
- Mapping order: rules (app/mapping/rules.py) first, the AI (app/mapping/mapper.py) only when a required field is
  still missing. Structured records never send values to the AI, only column names and value shapes (`shape()`);
  keep it that way. Free-text answers must pass `grounded()`.
- Outcomes are deterministic (app/validation/outcome.py). Reason messages must never contain values.
- Tests use `FakeLLM` (tests/test_mapping.py); LLM_PROVIDER is forced to none in tests.
- Submission (app/submit): never send before checking the portal for an existing record (`PortalAPI.find`), and
  never retry without checking again. Steps logs and error details must not contain values; screenshots are stored
  only encrypted (`seal_bytes`).
- Locators: add strategies to `Resolver` rather than special-casing a portal. Python Playwright is pinned to 1.63
  to match the frontend's Playwright and its Chromium build.
- Console (frontend/app/console): the page never holds a token. All engine calls go through
  app/api/console/engine/[...path] (allow-list in lib/console/server.ts; writes need `x-console: 1`). Polling must
  not use `reveal=true`: each reveal is an audited view of personal data.
- Console e2e: `npx playwright test -c playwright.console.config.ts` against a running engine and web app.
