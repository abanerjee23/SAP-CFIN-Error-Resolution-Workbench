import json

import pytest
from pydantic import ValidationError

from cfin.config import Settings
from cfin.readiness import report


def test_old_provider_environment_cannot_enable_arize_or_paid_models(monkeypatch):
    monkeypatch.setenv("GALILEO_ENABLED", "true")
    monkeypatch.setenv("GALILEO_API_KEY", "retired-test-key")
    settings = Settings(_env_file=None)
    assert not settings.arize_configured
    assert not settings.paid_models_enabled
    assert not hasattr(settings, "galileo_api_key")


def test_arize_readiness_is_config_only_and_does_not_expose_credentials():
    settings = Settings(
        _env_file=None,
        arize_enabled=True,
        arize_api_key="arize-test-secret",
        arize_space_id="test-space",
    )
    status = report(settings)
    assert status["arize"]["configured"]
    assert status["arize"]["connection_verified"] is False
    assert status["arize"]["automatic_instrumentation"] is True
    assert status["arize"]["missing_configuration"] == []
    assert "arize-test-secret" not in json.dumps(status)
    assert "arize-test-secret" not in repr(settings)
    assert "arize-test-secret" not in settings.model_dump_json()
    assert not settings.paid_models_enabled


def test_api_key_alone_does_not_enable_uploads_or_claim_readiness():
    settings = Settings(_env_file=None, arize_api_key="test-key", arize_enabled=True)
    status = report(settings)["arize"]
    assert not status["configured"]
    assert status["missing_configuration"] == ["ARIZE_SPACE_ID"]


@pytest.mark.parametrize("field", ["arize_api_url", "arize_otlp_endpoint"])
@pytest.mark.parametrize(
    "value",
    [
        "http://api.arize.com/v2",
        "https:///v2",
        "https://key@api.arize.com/v2",
        "https://api.arize.com/v2?api_key=secret",
        "https://api.arize.com/v2#secret",
    ],
)
def test_arize_rejects_insecure_or_credential_bearing_endpoints(field, value):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{field: value})
