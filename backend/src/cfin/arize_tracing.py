"""Automatic OpenInference Agents spans, optionally exported to Arize AX over OTLP.

The instrumentor creates every span. This module supplies configuration, scope
and an export buffer; it never creates a trace, span, session or model event.
"""

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from threading import Lock, RLock
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import SecretStr

_INSTRUMENTATION_LOCK = RLock()
_IDS = ("workspace_id", "run_id", "case_id", "attempt_id")
_EXTRA = ("stage", "model", "prompt_version", "evaluation_only", "offline_model")


@dataclass(frozen=True)
class ArizeTraceConfig:
    enabled: bool = False
    api_key: SecretStr = field(default_factory=lambda: SecretStr(""), repr=False)
    space_id: str = ""
    project_name: str = "cfin-document-error-analysis"
    otlp_endpoint: str = "https://otlp.arize.com/v1/traces"

    def configuration_error(self) -> str | None:
        if not self.enabled:
            return "disabled"
        if not self.api_key.get_secret_value().strip() or not self.space_id.strip():
            return "unconfigured"
        if (
            self.space_id != self.space_id.strip()
            or len(self.space_id) > 256
            or any(ord(char) < 33 or ord(char) > 126 for char in self.space_id)
            or not self.project_name.strip()
            or len(self.project_name) > 128
            or any(ord(char) < 32 for char in self.project_name)
        ):
            return "invalid_configuration"
        try:
            endpoint = urlsplit(self.otlp_endpoint)
            if (
                endpoint.scheme != "https"
                or not endpoint.hostname
                or endpoint.username is not None
                or endpoint.password is not None
                or endpoint.path != "/v1/traces"
                or endpoint.query
                or endpoint.fragment
            ):
                return "invalid_configuration"
        except ValueError:
            return "invalid_configuration"
        return None


def arize_config(settings: Any) -> ArizeTraceConfig:
    if isinstance(settings, ArizeTraceConfig):
        return settings
    return ArizeTraceConfig(
        enabled=settings.arize_enabled,
        api_key=settings.arize_api_key,
        space_id=settings.arize_space_id,
        project_name=settings.arize_project_name,
        otlp_endpoint=settings.arize_otlp_endpoint,
    )


def _metadata(values: Mapping[str, Any]) -> dict[str, str]:
    result = {}
    keys = ("workspace_id", "run_id", "snapshot_id") if values.get("stage") == "agent4" else _IDS
    for key in keys:
        if type(values[key]) is not str:
            raise ValueError("Invalid correlation identifier")
        result[key] = str(UUID(values[key]))
    for key in _EXTRA:
        if key in values and type(values[key]) in (str, int, bool):
            result[key] = (
                str(values[key]).lower() if type(values[key]) is bool else str(values[key])
            )
    return result


@dataclass(frozen=True)
class ArizeTraceResult:
    status: str
    retryable: bool = False
    trace_ids: tuple[str, ...] = ()
    span_count: int = 0
    readback_verified: bool = False
    error_code: str | None = None


class _Buffer:
    """Ordinary OTel SpanProcessor; retains only ended automatic SDK spans."""

    def __init__(self, owner):
        self.owner = owner
        self.spans = []
        self.lock = Lock()

    def on_start(self, span, parent_context=None):
        pass

    def _on_ending(self, span):
        # Required by OTel 1.45 before on_end receives the immutable span.
        pass

    def on_end(self, span):
        try:
            metadata = json.loads((span.attributes or {}).get("metadata", "{}"))
            if not self.owner._bound or any(
                metadata.get(key) != self.owner.trace_metadata[key]
                for key in getattr(self.owner, "correlation_keys", _IDS)
            ):
                self.owner._capture_error = "automatic_span_scope_mismatch"
                return
            with self.lock:
                if len(self.spans) >= 1000:
                    self.owner._capture_error = "automatic_span_limit"
                else:
                    self.spans.append(span)
        except Exception:
            self.owner._capture_error = "automatic_span_capture_error"

    def force_flush(self, timeout_millis=30000):
        # Provider/SDK lifecycle never sends an uncommitted workflow to a collector.
        return True

    def shutdown(self):
        with self.lock:
            self.spans.clear()


