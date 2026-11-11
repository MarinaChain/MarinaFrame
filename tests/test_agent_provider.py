"""Provider boundary tests are mock evidence, never model-quality evidence."""
import base64
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
import threading
import time

from PIL import Image
import pytest

from vessel_reconstruction.agent_provider import (
    AgentProviderError, BUDGET_ENDPOINT, GO_ENDPOINT, GO_MODEL,
    OpenCodeGoAgentProvider, ReplayAgentProvider, TransportResponse,
    USAGE_ENDPOINT, observation_hash, export_replay_transcript, verify_replay_transcript,
)
from vessel_reconstruction.provenance import digest_object


TOOLS = [{"name": "inspect_candidate", "description": "Inspect a candidate by ID.",
          "parameters": {"type": "object", "properties": {"candidate_id": {"type": "string"}},
                         "required": ["candidate_id"], "additionalProperties": False}}]
OBS = {"task": "Inspect source evidence", "candidates": ["candidate-1"]}
DECISION = {"tool": "inspect_candidate", "arguments": {"candidate_id": "candidate-1"},
            "reason": "Inspect the candidate before choosing a reconstruction."}


def encoded(value):
    return json.dumps(value).encode()


def allowance(percent=0):
    resets = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    return {"usage": {name: {"status": "ok", "percent": percent, "resetsAt": resets}
                      for name in ("rolling", "weekly", "monthly")}}


def completion(decision=DECISION, **overrides):
    result = {"id": "completion-1", "model": GO_MODEL,
              "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(decision)}}],
              "usage": {"prompt_tokens": 100, "completion_tokens": 30, "total_tokens": 130,
                        "cost": 0, "opencode": {"billing_source": "go", "list_cost": 0.00003,
                                                "allowance": 0.000018}}}
    result.update(overrides)
    return result


class FakeTransport:
    def __init__(self, *, budget=None, usage=None, result=None, status=200):
        self.budget = [{"limitDollars": 0, "coverage": "all"}] if budget is None else budget
        self.usage = allowance() if usage is None else usage
        self.result = completion() if result is None else result
        self.status = status
        self.requests = []

    def __call__(self, method, url, body, headers, timeout, limit):
        self.requests.append({"method": method, "url": url, "body": body,
                              "headers": headers, "timeout": timeout, "limit": limit})
        if url == BUDGET_ENDPOINT:
            return TransportResponse(200, encoded(self.budget))
        if url == USAGE_ENDPOINT:
            return TransportResponse(200, encoded(self.usage))
        return TransportResponse(self.status, self.result if isinstance(self.result, bytes) else encoded(self.result),
                                 "request-1")


def provider(transport=None, **kwargs):
    return OpenCodeGoAgentProvider(api_key="test-key-never-retained", authorized_external_data=True,
                                  transport=transport or FakeTransport(), **kwargs)


def image_evidence():
    b = io.BytesIO()
    Image.new("RGB", (32, 32), "red").save(b, format="PNG")
    raw = b.getvalue()
    return {"artifact_id": "synthetic-image-1", "sha256": hashlib.sha256(raw).hexdigest(),
            "mime_type": "image/png", "data_base64": base64.b64encode(raw).decode()}


def test_one_json_action_is_bounded_and_distinguished_from_live():
    transport = FakeTransport()
    p = provider(transport)
    out = p.decide(OBS, TOOLS, [])
    assert out["decision"] == DECISION
    receipt = out["receipt"]
    assert receipt["evidence_mode"] == "mock_transport"
    assert receipt["observed_cost_usd"] == 0
    assert receipt["usage"]["billing_source"] == "go"
    assert receipt["generation_attempted"] and receipt["hard_zero_cash_guard_verified"]
    assert receipt["observation_sha256"] == observation_hash(OBS, TOOLS, [])
    assert "test-key" not in json.dumps(out)
    assert "Authorization" not in json.dumps(out)
    sent = transport.requests[-1]
    request = json.loads(sent["body"])
    assert sent["url"] == GO_ENDPOINT
    assert request["model"] == GO_MODEL and request["max_tokens"] == 1024
    assert request["stream"] is False
    assert "tools" not in request  # One typed domain action; no native multi-tool execution.
    assert sent["headers"]["x-opencode-session"] == p.session_id


