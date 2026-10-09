"""Configuration-only readiness report. Never prints credentials or enables calls."""

import json

from cfin.config import Settings
from cfin.fixture_loader import load_md01
from cfin.model_adapter import PRICES


def report(settings: Settings) -> dict:
    checks = {
        "supabase_url": bool(settings.supabase_url),
        "supabase_publishable_key": bool(settings.supabase_publishable_key.get_secret_value()),
        "server_supabase_secret_key": bool(settings.supabase_secret_key.get_secret_value()),
        "openai_api_key": bool(settings.openai_api_key.get_secret_value()),
        "models_have_verified_price_adapter": all(
            x in PRICES
            for x in (settings.model_agent_1, settings.model_agent_2, settings.model_agent_3)
        ),
        "paid_models_enabled": settings.paid_models_enabled,
        "log_only_enabled": settings.log_only_enabled,
    }
    load_md01()
    return {
        "checks": checks,
        "missing_configuration": [k for k, v in checks.items() if not v],
        "fixture_valid": True,
        "baseline_models": {
            "extraction": settings.model_agent_1,
            "error_analysis": settings.model_agent_2,
            "summary": settings.model_agent_3,
        },
        "workflow_versions": ["log-only-v1", "error-analysis-v1"],
        "legacy_workflow_supported": True,
        "reasoning_effort": settings.model_reasoning_effort,
        "arize": {
            "configured": settings.arize_configured,
            "connection_verified": False,
            "purpose": "evaluations_and_observability",
            "automatic_instrumentation": True,
            "missing_configuration": [
                name
                for name, present in {
                    "ARIZE_ENABLED": settings.arize_enabled,
                    "ARIZE_API_KEY": bool(settings.arize_api_key.get_secret_value().strip()),
                    "ARIZE_SPACE_ID": bool(settings.arize_space_id.strip()),
                    "ARIZE_PROJECT_NAME": bool(settings.arize_project_name.strip()),
                }.items()
                if not present
            ],
        },
        "cloud_verified": False,
        "live_end_to_end_verified": False,
        "model_monthly_cap_usd": str(settings.model_monthly_budget_usd),
        "model_run_cap_usd": str(settings.model_run_budget_usd),
    }


def main() -> None:
    print(json.dumps(report(Settings()), indent=2))


if __name__ == "__main__":
    main()
