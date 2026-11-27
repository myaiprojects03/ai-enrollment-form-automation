"""Benchmark: 24 synthetic records in the shapes they really arrive in, against the values a careful person would
enter and the outcome the system should reach (benchmark/dataset.json).

    python -m scripts.benchmark             # rules plus the AI mapper configured in .env
    python -m scripts.benchmark --no-ai     # rules only, for comparison
    python -m scripts.benchmark --write     # also write docs/BENCHMARK.md and benchmark/results-*.json

What it measures, per record and overall:
- field accuracy: expected fields whose mapped value is right (missing and wrong are counted separately);
- outcome accuracy: PASS / NEEDS_REVIEW / BLOCKED as expected;
- safety: wrong values in records that PASS (sent without a person looking). This one must be zero;
- automation: share of records that pass, and how many needed the AI.
No database, portal or network is needed except the AI provider. Nothing is submitted.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.forms.registry import get_form
from app.mapping.llm import build_llm
from app.mapping.mapper import Mapper
from app.submit.compare import same
from app.validation.outcome import judge

ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / "benchmark" / "dataset.json"


def _resolve(value: Any, today: date) -> Any:
    """'+14d' -> an ISO date 14 days from today; '{{+12d}}' inside text -> '8 December 2026'."""
    if isinstance(value, dict):
        return {k: _resolve(v, today) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve(v, today) for v in value]
    if isinstance(value, str):
        m = re.fullmatch(r"\+(\d+)d", value)
        if m:
            return (today + timedelta(days=int(m[1]))).isoformat()
        return re.sub(r"\{\{\+(\d+)d\}\}", lambda x: (today + timedelta(days=int(x[1]))).strftime("%-d %B %Y"),
                      value)
    return value


async def run(use_ai: bool) -> dict[str, Any]:
    settings = get_settings()
    llm = build_llm(settings.llm_provider, groq_api_key=settings.groq_api_key, groq_model=settings.groq_model,
                    anthropic_api_key=settings.anthropic_api_key, anthropic_model=settings.anthropic_model) \
        if use_ai else None
    mapper = Mapper(llm, settings.llm_free_text)
    today = date.today()
    rows = []
    for item in json.loads(DATASET.read_text())["records"]:
        form = get_form(item["form"])
        record, expected = _resolve(item["record"], today), _resolve(item["expected"], today)
        started = time.perf_counter()
        mapping = await mapper.map(form, record, today)
        verdict = judge(form, mapping, today, settings.review_threshold)
        took = time.perf_counter() - started
        types = {f.name: f.type for f in form.fields}
        right, wrong, missing = [], [], []
        for name, want in expected.items():
            got = verdict.payload.get(name)
            if got is None and want not in (None, "", False, []):
                missing.append(name)
            elif same(types[name], want, got):
                right.append(name)
            else:
                wrong.append(name)
        rows.append({"id": item["id"], "form": item["form"], "source": item["source"], "note": item["note"],
                     "needs_ai": item["needs_ai"], "expected_outcome": item["expected_outcome"],
                     "outcome": verdict.outcome.value, "fields": len(expected), "right": len(right),
                     "wrong": wrong, "missing": missing, "ai_used": mapping.llm_used, "ai_error": mapping.llm_error,
                     "seconds": round(took, 2),
                     "reasons": sorted({r.code for r in verdict.reasons if r.severity != "info"})})
    total = sum(r["fields"] for r in rows)
    passed = [r for r in rows if r["outcome"] == "PASS"]
    return {
        "mode": f"rules + {llm.name}" if llm else "rules only", "date": today.isoformat(), "records": len(rows),
        "field_accuracy": round(sum(r["right"] for r in rows) / total, 4),
        "wrong_values": sum(len(r["wrong"]) for r in rows), "missing_values": sum(len(r["missing"]) for r in rows),
        "outcome_accuracy": round(sum(r["outcome"] == r["expected_outcome"] for r in rows) / len(rows), 4),
        "passed": len(passed), "wrong_values_in_passed": sum(len(r["wrong"]) + len(r["missing"]) for r in passed),
        "ai_calls": sum(r["ai_used"] for r in rows),
        "mean_seconds": round(sum(r["seconds"] for r in rows) / len(rows), 2),
        "rows": rows,
    }


def markdown(results: list[dict[str, Any]]) -> str:
    out = ["# Benchmark", "",
           "24 synthetic records (12 per portal) in the shapes they arrive in: spreadsheet exports, nested JSON, an",
           "emailed form, call and reception notes. Each has the values a careful person would enter and the outcome",
           "the system should reach. Regenerate with `python -m scripts.benchmark --write` (and `--no-ai`).", "",
           "| | " + " | ".join(r["mode"] for r in results) + " |", "|---|" + "---|" * len(results)]
    def line(label: str, fmt: Any) -> None:
        out.append(f"| {label} | " + " | ".join(fmt(r) for r in results) + " |")
    line("Field accuracy", lambda r: f"{r['field_accuracy'] * 100:.1f}%")
    line("Wrong values", lambda r: str(r["wrong_values"]))
    line("Values not found", lambda r: str(r["missing_values"]))
    line("Outcome as expected", lambda r: f"{round(r['outcome_accuracy'] * r['records'])} of {r['records']}")
    line("Passed without a person", lambda r: f"{r['passed']} of {r['records']}")
    line("Wrong or missing values in passed records", lambda r: str(r["wrong_values_in_passed"]))
    line("Records that needed the AI", lambda r: str(r["ai_calls"]))
    line("Mean time per record", lambda r: f"{r['mean_seconds']} s")
    best = results[0]
    out += ["", f"## Record by record ({best['mode']})", "",
            "| Record | Shape | What it tests | Expected | Got | Fields right | Reasons |",
            "|---|---|---|---|---|---|---|"]
    for r in best["rows"]:
        issues = ", ".join(r["wrong"] + [f"{m} (not found)" for m in r["missing"]])
        out.append(f"| {r['id']} | {r['source']} | {r['note']} | {r['expected_outcome']} | {r['outcome']} | "
                   f"{r['right']}/{r['fields']}{' (' + issues + ')' if issues else ''} | "
                   f"{', '.join(str(c).lower().replace('_', ' ') for c in r['reasons']) or '-'} |")
    return "\n".join(out) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-ai", action="store_true")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    result = asyncio.run(run(not args.no_ai))
    summary = {k: v for k, v in result.items() if k != "rows"}
    print(json.dumps(summary, indent=1))
    for r in result["rows"]:
        flag = "ok " if r["outcome"] == r["expected_outcome"] and not r["wrong"] and not r["missing"] else "-- "
        print(f"{flag}{r['id']} {r['expected_outcome']:>12} -> {r['outcome']:<12} fields {r['right']}/{r['fields']}"
              f" wrong={r['wrong']} missing={r['missing']} {r['reasons']}")
    if args.write:
        tag = "rules" if args.no_ai else "ai"
        (ROOT / "benchmark" / f"results-{tag}.json").write_text(json.dumps(result, indent=1))
        found = [json.loads(p.read_text()) for p in (ROOT / "benchmark" / "results-ai.json",
                                                      ROOT / "benchmark" / "results-rules.json") if p.exists()]
        found.sort(key=lambda r: r["mode"] == "rules only")   # the AI run first
        report = ROOT / "docs" / "BENCHMARK.md"
        kept = report.read_text().split("\n## Real submissions", 1) if report.exists() else [""]
        report.write_text(markdown(found) + ("\n## Real submissions" + kept[1] if len(kept) > 1 else ""))
        print("wrote docs/BENCHMARK.md")


if __name__ == "__main__":
    main()