def test_budget_read_403_does_not_become_a_cash_authorization():
    calls = []

    def denied(*args):
        calls.append(args)
        return TransportResponse(403, b"forbidden")

    p = provider(denied)
    with pytest.raises(AgentProviderError) as exc:
        p.decide(OBS, TOOLS, [])
    assert exc.value.code == "forbidden"
    assert p.calls == 0 and len(calls) == 1
    assert exc.value.receipt["generation_attempted"] is False
    assert exc.value.receipt["latency_seconds"] >= 0
    with pytest.raises(AgentProviderError, match="stopped"):
        p.decide(OBS, TOOLS, [])
    assert len(calls) == 1


@pytest.mark.parametrize("budget", [[], [{"limitDollars": 10, "coverage": "all"}],
                                     [{"limitDollars": 0, "coverage": "models", "models": []}],
                                     [{"limitDollars": False, "coverage": "all"}]])
def test_guard_cannot_be_missing_positive_narrow_or_boolean(budget):
    transport = FakeTransport(budget=budget)
    p = provider(transport)
    with pytest.raises(AgentProviderError) as exc:
        p.decide(OBS, TOOLS, [])
    assert exc.value.code == "cash_guard_unverified"
    assert p.calls == 0
    assert all(r["method"] == "GET" for r in transport.requests)


def test_fresh_allowance_is_explicit_rechecked_and_not_a_hard_cash_cap():
    transport = FakeTransport()
    p = provider(transport, admission_mode="fresh_observed_included_allowance")
    a = p.decide(OBS, TOOLS, [])
    p.decide({**OBS, "step": 2}, TOOLS, [])
    assert [r["url"] for r in transport.requests] == [USAGE_ENDPOINT, GO_ENDPOINT, USAGE_ENDPOINT, GO_ENDPOINT]
    assert a["receipt"]["hard_zero_cash_guard_verified"] is False
    assert a["receipt"]["admission_mode"] == "fresh_observed_included_allowance"
    preflight = p.preflight_receipts[-1]
    assert preflight["minimum_headroom_equivalent_usd"] >= preflight["required_headroom_equivalent_usd"]
    assert preflight["concurrent_external_consumption_risk"] is True


@pytest.mark.parametrize("usage", [{}, allowance(100), allowance(98), allowance(-1),
                                    {"usage": {"rolling": {"status": "ok", "percent": 0}}}])
def test_fresh_allowance_blocks_missing_exhausted_or_insufficient_headroom(usage):
    t = FakeTransport(usage=usage)
    p = provider(t, admission_mode="fresh_observed_included_allowance")
    with pytest.raises(AgentProviderError) as exc:
        p.decide(OBS, TOOLS, [])
    assert exc.value.code == "allowance_unavailable"
    assert p.calls == 0


@pytest.mark.parametrize("status,code", [(401, "unauthorized"), (403, "forbidden"),
                                        (429, "rate_limited"), (503, "provider_http_error"),
                                        (302, "redirect_rejected")])
def test_provider_failure_is_terminal_and_not_retried(status, code):
    t = FakeTransport(status=status)
    p = provider(t)
    with pytest.raises(AgentProviderError) as exc:
        p.decide(OBS, TOOLS, [])
    assert exc.value.code == code
    assert p.calls == 1 and len(t.requests) == 3
    with pytest.raises(AgentProviderError):
        p.decide(OBS, TOOLS, [])
    assert len(t.requests) == 3


@pytest.mark.parametrize("payload", [b'{"x":', b'{"x":1,"x":2}', b'{"x":NaN}', b"[]"])
def test_malformed_provider_json_never_produces_an_action(payload):
    p = provider(FakeTransport(result=payload))
    with pytest.raises(AgentProviderError) as exc:
        p.decide(OBS, TOOLS, [])
    assert exc.value.code == "malformed_response"
    assert p.last_receipt["observed_cost_usd"] is None


