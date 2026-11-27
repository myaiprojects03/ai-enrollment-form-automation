# n8n workflows

Three workflows for n8n Community Edition (free, self-hosted; it runs in `docker compose up -d` on port 5678).

| File | What it does |
|---|---|
| `01-intake-relay.json` | **Enrollment intake: receive and forward.** A form tool, CRM or website posts a record to the n8n webhook (`POST /webhook/enrollment-intake`). n8n signs it (HMAC-SHA256 with `WEBHOOK_SECRET`) and hands it to the engine's signed webhook, then replies with the enrollment ID, outcome and reasons. The sender's retries are safe: the same `Idempotency-Key` header (or the same body) returns the first enrollment. |
| `02-scheduled-submitter.json` | **Enrollment submissions: every 5 minutes.** Submits approved enrollments one at a time. The engine does the work (API or browser, read-back, retries without double submission); n8n summarises, and posts anything that needs a person to a chat webhook. Use this or `python -m scripts.worker`, not both at once (both would be safe, just redundant). |
| `03-morning-digest.json` | **Enrollment desk: morning digest.** Every morning at 8: counts by status and what is waiting for a person, posted to a chat webhook (Slack, Microsoft Teams, Discord and Google Chat all accept `{"text": "..."}`). |

No workflow sees personal data except the relay, which passes the record through without storing it. The summaries
use enrollment IDs, statuses, portal references and reason messages only.

## Set up

1. In `.env` (main folder) set `OPERATOR_TOKEN` and `WEBHOOK_SECRET` (already there), and optionally
   `ALERT_WEBHOOK_URL` (a Slack or Teams incoming-webhook URL). `docker compose up -d` passes them to n8n.
2. Open <http://localhost:5678> and create the owner account (local only).
3. For each file: **Workflows > Import from file**, choose it, then **Save** and switch it to **Active**.
4. Try the relay:

   ```bash
   curl -X POST localhost:5678/webhook/enrollment-intake -H 'content-type: application/json' \
        -H 'Idempotency-Key: crm-1001' -d @../samples/riverside-adult.json
   ```

   It answers with the enrollment's ID and outcome; the record appears in the review console.

The workflows read four settings with `$env` (`ENGINE_URL`, `ENGINE_TOKEN`, `WEBHOOK_SECRET`, `ALERT_WEBHOOK_URL`),
which is why compose sets `N8N_BLOCK_ENV_ACCESS_IN_NODE=false`. On a shared n8n, move the token and secret into
n8n credentials instead.
