# Deploying on free tiers

| Part | Where | Notes |
|---|---|---|
| Review console and both portals | Vercel (Hobby), project root `frontend/` | Next.js, no build settings needed |
| Engine API | Vercel (Hobby), project root `backend/` | FastAPI; `backend/vercel.json`; no browser here |
| Web-form submissions | GitHub Actions, `.github/workflows/worker.yml` | triggered on approval, plus a 15-minute sweep |
| Database | Neon (free) | one database (`enroll`) for the engine and the portals; their tables don't overlap |
| Shared state | Upstash Redis (free) | `rediss://` URL; keys are prefixed `enroll:` so an existing database can be shared |
| AI mapper | Groq (free) | or Claude |
| n8n | your machine (`docker compose up -d`) | n8n Cloud is paid; the workflows need only the engine's URL and token |

## 1. Databases

- **Neon:** create a project (region near London), database `enroll`. In **Connect**, turn connection pooling
  off and copy the direct string (no `-pooler` in the host; migrations hold a session lock). It ends in
  `?sslmode=require`. The engine and the portals use the same string.
- **Upstash:** use your Redis database's `rediss://` URL.

## 2. Secrets (on your machine, never in chat or git)

```bash
cd backend && python -m scripts.keys          # ENCRYPTION_KEYS, FINGERPRINT_KEY, OPERATOR_TOKEN, SESSION_SECRET
python -m scripts.staff reviewer@example.com  # STAFF_ACCOUNTS entry for the console sign-in
python -c "import secrets; print(secrets.token_urlsafe(24))"   # PORTAL_API_KEY, and again for WEBHOOK_SECRET
```

## 3. GitHub

Push the repository. Create a fine-grained token (Settings > Developer settings > Fine-grained tokens) for this
repository only, with **Contents: Read and write** (GitHub requires it for repository dispatch). It lets the engine start
the worker.

## 4. Vercel: the web app (`frontend/`)

New project from the repository, Root Directory `frontend`. Environment variables:

```
PORTAL_DATABASE_URL = <Neon enroll connection string>
PORTAL_API_KEY      = <PORTAL_API_KEY>
ENGINE_URL          = https://<engine project>.vercel.app      (fill in after step 5, then redeploy)
```

## 5. Vercel: the engine (`backend/`)

New project from the same repository, Root Directory `backend`. Environment variables:

```
APP_ENV=production
DATABASE_URL=<Neon enroll connection string>
REDIS_URL=<Upstash rediss:// URL>
ENCRYPTION_KEYS=...  FINGERPRINT_KEY=...  OPERATOR_TOKEN=...  SESSION_SECRET=...
STAFF_ACCOUNTS=<the scripts.staff line>
WEBHOOK_SECRET=...
GROQ_API_KEY=...
PORTAL_BASE_URL=https://<web app>.vercel.app
PORTAL_API_KEY=<same as the web app>
ALLOWED_ORIGINS=https://<web app>.vercel.app
SUBMIT_MODE=dispatch
GITHUB_DISPATCH_REPO=<you>/<repository>
GITHUB_DISPATCH_TOKEN=<the token from step 3>
```

The engine refuses to start in production with weak or missing settings and says which. Check
`https://<engine>.vercel.app/health`.

## 6. GitHub Actions secrets (Settings > Secrets and variables > Actions)

`DATABASE_URL`, `REDIS_URL`, `ENCRYPTION_KEYS`, `FINGERPRINT_KEY`, `OPERATOR_TOKEN`, `SESSION_SECRET`,
`PORTAL_BASE_URL`, `PORTAL_API_KEY`: the same values as the engine. Run **Actions > Submission worker > Run
workflow** once to check it.

## How a submission runs when deployed

- Harbour Sports Club (has an API): submitted straight away by the engine when a reviewer approves.
- Riverside Academy (web form only): the engine starts the worker; a GitHub runner opens Chromium, submits, stores
  the screenshots and reference, usually within two minutes. The console waits and shows the result.
- If the trigger is missed, the 15-minute sweep picks the record up. The nightly run also erases personal data of
  enrollments finished more than `RETENTION_DAYS` (90) ago.