@pytest.mark.parametrize("decision", [[DECISION], {**DECISION, "approved": True},
                                       {**DECISION, "tool": "execute_shell"},
                                       {**DECISION, "reason": "x" * 513},
                                       {**DECISION, "arguments": []}])
def test_decision_is_exactly_one_allowlisted_action(decision):
    p = provider(FakeTransport(result=completion(decision)))
    with pytest.raises(AgentProviderError) as exc:
        p.decide(OBS, TOOLS, [])
    assert exc.value.code == "invalid_decision"


def test_truncated_and_native_multitool_outputs_are_rejected():
    truncated = completion()
    truncated["choices"][0]["finish_reason"] = "length"
    with pytest.raises(AgentProviderError) as exc:
        provider(FakeTransport(result=truncated)).decide(OBS, TOOLS, [])
    assert exc.value.code == "incomplete_response"
    native = completion()
    native["choices"][0]["message"]["tool_calls"] = [{"function": {"name": "inspect_candidate"}}]
    with pytest.raises(AgentProviderError) as exc:
        provider(FakeTransport(result=native)).decide(OBS, TOOLS, [])
    assert exc.value.code == "invalid_decision"


def test_response_bytes_and_model_identity_are_checked():
    with pytest.raises(AgentProviderError) as exc:
        provider(FakeTransport(result=b" " * 131_073)).decide(OBS, TOOLS, [])
    assert exc.value.code == "response_limit"
    with pytest.raises(AgentProviderError) as exc:
        provider(FakeTransport(result=completion(model="other-model"))).decide(OBS, TOOLS, [])
    assert exc.value.code == "model_identity"


def test_unknown_cost_stays_unknown_and_fresh_allowance_stops():
    p = provider(FakeTransport(result=completion(usage={})))
    assert p.decide(OBS, TOOLS, [])["receipt"]["observed_cost_usd"] is None
    p = provider(FakeTransport(result=completion(usage={})), admission_mode="fresh_observed_included_allowance")
    with pytest.raises(AgentProviderError) as exc:
        p.decide(OBS, TOOLS, [])
    assert exc.value.code == "usage_unverified"
    assert exc.value.receipt["observed_cost_usd"] is None


def test_reported_cash_spend_stops_further_requests():
    result = completion(usage={"cost": 0.002, "opencode": {"billing_source": "balance"}})
    p = provider(FakeTransport(result=result))
    with pytest.raises(AgentProviderError) as exc:
        p.decide(OBS, TOOLS, [])
    assert exc.value.code == "unexpected_cash_charge"
    assert exc.value.receipt["observed_cost_usd"] == 0.002
    with pytest.raises(AgentProviderError, match="stopped"):
        p.decide(OBS, TOOLS, [])


def test_input_pixels_are_verified_and_receipts_contain_no_base64():
    image = image_evidence()
    t = FakeTransport()
    p = provider(t)
    out = p.decide(OBS, TOOLS, [image])
    assert out["receipt"]["input_mode"] == "vision"
    assert image["data_base64"] not in json.dumps(out)
    request = json.loads(t.requests[-1]["body"])
    assert request["messages"][1]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")
    altered = {**image, "sha256": "0" * 64}
    t2 = FakeTransport()
    with pytest.raises(AgentProviderError, match="Image bytes"):
        provider(t2).decide(OBS, TOOLS, [altered])
    assert not t2.requests


def test_metadata_without_pixels_is_labeled_text_only():
    image = image_evidence()
    del image["data_base64"]
    out = provider().decide(OBS, TOOLS, [image])
    assert out["receipt"]["input_mode"] == "text"
    assert out["receipt"]["images"][0]["pixels_attached"] is False


