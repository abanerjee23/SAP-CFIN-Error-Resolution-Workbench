"""Real automatic instrumentor/Responses SDK with only local HTTP and exporter fakes."""

import asyncio
import builtins
import json
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import SecretStr

from cfin.arize_smoke import check
from cfin.arize_tracing import ArizeTraceConfig, AutoArizeTracing, _Buffer, _SafeCallbacks


def metadata():
    return {key: str(uuid4()) for key in ("workspace_id", "run_id", "case_id", "attempt_id")}


def configured():
    return ArizeTraceConfig(
        enabled=True, api_key=SecretStr("offline-test-key"), space_id="U3BhY2U6dGVzdA=="
    )


@pytest.fixture
def exporter(monkeypatch):
    from opentelemetry.exporter.otlp.proto.http import trace_exporter
    from opentelemetry.sdk.trace.export import SpanExportResult

    class FakeExporter:
        instances = []
        response = SpanExportResult.SUCCESS
        raises = False
        verify_before_export = None

        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.calls = []
            self.closed = False
            self.instances.append(self)

        def export(self, spans):
            if self.verify_before_export:
                self.verify_before_export()
            self.calls.append(tuple(spans))
            if self.raises:
                raise RuntimeError("Remote response may contain a secret; never report it")
            return self.response

        def shutdown(self):
            self.closed = True

    monkeypatch.setattr(trace_exporter, "OTLPSpanExporter", FakeExporter)
    return FakeExporter


@pytest.mark.parametrize("config", [ArizeTraceConfig(), ArizeTraceConfig(enabled=True)])
def test_unconfigured_does_not_import_optional_sdk_or_change_processors(monkeypatch, config):
    original = builtins.__import__

    def guarded(name, *args, **kwargs):
        if name.startswith(("openinference", "opentelemetry")):
            pytest.fail("Unconfigured telemetry must not initialize its optional SDK")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)
    with AutoArizeTracing(config) as tracing:
        assert not tracing.enabled
        assert not tracing.bind_metadata(metadata())
        assert tracing.flush(business_committed=True).status in {"disabled", "unconfigured"}


@pytest.mark.parametrize(
    "changes",
    [
        {"space_id": " space"},
        {"space_id": "bad\nheader"},
        {"project_name": ""},
        {"otlp_endpoint": "http://otlp.arize.com/v1/traces"},
        {"otlp_endpoint": "https://user:key@otlp.arize.com/v1/traces"},
        {"otlp_endpoint": "https://otlp.arize.com/v1/traces?key=secret"},
    ],
)
def test_invalid_destination_fails_closed(changes):
    with AutoArizeTracing(replace(configured(), **changes)) as tracing:
        assert not tracing.enabled
        assert tracing.result.status == "invalid_configuration"


def test_native_setup_before_claim_binds_only_once_and_never_sends(exporter):
    with AutoArizeTracing(configured()) as tracing:
        assert tracing.enabled and not tracing._bound
        assert not tracing.captured_spans
        actual = metadata()
        assert tracing.bind_metadata(actual)
        assert tracing.trace_metadata == actual
        tracing._provider.force_flush()
        tracing._callbacks.force_flush()
        tracing._callbacks.shutdown()
        assert exporter.instances[0].calls == []
        assert not tracing.bind_metadata(actual)
        assert not tracing.enabled
    assert exporter.instances[0].closed and not exporter.instances[0].calls


def test_unbound_or_wrong_scope_native_callback_is_rejected():
    with AutoArizeTracing(ArizeTraceConfig(enabled=True), offline=True) as tracing:
        tracing._callbacks.on_trace_start(SimpleNamespace(trace_id="fake", metadata=metadata()))
        assert tracing._capture_error == "automatic_trace_scope_unbound_or_overlapping"
        assert tracing.flush(business_committed=True).status == "capture_failed"
        assert not tracing.captured_spans


def test_native_callback_exception_is_sanitized():
    class Broken:
        def on_span_end(self, _span):
            raise RuntimeError("credential-bearing remote message")

    owner = SimpleNamespace(_capture_error=None, _closed=False)
    callbacks = _SafeCallbacks(owner, Broken())
    callbacks.on_span_end(object())
    assert owner._capture_error == "automatic_callback_error"


def test_span_capture_rejects_foreign_scope_and_no_lifecycle_upload():
    owner = SimpleNamespace(_bound=True, trace_metadata=metadata(), _capture_error=None)
    buffer = _Buffer(owner)
    buffer._on_ending(object())  # OTel 1.45's required immutable-span lifecycle hook
    buffer.on_end(SimpleNamespace(attributes={"metadata": json.dumps(metadata())}))
    assert owner._capture_error == "automatic_span_scope_mismatch"
    assert not buffer.spans
    assert buffer.force_flush()
    buffer.shutdown()


def test_native_processor_cleanup_preserves_other_processors_and_empty_original():
    from agents.tracing import add_trace_processor, get_trace_provider
    from agents.tracing.processors import default_processor

    multi = get_trace_provider()._multi_processor
    original = multi._processors
    late = object()
    try:
        for starting in (original, ()):
            with multi._lock:
                multi._processors = starting
            with AutoArizeTracing(
                ArizeTraceConfig(enabled=True), metadata(), offline=True
            ) as tracing:
                assert tracing.enabled
                assert default_processor() not in multi._processors
                add_trace_processor(late)
            assert all(item in multi._processors for item in starting)
            assert late in multi._processors
            assert tracing._callbacks not in multi._processors
            assert not any(item in multi._processors for item in tracing._owned)
    finally:
        with multi._lock:
            multi._processors = original


