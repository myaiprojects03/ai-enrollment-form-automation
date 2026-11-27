"""The n8n exports: well-formed, wired up, and free of secrets (they read settings with $env)."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

N8N = Path(__file__).resolve().parents[2] / "n8n"
FILES = sorted(N8N.glob("*.json"))


def test_there_are_three_workflows() -> None:
    assert [f.name for f in FILES] == ["01-intake-relay.json", "02-scheduled-submitter.json", "03-morning-digest.json"]


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_workflow_is_connected_and_holds_no_secrets(path: Path) -> None:
    wf = json.loads(path.read_text())
    names = {n["name"] for n in wf["nodes"]}
    assert len(names) == len(wf["nodes"])
    for source, outputs in wf["connections"].items():
        assert source in names
        for branch in outputs["main"]:
            assert all(link["node"] in names for link in branch)
    reached = {link["node"] for out in wf["connections"].values() for b in out["main"] for link in b}
    triggers = {n["name"] for n in wf["nodes"] if n["type"].endswith(("Trigger", ".webhook"))}
    assert names == reached | triggers, "every node is reached from a trigger"
    text = path.read_text()
    assert "Bearer {{ $env.ENGINE_TOKEN }}" in text or "WEBHOOK_SECRET" in text
    assert not re.search(r"(sk|gsk)_[A-Za-z0-9]{10,}|Bearer [A-Za-z0-9_-]{20,}", text)
    assert "localhost" not in text, "addresses come from ENGINE_URL"


def test_the_relay_signs_exactly_what_it_sends() -> None:
    wf = json.loads((N8N / "01-intake-relay.json").read_text())
    sign = next(n for n in wf["nodes"] if n["type"] == "n8n-nodes-base.crypto")["parameters"]
    send = next(n for n in wf["nodes"] if n["name"] == "Send to the engine")["parameters"]
    assert sign["value"] == send["body"] == "={{ $json.payload }}"
    assert send["contentType"] == "raw" and sign["type"] == "SHA256"
