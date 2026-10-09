"""Snapshot authorisation and numerical grounding without paid model calls."""

import asyncio
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from cfin.config import Settings
from cfin.insights import (
    ExplainOverviewRequest,
    InsightsService,
    OverviewExplanation,
    OverviewRequest,
    validate_explanation,
)

W = UUID("11111111-1111-4111-8111-111111111111")
A = UUID("22222222-2222-4222-8222-222222222222")
S = UUID("33333333-3333-4333-8333-333333333333")
G = UUID("44444444-4444-4444-8444-444444444444")
R = UUID("55555555-5555-4555-8555-555555555555")
CAVEAT = (
    "These are case counts, not failure rates. Shared objects suggest investigation; "
    "they do not establish a cause."
)


def overview(stale=False):
    return {
        "snapshot": {"id": str(S), "workspace_id": str(W), "stale": stale},
        "metrics": {"unresolved_known_cases": 2, "provisional_cases": 1, "attempts": 5},
        "groups": [{"id": str(G), "dimension": "category", "value": "cause_not_established",
                    "count": 2, "unit": "cases"}],
        "narrative": None,
    }


class User:
    def __init__(self, *, denied=False, stale=False):
        self.calls = []
        self.denied = denied
        self.stale = stale

    async def require_member(self, token, actor, workspace, role=None):
        self.calls.append(("member", actor, workspace, role))
        if self.denied:
            raise HTTPException(403, "Membership revoked")

    async def rpc(self, name, token, payload):
        self.calls.append((name, token, payload))
        if name == "cfin_overview_group":
            return {"group": overview()["groups"][0], "items": [], "total": 2}
        return overview(self.stale)


class Service:
    def __init__(self):
        self.calls = []
        self.execute = True

    async def rpc(self, name, payload):
        self.calls.append((name, payload))
        if name == "cfin_reserve_overview_call":
            return {"execute": self.execute, "run": {"id": str(R)}}
        return overview()


def settings(paid=False):
    return Settings(
        _env_file=None, paid_models_enabled=paid,
        supabase_url="https://example.supabase.co", supabase_publishable_key="public",
        supabase_secret_key="secret", openai_api_key="never-sent", model_agent_4="gpt-6.1-sol",
    )


def run(awaitable):
    return asyncio.run(awaitable)


def test_membership_is_checked_before_creating_or_reading_cached_material():
    user, service = User(denied=True), Service()
    api = InsightsService(user, service, settings())
    with pytest.raises(HTTPException) as exc:
        run(api.create("token", A, OverviewRequest(workspace_id=W)))
    assert exc.value.status_code == 403
    assert len(user.calls) == 1
    assert service.calls == []


def test_refresh_preserves_exact_filters_and_generates_backend_owned_group_links():
    user = User()
    api = InsightsService(user, Service(), settings())
    result = run(api.create("token", A, OverviewRequest(
        workspace_id=W, filters={"priority": "P3", "company_code": "0010"}, refresh=True,
    )))
    request = user.calls[1][2]
    assert request["filters"] == {"priority": "P3", "company_code": "0010"}
    assert request["refresh"] is True
    assert result["groups"][0]["drilldown_url"] == (
        f"/groups?snapshot_id={S}&group_id={G}&workspace_id={W}"
    )
    assert result["narrative"]["status"] == "not_requested"


@pytest.mark.parametrize("page,size", [(0, 25), (1, 0), (1, 51), (-1, 10)])
def test_group_reads_enforce_bounded_pagination(page, size):
    user = User()
    with pytest.raises(HTTPException) as exc:
        run(InsightsService(user, Service(), settings()).group("token", A, W, S, G, page, size))
    assert exc.value.status_code == 422
    assert all(x[0] != "cfin_overview_group" for x in user.calls)


def test_models_disabled_leaves_saved_counts_available_without_reservation():
    service = Service()
    result = run(InsightsService(User(), service, settings()).explain(
        "token", A, S, ExplainOverviewRequest(workspace_id=W),
    ))
    assert result["narrative"]["status"] == "models_disabled"
    assert result["metrics"]["attempts"] == 5
    assert len(result["groups"]) == 1
    assert service.calls == []


def test_expired_or_changed_snapshot_cannot_start_a_model_call():
    service = Service()
    result = run(InsightsService(User(stale=True), service, settings(True)).explain(
        "token", A, S, ExplainOverviewRequest(workspace_id=W),
    ))
    assert result["narrative"]["status"] == "stale"
    assert service.calls == []


@pytest.mark.parametrize("observation", [
    "This affects 2 cases", "A 50% increase", "The failure rate is high", "Ten percent fail",
])
def test_free_text_cannot_smuggle_uncited_numeric_or_rate_claims(observation):
    with pytest.raises(ValidationError):
        OverviewExplanation.model_validate({
            "claims": [{"group_id": str(G), "count": 2, "observation": observation}],
            "caveat": CAVEAT,
        })


