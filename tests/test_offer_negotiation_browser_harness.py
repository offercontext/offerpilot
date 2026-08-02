from __future__ import annotations

import re
from pathlib import Path


HARNESS = Path(__file__).parents[1] / "scripts" / "offer-negotiation-real-ai-browser-harness.ps1"


def test_offer_negotiation_harness_isolated_and_fail_closed() -> None:
    script = HARNESS.read_text(encoding="utf-8")
    assert "OFFER_NEGOTIATION_CDP_URL" in script
    assert "browser-network-audit.py" in script
    assert "provider-egress-proxy.py" in script
    assert "finally" in script
    assert "offer_negotiation_provider_error" in script
    assert "offer_negotiation_unverifiable" in script
    assert "offer_negotiation_proposal" in script
    assert "offer-negotiation/proposals" in script
    assert "Chat" in script
    assert "throw" in script


def test_harness_output_is_ascii_and_checks_the_complete_browser_sequence() -> None:
    script = HARNESS.read_text(encoding="utf-8")
    output_lines = [
        line
        for line in script.splitlines()
        if re.search(r"\b(?:Write-Host|throw)\b", line)
    ]
    assert all(line.isascii() for line in output_lines)
    for marker in (
        "comparison",
        "negotiation/proposals",
        "/confirm",
        "history",
        "provider_request_id",
        "source_changed",
    ):
        assert marker in script


def test_harness_does_not_classify_502_by_status_alone() -> None:
    script = HARNESS.read_text(encoding="utf-8")
    assert "offer_negotiation_provider_error" in script
    assert "offer_negotiation_unverifiable" in script
    assert "status -eq 502" not in script
    assert "error_code" in script
