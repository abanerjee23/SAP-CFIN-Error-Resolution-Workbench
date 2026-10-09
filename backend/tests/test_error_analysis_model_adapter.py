"""Hard information-boundary checks before a paid Error Analysis dispatch."""

import pytest

from cfin.config import Settings
from cfin.error_analysis_contracts import CaseContent, ErrorAnalysisDraft
from cfin.error_analysis_prompts import ERROR_ANALYSIS_PROMPT_VERSIONS
from cfin.log_only_contracts import ExtractedLog
from cfin.model_adapter import OpenAIStageAdapter


class Ledger:
    cached_outputs = {}


def adapter() -> OpenAIStageAdapter:
    return OpenAIStageAdapter(
        Settings(
            _env_file=None,
            supabase_url="https://synthetic-test.supabase.co",
            supabase_publishable_key="test-publishable",
            supabase_secret_key="test-worker-secret",
            openai_api_key="test-api-key",
            paid_models_enabled=True,
        ),
        Ledger(),
        workflow_version="error-analysis-v1",
    )


def binding() -> dict[str, object]:
    return {
        "workspace_id": "workspace-1",
        "run_id": "run-1",
        "case_id": "case-1",
        "attempt_id": "attempt-1",
        "input_revision": "revision-1",
        "workflow_version": "error-analysis-v1",
        "schema_version": "error-analysis-v1",
        "source_manifest_sha256": "a" * 64,
        "prompt_versions": dict(ERROR_ANALYSIS_PROMPT_VERSIONS),
        "model_configuration": {
            "agent1": "gpt-6-luna",
            "agent2": "gpt-6.1-sol",
            "agent3": "gpt-6.1-sol",
            "reasoning_effort": "medium",
        },
    }


def extraction() -> dict[str, object]:
    return ExtractedLog(
        entries=[
            {
                "entry_id": "entry-1",
                "source_id": "source-1",
                "source_version": "1",
                "kind": "message",
                "source_span": {"line_start": 1, "line_end": 1},
                "raw_text": "Posting failed.",
            }
        ]
    ).model_dump(mode="json")


def test_agent2_accepts_only_structured_extraction_and_taxonomy():
    instance = adapter()
    payload = {
        "binding": binding(),
        "extracted": extraction(),
        "taxonomy": [
            {
                "category_id": "master_data",
                "label": "Master-data failure",
                "definition": "A record may be unavailable.",
                "pilot_active": True,
            }
        ],
    }
    instructions, version = instance._error_analysis_request("agent2", payload, ErrorAnalysisDraft)
    assert version == "error-analysis-v1"
    assert "only Agent 1's structured" in instructions
    assert "raw original log, case history or SAP data" in instructions.replace("\n", " ")


@pytest.mark.parametrize("forbidden", ["sources", "history", "route"])
def test_agent2_rejects_originals_history_and_route_before_any_model_call(forbidden: str):
    payload = {
        "binding": binding(),
        "extracted": extraction(),
        "taxonomy": [],
        forbidden: {"untrusted": "data"},
    }
    with pytest.raises(RuntimeError, match="stage boundary|structured extraction"):
        adapter()._error_analysis_request("agent2", payload, ErrorAnalysisDraft)


def test_other_stages_keep_their_distinct_output_contracts():
    instance = adapter()
    with pytest.raises(RuntimeError, match="Output contract"):
        instance._error_analysis_request(
            "agent1", {"binding": binding(), "sources": []}, CaseContent
        )
    with pytest.raises(RuntimeError, match="Output contract"):
        instance._error_analysis_request(
            "agent3",
            {
                "binding": binding(),
                "sources": [],
                "extracted": extraction(),
                "analysis": {},
                "history": {},
            },
            ExtractedLog,
        )
