"""CLI diagnostic defaults to offline collection and creates no operational record."""

import asyncio
import json

from cfin import arize_smoke


def test_default_smoke_does_not_load_settings_or_construct_cloud_exporter(tmp_path, monkeypatch):
    from opentelemetry.exporter.otlp.proto.http import trace_exporter

    from cfin import config

    def forbidden(*_args, **_kwargs):
        raise AssertionError("Default smoke may not read environment or initialize cloud export")

    monkeypatch.setattr(config, "Settings", forbidden)
    monkeypatch.setattr(trace_exporter, "OTLPSpanExporter", forbidden)
    output = tmp_path / "offline.json"
    report = asyncio.run(arize_smoke.check(output))
    assert report["arize"]["status"] == "captured_offline"
    assert report["local_response_verified"] and report["automatic_llm_verified"]
    assert report["provider_calls"] == 0 and report["mock_provider_calls"] == 1
    assert not report["upload_requested"] and not report["operational_case_modified"]
    snapshots = json.loads(output.with_name("offline-captured.json").read_text())
    assert len(snapshots) == report["arize"]["span_count"] == 5
    assert len({record["trace_id"] for record in snapshots}) == 1
    assert json.loads(output.read_text())["arize"]["status"] == "captured_offline"