def test_missing_key_and_data_authorization_do_not_dispatch(monkeypatch):
    monkeypatch.delenv("OPENCODE_API_KEY", raising=False)
    t = FakeTransport()
    p = OpenCodeGoAgentProvider(authorized_external_data=True, transport=t)
    with pytest.raises(AgentProviderError) as exc:
        p.decide(OBS, TOOLS, [])
    assert exc.value.code == "missing_credential" and not t.requests
    p = OpenCodeGoAgentProvider(api_key="test-key", transport=t)
    with pytest.raises(AgentProviderError) as exc:
        p.decide(OBS, TOOLS, [])
    assert exc.value.code == "external_data_not_authorized" and not t.requests


def test_output_budget_reserved_before_dispatch():
    p = provider(max_requests=3, max_total_output_tokens=1024)
    p.decide(OBS, TOOLS, [])
    assert p.reserved_output_tokens == 1024
    with pytest.raises(AgentProviderError) as exc:
        p.decide(OBS, TOOLS, [])
    assert exc.value.code == "request_budget"
    assert p.calls == 1


def test_timeout_and_cancel_do_not_wait_for_network_completion():
    gate = threading.Event()

    def slow(*args):
        gate.wait(1)
        return TransportResponse(200, encoded([]))

    p = provider(slow, timeout_seconds=0.06)
    started = time.monotonic()
    with pytest.raises(AgentProviderError) as exc:
        p.decide(OBS, TOOLS, [])
    assert exc.value.code == "timeout" and time.monotonic() - started < 0.5
    cancel = threading.Event()
    p = provider(slow, cancel=cancel, timeout_seconds=1)
    threading.Timer(0.04, cancel.set).start()
    started = time.monotonic()
    with pytest.raises(AgentProviderError) as exc:
        p.decide(OBS, TOOLS, [])
    assert exc.value.code == "cancelled" and time.monotonic() - started < 0.5
    gate.set()


def test_replay_requires_same_observation_tools_and_pixels():
    result = provider().decide(OBS, TOOLS, [])
    replay = ReplayAgentProvider([result])
    with pytest.raises(AgentProviderError) as exc:
        replay.decide({**OBS, "task": "Changed"}, TOOLS, [])
    assert exc.value.code == "replay_mismatch" and replay.calls == 0
    out = replay.decide(OBS, TOOLS, [])
    assert out["decision"] == DECISION and out["receipt"]["evidence_mode"] == "replay"
    assert out["receipt"]["origin_evidence_mode"] == "mock_transport"
    assert out["receipt"]["generation_attempted"] is False
    with pytest.raises(AgentProviderError) as exc:
        replay.decide(OBS, TOOLS, [])
    assert exc.value.code == "replay_exhausted"


def test_replay_hash_is_sensitive_to_pixel_presence_and_tool_contract():
    image = image_evidence()
    without_pixels = {k: v for k, v in image.items() if k != "data_base64"}
    assert observation_hash(OBS, TOOLS, [image]) != observation_hash(OBS, TOOLS, [without_pixels])
    altered_tools = [{**TOOLS[0], "description": "A different instruction"}]
    assert observation_hash(OBS, TOOLS, []) != observation_hash(OBS, altered_tools, [])


def event_chain(result, images=None):
    images = images or []
    request = {"observation": OBS, "observation_sha256": digest_object(OBS),
               "images": [{k: v for k, v in image.items() if k != "data_base64"} for image in images]}
    events = []
    for kind, payload in [("policy_requested", request), ("decision", result)]:
        event = {"sequence": len(events) + 1,
                 "previous_sha256": events[-1]["event_sha256"] if events else None,
                 "kind": kind, "payload": payload, "state_after": {}}
        event["event_sha256"] = digest_object(event)
        events.append(event)
    return events


def test_export_and_verify_exact_recorded_text_decisions_without_running_cad():
    result = provider().decide(OBS, TOOLS, [])
    transcript = export_replay_transcript(event_chain(result), TOOLS)
    verification = verify_replay_transcript(transcript)
    assert verification["verified"] and verification["replayed_decisions"] == 1
    assert verification["generation_requests"] == 0 and verification["cad_operations_executed"] == 0
    assert verification["origin_evidence_modes"] == ["mock_transport"]
    assert transcript["external_authenticity_proven"] is False


