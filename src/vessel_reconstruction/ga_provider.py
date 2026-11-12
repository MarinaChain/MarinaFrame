"""Commercial GA provider."""
from __future__ import annotations

from .ga_commercial_settings import (
    MODEL,
)
from pathlib import Path
import json
import subprocess


# ------------------------------------------------------------------ the receipted model call

def call_model(binary: Path, request: Path, out: Path, basis: str, model: str = MODEL) -> dict:
    """One receipted ``ga_reading`` request through the Rust controller; returns its reading record."""
    completed = subprocess.run([str(binary), "vision-request", "--request", str(request), "--out", str(out),
                                "--provider-transfer-basis", basis, "--model", model],
                               capture_output=True, text=True)
    reading_path = Path(out) / "vision_reading.json"
    if reading_path.exists():
        return json.loads(reading_path.read_text())
    return failed_reading(Path(out), model, completed.stderr)


def failed_reading(out: Path, model: str, stderr: str) -> dict:
    """A reading record for a request that wrote none, built from the receipts on disk.

    Every receipt is a request that counts against the budget; with no reply, every value of
    the case becomes an abstention (``interpret``), not a missing output.
    """
    receipts = [json.loads(path.read_text()) for path in sorted((out / "receipts").glob("*.json"))]
    usage = {"requests_intended": len(receipts),
             "requests_completed": sum(r.get("state") == "completed" for r in receipts),
             "prompt_tokens": sum((r.get("usage") or {}).get("prompt_tokens", 0) for r in receipts),
             "completion_tokens": sum((r.get("usage") or {}).get("completion_tokens", 0) for r in receipts),
             "observed_cost_usd": sum(r.get("observed_cost_usd") or 0.0 for r in receipts)}
    try:
        error = json.loads(stderr.strip().splitlines()[-1]).get("error_code")
    except (ValueError, IndexError, AttributeError):
        error = "unreadable_error"
    return {"requested_model": model, "endpoint": None, "usage": usage, "receipts": receipts, "reply": None,
            "stop_reason": f"vision_request_failed: {error}"}


def usage_of(reading: dict) -> dict:
    """Requests, tokens and the CLI's API-price estimate (``list_cost``) of one reading."""
    receipts = reading.get("receipts") or []
    list_cost = sum((r.get("usage") or {}).get("list_cost") or 0.0 for r in receipts)
    usage = reading.get("usage") or {}
    return {"requests": usage.get("requests_intended", len(receipts)),
            "completed": usage.get("requests_completed", 0),
            "prompt_tokens": usage.get("prompt_tokens", 0), "completion_tokens": usage.get("completion_tokens", 0),
            "observed_cost_usd": usage.get("observed_cost_usd", 0.0), "list_cost_usd": round(list_cost, 6),
            "model": reading.get("requested_model"), "endpoint": reading.get("endpoint")}


def add_usage(total: dict, more: dict) -> dict:
    """The sum of two usage records (``usage_of``)."""
    keys = ("requests", "completed", "prompt_tokens", "completion_tokens", "observed_cost_usd", "list_cost_usd")
    return {**total, **{key: round(total.get(key, 0) + more.get(key, 0), 6) for key in keys}}
