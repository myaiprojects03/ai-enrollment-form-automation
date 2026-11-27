"""Handing web-form submissions to the worker when the API runs serverless (no browser, no background work).

The worker is a GitHub Actions workflow (.github/workflows/worker.yml) listening for a repository_dispatch event;
it also runs on a schedule, so a missed trigger only delays a submission, never loses it.
"""
from __future__ import annotations

import httpx


async def trigger_worker(repo: str, token: str) -> bool:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            res = await client.post(
                f"https://api.github.com/repos/{repo}/dispatches", json={"event_type": "submit-enrollments"},
                headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                         "X-GitHub-Api-Version": "2022-11-28"})
    except httpx.HTTPError:
        return False
    return res.status_code == 204
