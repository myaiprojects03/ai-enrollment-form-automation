"""Benchmark, part two: real submissions. Every benchmark record that can go to a portal is sent through the
running engine (intake, mapping, approval where a person would give it, submission) while the portals misbehave on
purpose, then the portals are asked how many records they hold for each applicant.

    python -m scripts.benchmark_submit [--engine http://localhost:8000] [--write]

Needs the engine (OPERATOR_TOKEN in .env) and the portals running (PORTAL_BASE_URL, PORTAL_API_KEY). Emails get a
+tag so a rerun never collides with earlier data. Measures: completion time, attempts, recovery from simulated
failures, healed locators, and duplicates at the portal (must be zero).
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import time
import uuid
from typing import Any

import httpx

from app.config import get_settings
from scripts.benchmark import DATASET, ROOT, _resolve

# Trouble rotated across the records: a normal page, a slow portal, a failing-then-working one, a reply that is
# lost after saving, and the reworded page without test ids (browser path only).
# Points a reviewer can confirm as they are (a date read the right way round, the right one of two numbers).
CONFIRMABLE = {"LOW_CONFIDENCE", "AMBIGUOUS_FIELD", "POSSIBLE_DUPLICATE", "AI_MAPPER_UNAVAILABLE"}
MODES: list[dict[str, str]] = [{}, {"chaos": "slow"}, {"chaos": "flaky"}, {"chaos": "lost"}, {"variant": "b"}]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", default="http://localhost:8000")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    settings = get_settings()
    engine = httpx.Client(base_url=args.engine, timeout=180,
                          headers={"Authorization": f"Bearer {settings.operator_token}"})
    portal = httpx.Client(base_url=settings.portal_base_url, timeout=30,
                          headers={"x-portal-key": settings.portal_api_key})
    from datetime import date
    today, tag = date.today(), uuid.uuid4().hex[:6]
    rows = []
    for i, item in enumerate(json.loads(DATASET.read_text())["records"]):
        text = json.dumps(_resolve(item["record"], today))
        text = re.sub(r"@example\.com", f"+{tag}@example.com", text, flags=re.I)
        text = re.sub(r" at example dot com", f"+{tag} at example dot com", text)
        record = json.loads(text)
        intake = engine.post("/api/enrollments", json={"target_form": item["form"], "source": "api", "record": record})
        body = intake.json()
        open_points = {r["code"] for r in body["reasons"] if r["severity"] != "info"}
        if body["outcome"] == "BLOCKED":
            rows.append({"id": item["id"], "skipped": "blocked before submission"})
            continue
        if open_points - CONFIRMABLE:
            # A wrong value (an emergency number that is the member's own) needs a person to change the data;
            # approving it unchanged would only be refused by the portal.
            rows.append({"id": item["id"], "skipped": "needs a person to correct the data first"})
            continue
        if body["status"] != "approved":
            engine.post(f"/api/enrollments/{body['enrollment_id']}/approve", json={"note": "benchmark"})
        mode = MODES[i % len(MODES)]
        if mode.get("variant") and item["form"] != "riverside-enrollment":
            mode = {}
        started = time.perf_counter()
        out = engine.post(f"/api/enrollments/{body['enrollment_id']}/submit", json={"wait": True, **mode}).json()
        took = time.perf_counter() - started
        shown = engine.get(f"/api/enrollments/{body['enrollment_id']}", params={"reveal": "true"}).json()
        email = (shown.get("mapped_payload") or {}).get("email", "")
        lookup = ("/api/portals/riverside/applications" if item["form"] == "riverside-enrollment"
                  else "/api/portals/harbour/members")
        held = portal.get(lookup, params={"email": email}).json() if email else {}
        copies = len(held.get("applications") or held.get("members") or [])
        rows.append({"id": item["id"], "form": item["form"], "mode": mode or {"normal": "1"}, "status": out["status"],
                     "path": out.get("path"), "attempts": out.get("attempts"), "adopted": out.get("adopted"),
                     "healed": len(out.get("healed") or []), "readback": out.get("readback"),
                     "seconds": round(took, 1), "copies_at_portal": copies})
        print(rows[-1])
    sent = [r for r in rows if "status" in r]
    trouble = [r for r in sent if r["mode"].get("chaos") in ("flaky", "lost")]
    summary = {
        "records": len(rows), "sent": len(sent),
        "blocked_first": sum(r.get("skipped") == "blocked before submission" for r in rows),
        "held_for_correction": sum(r.get("skipped") == "needs a person to correct the data first" for r in rows),
        "submitted": sum(r["status"] == "submitted" for r in sent),
        "readback_matched": sum(r["readback"] == "matched" for r in sent),
        "recovered_from_failures": f"{sum(r['status'] == 'submitted' for r in trouble)} of {len(trouble)}",
        "duplicates_at_portal": sum(max(r["copies_at_portal"] - 1, 0) for r in sent),
        "mean_seconds": round(statistics.mean(r["seconds"] for r in sent), 1) if sent else None,
        "median_seconds_browser": round(statistics.median([r["seconds"] for r in sent if r["path"] == "browser"]), 1)
        if any(r["path"] == "browser" for r in sent) else None,
        "median_seconds_api": round(statistics.median([r["seconds"] for r in sent if r["path"] == "api"]), 1)
        if any(r["path"] == "api" for r in sent) else None,
        "healed_locators": sum(r["healed"] for r in sent),
    }
    print(json.dumps(summary, indent=1))
    if args.write:
        result = {"summary": summary, "rows": rows}
        (ROOT / "benchmark" / "results-submit.json").write_text(json.dumps(result, indent=1))
        _append_markdown(summary, rows)
        print("wrote docs/BENCHMARK.md")


def _append_markdown(summary: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    path = ROOT / "docs" / "BENCHMARK.md"
    text = path.read_text().split("\n## Real submissions")[0].rstrip() + "\n"
    text += ("\n## Real submissions\n\nEvery record that could go to a portal, through the running engine and the real "
             "portals in Chromium, with trouble rotated across them (slow, failing then working, a reply lost after "
             "saving, a reworded page without test ids). `python -m scripts.benchmark_submit --write`.\n\n"
             "| | |\n|---|---|\n"
             f"| Sent to a portal | {summary['sent']} of {summary['records']} ({summary['blocked_first']} blocked, "
             f"{summary['held_for_correction']} held for a person to correct) |\n"
             f"| Submitted | {summary['submitted']} of {summary['sent']} |\n"
             f"| Portal record matched what was sent | {summary['readback_matched']} of {summary['sent']} |\n"
             f"| Recovered from a failing or lost-reply portal | {summary['recovered_from_failures']} |\n"
             f"| Duplicates at the portal | {summary['duplicates_at_portal']} |\n"
             f"| Locators healed on the reworded page | {summary['healed_locators']} |\n"
             f"| Median time, web form | {summary['median_seconds_browser']} s |\n"
             f"| Median time, API | {summary['median_seconds_api']} s |\n"
             f"| Mean time, all (including a deliberately slow portal and retries) | {summary['mean_seconds']} s |\n")
    path.write_text(text)


if __name__ == "__main__":
    main()