def test_processor_registered_during_native_setup_is_preserved(monkeypatch):
    from agents.tracing import add_trace_processor, get_trace_provider
    from openinference.instrumentation.openai_agents import OpenAIAgentsInstrumentor
    from openinference.instrumentation.openai_agents._processor import OpenInferenceTracingProcessor
    from opentelemetry.sdk.trace import TracerProvider

    multi = get_trace_provider()._multi_processor
    original = multi._processors
    unrelated_provider = TracerProvider(shutdown_on_exit=False)
    registered_during_setup = OpenInferenceTracingProcessor(unrelated_provider.get_tracer("other"))
    instrument = OpenAIAgentsInstrumentor.instrument

    def instrument_and_register(self, **kwargs):
        assert kwargs["exclusive_processor"] is False
        instrument(self, **kwargs)
        add_trace_processor(registered_during_setup)

    monkeypatch.setattr(OpenAIAgentsInstrumentor, "instrument", instrument_and_register)
    try:
        with AutoArizeTracing(ArizeTraceConfig(enabled=True), metadata(), offline=True) as tracing:
            assert tracing.enabled
            assert registered_during_setup in multi._processors
        assert registered_during_setup in multi._processors
        assert all(item in multi._processors for item in original)
    finally:
        with multi._lock:
            multi._processors = original
        unrelated_provider.shutdown()


def test_actual_runner_captures_responses_payload_hierarchy_usage_and_scope(tmp_path, exporter):
    output = tmp_path / "smoke.json"

    def saved_before_export():
        assert json.loads(output.read_text())["local_response_verified"]
        assert json.loads(output.with_name("smoke-captured.json").read_text())

    exporter.verify_before_export = staticmethod(saved_before_export)
    report = asyncio.run(check(output, upload=True, settings=configured()))
    assert report["provider_calls"] == 0 and report["mock_provider_calls"] == 1
    assert report["local_response_verified"] and report["automatic_llm_verified"]
    result = report["arize"]
    assert result["status"] == "export_acknowledged"
    assert result["readback_verified"] is False
    assert result["span_count"] == 5
    record = exporter.instances[0]
    assert record.closed and len(record.calls) == 1
    spans = record.calls[0]
    roots = [span for span in spans if span.parent is None]
    assert len(roots) == 1
    ids = {span.context.span_id for span in spans}
    assert all(span.parent is None or span.parent.span_id in ids for span in spans)
    assert len({span.context.trace_id for span in spans}) == 1
    llm = next(span for span in spans if span.attributes["openinference.span.kind"] == "LLM")
    assert llm.attributes["llm.model_name"] == "offline-automatic-tracing-smoke"
    assert "local fake" in llm.attributes["input.value"]
    assert json.loads(llm.attributes["output.value"])["usage"]["total_tokens"] == 12
    correlation = json.loads(roots[0].attributes["metadata"])
    assert correlation["evaluation_only"] == correlation["offline_model"] == "true"
    assert correlation["human_approval"] == "not_asserted_by_telemetry"
    for span in spans:
        assert (
            span.resource.attributes["openinference.project.name"] == "cfin-document-error-analysis"
        )
        assert json.loads(span.attributes["metadata"]) == correlation
        assert span.attributes["session.id"] == correlation["case_id"]
        assert span.end_time >= span.start_time > 0
    serialized = json.dumps(json.loads(output.with_name("smoke-captured.json").read_text()))
    assert "offline-test-key" not in serialized


@pytest.mark.parametrize("raises", [False, True])
def test_failed_otlp_keeps_actual_trace_ids_and_does_not_claim_persistence(
    tmp_path, exporter, raises
):
    from opentelemetry.sdk.trace.export import SpanExportResult

    exporter.response = SpanExportResult.FAILURE
    exporter.raises = raises
    report = asyncio.run(check(tmp_path / "failed.json", upload=True, settings=configured()))
    result = report["arize"]
    assert result["status"] == "export_failed" and result["retryable"]
    assert result["trace_ids"] and result["span_count"] == 5
    assert not result["readback_verified"]
    assert result["error_code"] in {"otlp_export_failed", "otlp_export_error"}
    assert len(exporter.instances[0].calls) == 1 and exporter.instances[0].closed
    assert "credential" not in json.dumps(report)


def test_no_export_before_business_commit_or_from_sdk_shutdown(tmp_path, exporter, monkeypatch):
    original = AutoArizeTracing.flush
    captured = []

    def uncommitted(self, **_kwargs):
        assert self.captured_spans
        assert original(self, business_committed=False).status == "not_committed"
        self._provider.force_flush()
        self._callbacks.shutdown()
        captured.append(self)
        assert not exporter.instances[0].calls
        return self.result

    monkeypatch.setattr(AutoArizeTracing, "flush", uncommitted)
    report = asyncio.run(check(tmp_path / "uncommitted.json", upload=True, settings=configured()))
    assert report["arize"]["status"] == "not_committed"
    assert not exporter.instances[0].calls and exporter.instances[0].closed
    assert len(captured[0].captured_spans) == 5  # retain original records for explicit diagnostics
