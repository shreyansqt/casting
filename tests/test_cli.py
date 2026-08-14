from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).parents[1]
POLICY = ROOT / "tests" / "fixtures" / "pwc-daf1738-routing-policy.json"


def run_casting(*args: str, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ROOT / "bin" / "casting"), *args],
        input=input_text,
        capture_output=True,
        text=True,
        check=False,
    )


def test_route_cli_emits_versioned_contract() -> None:
    result = run_casting(
        "route",
        "--key",
        "fixture-14-1201",
        "--domain",
        "implementation",
        "--reasoning",
        "4",
        "--verifiability",
        "4",
        "--context-need",
        "200000",
        "--policy",
        str(POLICY),
    )
    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    assert output["schema_version"] == 1
    assert output["stable_key"] == "fixture-14-1201"
    assert output["harness"] == "claude"
    assert output["model"] == "opus"
    assert "candidates" not in output


def test_route_cli_accepts_complete_request_on_stdin() -> None:
    request = {
        "profile": {
            "stable_key": "fixture-14-1206",
            "domain": "implementation",
            "reasoning": 3,
        },
        "policy": json.loads(POLICY.read_text()),
    }
    result = run_casting("route", "--request", "-", "--explain", input_text=json.dumps(request))
    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    assert output["harness"] == "codex"
    assert output["candidates"]
    assert output["rejected"]


def test_cli_rejects_unknown_protocol_version() -> None:
    result = run_casting("--protocol-version", "2", "route", "--request", "-", input_text="{}")
    assert result.returncode == 2
    assert "unsupported protocol version 2; supported: 1" in result.stderr


def test_cli_reports_no_qualifying_model_without_traceback() -> None:
    request = {
        "profile": {"stable_key": "work", "domain": "implementation", "reasoning": 5},
        "policy": {
            "version": 1,
            "models": [
                {
                    "key": "ghost",
                    "harness": "test",
                    "model": "ghost",
                    "available": False,
                    "tiers": {"implementation": 5},
                }
            ],
            "overlay": {},
            "preferences": {},
        },
    }
    result = run_casting("route", "--request", "-", input_text=json.dumps(request))
    assert result.returncode == 1
    assert "There is no fallback chain by design" in result.stderr
    assert "Traceback" not in result.stderr