class _SafeCallbacks:
    """Scope native processor callbacks; failures never escape to Runner."""

    def __init__(self, owner, native):
        self.owner, self.native = owner, native
        self.active_trace_id = None
        self.context = None

    def _call(self, callback, value):
        if self.owner._capture_error or self.owner._closed:
            return
        try:
            getattr(self.native, callback)(value)
        except Exception:
            self.owner._capture_error = "automatic_callback_error"

    def on_trace_start(self, trace):
        try:
            if not self.owner._bound or self.active_trace_id is not None:
                self.owner._capture_error = "automatic_trace_scope_unbound_or_overlapping"
                return
            metadata = _metadata(trace.metadata or {})
            if any(
                metadata[key] != self.owner.trace_metadata[key]
                for key in self.owner.correlation_keys
            ):
                self.owner._capture_error = "automatic_trace_scope_mismatch"
                return
            from openinference.instrumentation import using_attributes

            self.active_trace_id = trace.trace_id
            self.context = using_attributes(
                session_id=metadata.get("case_id", metadata.get("snapshot_id")),
                metadata={
                    **metadata,
                    "openai_trace_id": trace.trace_id,
                    "tracing_mode": "openinference_auto",
                    "human_approval": "not_asserted_by_telemetry",
                },
            )
            self.context.__enter__()
            self._call("on_trace_start", trace)
        except Exception:
            self.owner._capture_error = "automatic_trace_scope_invalid"

    def on_trace_end(self, trace):
        try:
            if self.active_trace_id != trace.trace_id:
                self.owner._capture_error = "automatic_trace_lifecycle_mismatch"
            else:
                self._call("on_trace_end", trace)
        finally:
            self.close()

    def on_span_start(self, span):
        self._call("on_span_start", span)

    def on_span_end(self, span):
        self._call("on_span_end", span)

    def force_flush(self):
        pass

    def shutdown(self, timeout=None):
        pass

    def close(self):
        if self.context is not None:
            context, self.context = self.context, None
            try:
                context.__exit__(None, None, None)
            except Exception:
                self.owner._capture_error = "automatic_scope_cleanup_error"
        self.active_trace_id = None


class _DiscardExporterLogs(logging.Filter):
    def filter(self, record):
        # OTel can include a remote error body. Public diagnostics are fixed codes.
        return False


