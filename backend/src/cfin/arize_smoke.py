"""Exercise native Arize automatic tracing with a local Responses HTTP fake.

Default mode collects spans in memory only. --upload explicitly sends these
synthetic spans to the configured Arize OTLP collector, never a paid model.
"""

import argparse
import asyncio
import json
import time
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

import httpx
from agents import Agent, OpenAIResponsesModel, RunConfig, Runner
from openai import AsyncOpenAI

from cfin.arize_tracing import ArizeTraceConfig, AutoArizeTracing, span_snapshot


async def check(output: Path, *, upload=False, settings=None) -> dict:
    if settings is None:
        if upload:
            from cfin.config import Settings

            settings = Settings()
        else:
            settings = ArizeTraceConfig(enabled=True)
    mock_calls = []

    def fake_response(request):
        assert request.method == "POST" and request.url.path == "/v1/responses"
        mock_calls.append(True)
        return httpx.Response(
            200,
            json={
                "id": "resp_offline_arize_smoke",
                "object": "response",
                "created_at": int(time.time()),
                "status": "completed",
                "model": "offline-automatic-tracing-smoke",
                "output": [
                    {
                        "id": "msg_offline_smoke",
                        "type": "message",
                        "status": "completed",
                        "role": "assistant",
                        "content": [
                            {
                                "type": "output_text",
                                "text": "Automatic tracing smoke completed.",
                                "annotations": [],
                            }
                        ],
                    }
                ],
                "usage": {"input_tokens": 7, "output_tokens": 5, "total_tokens": 12},
            },
        )

    report = {
        "kind": "arize_automatic_tracing_integration_smoke",
        "provider_calls": 0,
        "synthetic_token_counts": True,
        "model_quality_evaluated": False,
        "operational_case_modified": False,
        "upload_requested": upload,
    }
    metadata = {
        **{key: str(uuid4()) for key in ("workspace_id", "run_id", "case_id", "attempt_id")},
        "evaluation_only": True,
        "offline_model": True,
    }
    with AutoArizeTracing(settings, metadata=metadata, offline=not upload) as tracing:
        if tracing.enabled:
            async with AsyncOpenAI(
                api_key="offline-fake-not-a-provider-key",
                max_retries=0,
                http_client=httpx.AsyncClient(transport=httpx.MockTransport(fake_response)),
            ) as client:
                result = await Runner.run(
                    Agent(
                        name="CFIN automatic tracing integration smoke",
                        instructions="Return the fixed synthetic diagnostic response.",
                        model=OpenAIResponsesModel("offline-automatic-tracing-smoke", client),
                    ),
                    "Exercise automatic tracing using a local fake; no real model request.",
                    max_turns=1,
                    run_config=RunConfig(
                        tracing_disabled=False,
                        trace_include_sensitive_data=True,
                        workflow_name="CFIN automatic tracing integration smoke",
                        trace_metadata=tracing.trace_metadata,
                    ),
                )
            snapshots = [span_snapshot(span) for span in tracing.captured_spans]
            llms = [
                record
                for record in snapshots
                if record["attributes"].get("openinference.span.kind") == "LLM"
            ]
            expected_usage = {
                "llm.token_count.prompt": 7,
                "llm.token_count.completion": 5,
                "llm.token_count.total": 12,
            }
            report.update(
                mock_provider_calls=len(mock_calls),
                local_response_verified=result.final_output == "Automatic tracing smoke completed.",
                automatic_llm_verified=len(llms) == 1
                and all(
                    llms[0]["attributes"].get(key) == value for key, value in expected_usage.items()
                ),
            )
            output.parent.mkdir(parents=True, exist_ok=True)
            captured_path = output.with_name(output.stem + "-captured.json")
            captured_path.write_text(json.dumps(snapshots, indent=2) + "\n")
            report["captured_path"] = str(captured_path.resolve())
            # Save the local diagnostic result and actual auto spans before export.
            output.write_text(json.dumps(report, indent=2) + "\n")
        report["arize"] = asdict(tracing.flush(business_committed=True, run_state="offline_smoke"))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--upload", action="store_true", help="Export synthetic spans to configured Arize"
    )
    args = parser.parse_args()
    try:
        report = asyncio.run(check(args.output, upload=args.upload))
    except Exception:
        report = {"status": "failed", "error": "Automatic tracing smoke could not complete"}
    print(json.dumps(report, indent=2))
    expected = "export_acknowledged" if args.upload else "captured_offline"
    return (
        0
        if report.get("arize", {}).get("status") == expected
        and report.get("automatic_llm_verified")
        and report.get("local_response_verified")
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