@pytest.mark.parametrize("group,count", [(str(G), 3), (str(R), 2)])
def test_wrong_group_or_count_is_rejected(group, count):
    answer = OverviewExplanation.model_validate({
        "claims": [{"group_id": group, "count": count, "observation": "Needs cause review."}],
        "caveat": CAVEAT,
    })
    with pytest.raises(ValueError):
        validate_explanation(answer, overview())


def test_valid_claim_links_are_built_from_exact_group_reference():
    source = InsightsService(User(), Service(), settings())._decorate(overview())
    answer = OverviewExplanation.model_validate({
        "claims": [{"group_id": str(G), "count": 2, "observation": "Needs cause review."}],
        "caveat": CAVEAT,
    })
    result = validate_explanation(answer, source)
    assert result["text"] == "2 cases: Needs cause review."
    assert result["claims"][0]["drilldown_url"] == source["groups"][0]["drilldown_url"]


class Telemetry:
    enabled = True

    def __init__(self, settings, metadata):
        self.metadata = metadata

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def bind_metadata(self, metadata):
        assert set(metadata) == {"stage", "workspace_id", "run_id", "snapshot_id"}
        assert "case_id" not in metadata

    def flush(self, business_committed):
        assert business_committed
        from cfin.arize_tracing import ArizeTraceResult

        return ArizeTraceResult("export_acknowledged")


class Client:
    def __init__(self, **kwargs):
        assert kwargs["max_retries"] == 0

    async def close(self):
        pass


def test_agent4_reserves_before_runner_and_reconciles_observed_usage(monkeypatch):
    service = Service()
    monkeypatch.setattr("cfin.insights.AutoArizeTracing", Telemetry)
    monkeypatch.setattr("cfin.insights.AsyncOpenAI", Client)

    async def runner(agent, payload, **kwargs):
        assert service.calls[0][0] == "cfin_reserve_overview_call"
        assert service.calls[0][1]["max_input_tokens"] == 131072
        assert agent.model_settings.reasoning.effort == "medium"
        assert agent.model_settings.max_tokens == 2048
        assert kwargs["max_turns"] == 4
        return SimpleNamespace(
            context_wrapper=SimpleNamespace(usage=SimpleNamespace(
                requests=1, input_tokens=40, output_tokens=20,
            )), final_output=OverviewExplanation.model_validate({
                "claims": [{"group_id": str(G), "count": 2, "observation": "Needs review."}],
                "caveat": CAVEAT,
            }),
        )

    monkeypatch.setattr("cfin.insights.Runner.run", runner)
    result = run(InsightsService(User(), service, settings(True)).explain(
        "token", A, S, ExplainOverviewRequest(workspace_id=W),
    ))
    assert service.calls[1][0] == "cfin_complete_overview_call"
    assert service.calls[1][1]["usage"] == {"input_tokens": 40, "output_tokens": 20}
    assert service.calls[1][1]["state"] == "succeeded"
    assert result["arize"]["status"] == "export_acknowledged"


def test_unknown_usage_keeps_full_reservation_and_charts_available(monkeypatch):
    service = Service()
    monkeypatch.setattr("cfin.insights.AutoArizeTracing", Telemetry)
    monkeypatch.setattr("cfin.insights.AsyncOpenAI", Client)

    async def runner(*args, **kwargs):
        raise TimeoutError("secret diagnostic")

    monkeypatch.setattr("cfin.insights.Runner.run", runner)
    result = run(InsightsService(User(), service, settings(True)).explain(
        "token", A, S, ExplainOverviewRequest(workspace_id=W),
    ))
    assert service.calls[1][1]["state"] == "usage_unknown"
    assert "secret" not in str(result)
    assert result["narrative"]["status"] == "unavailable"
    assert result["metrics"]["unresolved_known_cases"] == 2


def test_membership_revocation_after_model_commit_prevents_cached_disclosure(monkeypatch):
    user, service = User(), Service()
    original_rpc = service.rpc

    async def cloud(name, payload):
        result = await original_rpc(name, payload)
        if name == "cfin_complete_overview_call":
            user.denied = True
        return result

    service.rpc = cloud
    monkeypatch.setattr("cfin.insights.AutoArizeTracing", Telemetry)
    monkeypatch.setattr("cfin.insights.AsyncOpenAI", Client)

    async def runner(*args, **kwargs):
        return SimpleNamespace(
            context_wrapper=SimpleNamespace(usage=SimpleNamespace(
                requests=1, input_tokens=40, output_tokens=20,
            )), final_output=OverviewExplanation.model_validate({
                "claims": [{"group_id": str(G), "count": 2, "observation": "Needs review."}],
                "caveat": CAVEAT,
            }),
        )

    monkeypatch.setattr("cfin.insights.Runner.run", runner)
    with pytest.raises(HTTPException) as exc:
        run(InsightsService(user, service, settings(True)).explain(
            "token", A, S, ExplainOverviewRequest(workspace_id=W),
        ))
    assert exc.value.status_code == 403