def test_image_transcript_requires_verified_pixels_and_detects_changed_observation():
    image = image_evidence()
    result = provider().decide(OBS, TOOLS, [image])
    events = event_chain(result, [image])
    with pytest.raises(AgentProviderError) as exc:
        export_replay_transcript(events, TOOLS)
    assert exc.value.code == "replay_images_required"
    loader = lambda metadata: base64.b64decode(image["data_base64"])
    transcript = export_replay_transcript(events, TOOLS, image_loader=loader)
    assert verify_replay_transcript(transcript)["verified"]
    transcript["records"][0]["observation"] = {**OBS, "task": "Changed after capture"}
    with pytest.raises(AgentProviderError) as exc:
        verify_replay_transcript(transcript)
    assert exc.value.code == "replay_mismatch"
    with pytest.raises(AgentProviderError, match="Image bytes"):
        export_replay_transcript(events, TOOLS, image_loader=lambda metadata: b"changed")


def test_transcript_export_rejects_tampered_event_chain():
    result = provider().decide(OBS, TOOLS, [])
    events = event_chain(result)
    events[0]["payload"]["observation"] = {"task": "tampered"}
    with pytest.raises(AgentProviderError, match="event chain"):
        export_replay_transcript(events, TOOLS)


def test_replay_rejects_changed_prompt_even_when_observation_matches():
    result = provider().decide(OBS, TOOLS, [])
    result["receipt"]["prompt_sha256"] = "0" * 64
    with pytest.raises(AgentProviderError, match="prompt or protocol"):
        ReplayAgentProvider([result]).decide(OBS, TOOLS, [])


def test_controller_interface_marks_live_and_image_support_without_network():
    p = OpenCodeGoAgentProvider(api_key="test-key")
    assert p.kind == "live" and p.supports_images is True
    assert provider().kind == "mock_provider"
    with pytest.raises(AgentProviderError, match="eight"):
        provider(admission_mode="fresh_observed_included_allowance", max_requests=9)


def test_provider_rejects_credential_echo_without_retaining_it():
    decision = {**DECISION, "reason": "test-key-never-retained"}
    p = provider(FakeTransport(result=completion(decision)))
    with pytest.raises(AgentProviderError) as exc:
        p.decide(OBS, TOOLS, [])
    assert exc.value.code == "credential_echo"
    assert "test-key-never-retained" not in str(exc.value)
    assert "test-key-never-retained" not in json.dumps(exc.value.receipt)


@pytest.mark.parametrize("prior", [-1, 33, True, 1.0, "6"])
def test_prior_reservations_require_a_bounded_integer(prior):
    with pytest.raises(AgentProviderError, match="Prior generation"):
        provider(prior_generation_reservations=prior)


def test_prior_attempts_consume_fresh_allowance_headroom_even_in_new_instance():
    # Four conservative reservations need more headroom than this meter has.
    t = FakeTransport(usage=allowance(80))
    p = provider(t, admission_mode="fresh_observed_included_allowance", prior_generation_reservations=3)
    with pytest.raises(AgentProviderError) as exc:
        p.decide(OBS, TOOLS, [])
    assert exc.value.code == "allowance_unavailable" and p.calls == 0
    assert len(t.requests) == 1 and t.requests[0]["url"] == USAGE_ENDPOINT
    # The same meter admits one reservation, establishing that the prior count
    # changes the gate rather than merely being reported in a receipt.
    assert provider(FakeTransport(usage=allowance(80)), admission_mode="fresh_observed_included_allowance").decide(
        OBS, TOOLS, [])["receipt"]["status"] == "decision_validated"


def test_prior_reservations_are_retained_in_receipts_and_fourfold_gate():
    p = provider(admission_mode="fresh_observed_included_allowance", prior_generation_reservations=6)
    result = p.decide(OBS, TOOLS, [])
    assert result["receipt"]["prior_generation_reservations"] == 6
    assert result["receipt"]["cumulative_generation_reservations"] == 7
    admission = p.preflight_receipts[-1]
    assert admission["required_headroom_equivalent_usd"] == pytest.approx(
        4 * admission["request_reservation_equivalent_usd"] * 7)
