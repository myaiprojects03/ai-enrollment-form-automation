# Setup

Needs Docker, Python 3.11+ and Node 20+.

## 1. Services

```bash
docker compose up -d
```

Postgres on `localhost:5433` (databases `enroll`, `portals`, `n8n`, `enroll_test`), Redis on `localhost:6380`, n8n on
<http://localhost:5678>.

## 2. Engine

```bash
cp .env.example .env
cd backend
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
python -m scripts.keys          # paste the three lines into ../.env
uvicorn app.main:app --reload
```

Check it: `curl localhost:8000/health` should return `{"status":"ok","database":true,"shared_state":true}`.

Send a sample record (use your OPERATOR_TOKEN):

```bash
curl -H "Authorization: Bearer $OPERATOR_TOKEN" -H "content-type: application/json" \
     -d @../samples/riverside-adult.json localhost:8000/api/enrollments
```

Sending it again returns `200` with `"duplicate": true` and the same `enrollment_id`.

Install the browser the engine submits with (once):

```bash
python -m playwright install chromium
```

Create your review console account (the password is asked twice and never stored):

```bash
python -m scripts.staff you@example.com     # paste the printed line as STAFF_ACCOUNTS=... in ../.env
```

`SESSION_SECRET` comes from `python -m scripts.keys` (run it again and copy just that line if you set up before
Phase 4). Restart the engine after changing `.env`.

## 3. Portals and console

```bash
cd frontend
cp .env.example .env.local
npm install
npm run dev
```

Open <http://localhost:3000/console> and sign in. The portals are at
<http://localhost:3000/portals/riverside/enroll> and <http://localhost:3000/portals/harbour/join>.

## 4. Tests

```bash
cd backend && TEST_DATABASE_URL=postgresql://enroll:enroll@localhost:5433/enroll_test \
              TEST_REDIS_URL=redis://localhost:6380/15 pytest -q
cd frontend && npm run build && npx playwright install chromium && npx playwright test
# real submissions: portals on 3100, then
cd frontend && PORTAL_API_KEY=dev-portal-key npx next start -p 3100 &
cd backend && TEST_PORTAL_URL=http://localhost:3100 TEST_DATABASE_URL=... pytest -q tests/test_submit_e2e.py
```

The backend tests drop and recreate the schema of the test database, so never point `TEST_DATABASE_URL` at real data.

## Secrets

- `.env` and `frontend/.env.local` are git-ignored. Never commit them or paste their values anywhere.
- `ENCRYPTION_KEYS` is a list, newest first. To rotate, put a new key in front and keep the old ones until every row
  has been re-sealed.
- Losing every encryption key makes stored records unreadable. Keep a copy in a password manager.