class AutoArizeTracing:
    """Set up before claim, bind actual IDs once, buffer until business commit.

    offline=True is an explicit diagnostic mode: native spans are collected but
    no authenticated exporter is constructed and no collector request is made.
    """

    def __init__(self, settings, metadata=None, *, offline=False):
        self.config = arize_config(settings)
        self.offline = offline
        self.trace_metadata = {}
        self.correlation_keys = _IDS
        self.enabled = False
        self.result = ArizeTraceResult("not_started")
        self._input_metadata = metadata
        self._bound = self._closed = self._attempted = self._locked = False
        self._capture_error = None
        self._provider = self._instrumentor = self._callbacks = self._buffer = None
        self._exporter = self._multi = None
        self._original = None
        self._owned = ()
        self._captured = ()

    def __enter__(self):
        error = self.config.configuration_error()
        if not self.offline and error is not None:
            self.result = ArizeTraceResult(error)
            return self
        try:
            _INSTRUMENTATION_LOCK.acquire()
            self._locked = True
            from agents.tracing import get_trace_provider
            from agents.tracing.processors import default_processor
            from openinference.instrumentation.openai_agents import OpenAIAgentsInstrumentor
            from openinference.instrumentation.openai_agents._processor import (
                OpenInferenceTracingProcessor,
            )
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.sdk.trace import TracerProvider

            self._multi = get_trace_provider()._multi_processor
            if not isinstance(self._multi._processors, tuple):
                raise RuntimeError("Unsupported Agents trace provider")
            self._instrumentor = OpenAIAgentsInstrumentor()
            if self._instrumentor.is_instrumented_by_opentelemetry:
                self._instrumentor = None
                raise RuntimeError("Existing instrumentation is owned elsewhere")
            with self._multi._lock:
                self._original = self._multi._processors
            self._provider = TracerProvider(
                resource=Resource(
                    {"openinference.project.name": self.config.project_name, "service.name": "cfin"}
                ),
                shutdown_on_exit=False,
            )
            self._buffer = _Buffer(self)
            self._provider.add_span_processor(self._buffer)
            self._instrumentor.instrument(tracer_provider=self._provider, exclusive_processor=False)
            with self._multi._lock:
                self._owned = tuple(
                    item
                    for item in self._multi._processors
                    if isinstance(item, OpenInferenceTracingProcessor)
                    and item._tracer.span_processor is self._provider._active_span_processor
                )
                if len(self._owned) != 1:
                    raise RuntimeError("Automatic processor could not be verified")
                self._callbacks = _SafeCallbacks(self, self._owned[0])
                self._multi._processors = tuple(
                    item
                    for item in self._multi._processors
                    if item is not default_processor() and item not in self._owned
                ) + (self._callbacks,)
            if not self.offline:
                from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

                self._exporter = OTLPSpanExporter(
                    endpoint=self.config.otlp_endpoint,
                    headers={
                        "space_id": self.config.space_id,
                        "api_key": self.config.api_key.get_secret_value(),
                    },
                    timeout=10,
                )
            self.enabled = True
            self.result = ArizeTraceResult("ready_offline" if self.offline else "ready")
            if self._input_metadata is not None:
                self.bind_metadata(self._input_metadata)
        except ImportError:
            self.result = ArizeTraceResult("sdk_unavailable")
            self.close()
        except Exception:
            self.result = ArizeTraceResult("initialization_failed", True, error_code="setup_error")
            self.close()
        return self

    def bind_metadata(self, metadata) -> bool:
        if not self.enabled:
            return False
        try:
            if self._bound or self._closed or self._attempted:
                raise ValueError("Metadata was already bound")
            self.trace_metadata = _metadata(metadata)
            self.correlation_keys = (
                ("workspace_id", "run_id", "snapshot_id")
                if metadata.get("stage") == "agent4"
                else _IDS
            )
            self._bound = True
            return True
        except (KeyError, TypeError, ValueError):
            self.enabled = False
            self._capture_error = "automatic_metadata_invalid"
            self.result = ArizeTraceResult("invalid_metadata")
            return False

    @property
    def captured_spans(self):
        if self._buffer is not None and not self._closed:
            with self._buffer.lock:
                return tuple(self._buffer.spans)
        return self._captured

    def flush(self, *, business_committed=False, run_state=None):
        if self._attempted or not self.enabled or self._closed:
            return self.result
        if self._capture_error:
            self.result = ArizeTraceResult("capture_failed", error_code=self._capture_error)
            return self.result
        if not business_committed:
            self.result = ArizeTraceResult("not_committed")
            return self.result
        spans = self.captured_spans
        self._captured = spans
        ids = tuple(sorted({f"{span.context.trace_id:032x}" for span in spans}))
        if not spans or self._callbacks.active_trace_id is not None:
            self.result = ArizeTraceResult("no_complete_spans", error_code="capture_incomplete")
            return self.result
        self._attempted = True
        if self.offline:
            self.result = ArizeTraceResult("captured_offline", trace_ids=ids, span_count=len(spans))
            return self.result
        logger = logging.getLogger("opentelemetry.exporter.otlp.proto.http.trace_exporter")
        redaction = _DiscardExporterLogs()
        logger.addFilter(redaction)
        try:
            from opentelemetry.sdk.trace.export import SpanExportResult

            accepted = self._exporter.export(spans) == SpanExportResult.SUCCESS
            self.result = ArizeTraceResult(
                "export_acknowledged" if accepted else "export_failed",
                not accepted,
                ids,
                len(spans),
                False,  # HTTP acknowledgement is not independent server readback.
                None if accepted else "otlp_export_failed",
            )
        except Exception:
            self.result = ArizeTraceResult(
                "export_failed", True, ids, len(spans), False, "otlp_export_error"
            )
        finally:
            logger.removeFilter(redaction)
        return self.result

    def __exit__(self, *_args):
        self.close()
        return False

    def close(self):
        if self._closed:
            return
        self._captured = self.captured_spans
        self._closed = True
        self.enabled = False
        try:
            if self._callbacks is not None:
                self._callbacks.close()
            if self._instrumentor is not None:
                self._instrumentor.uninstrument()
            if self._multi is not None and self._original is not None:
                with self._multi._lock:
                    remaining = tuple(
                        item
                        for item in self._multi._processors
                        if item is not self._callbacks and item not in self._owned
                    )
                    self._multi._processors = self._original + tuple(
                        item for item in remaining if item not in self._original
                    )
            if self._provider is not None:
                self._provider.shutdown()  # buffer shutdown has no exporter
            if self._exporter is not None:
                self._exporter.shutdown()
        except Exception:
            self.result = ArizeTraceResult("cleanup_failed", error_code="cleanup_error")
        finally:
            if self._locked:
                self._locked = False
                _INSTRUMENTATION_LOCK.release()


def span_snapshot(span) -> dict:
    """Actual automatic OTel record for explicit diagnostics, without auth headers."""
    return {
        "trace_id": f"{span.context.trace_id:032x}",
        "span_id": f"{span.context.span_id:016x}",
        "parent_span_id": f"{span.parent.span_id:016x}" if span.parent else None,
        "name": span.name,
        "start_time": span.start_time,
        "end_time": span.end_time,
        "attributes": dict(span.attributes or {}),
        "resource_attributes": dict(span.resource.attributes),
        "status_code": span.status.status_code.name,
    }
