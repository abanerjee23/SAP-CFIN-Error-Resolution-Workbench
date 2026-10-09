"""Promptfoo assertion for the deterministic policy-gate suite."""

import json


def get_assert(output, context):
    parsed = json.loads(output)
    expected = context["vars"]["expected_category"]
    actual = parsed.get("category_id")
    pilot = context["vars"].get("pilot") is True
    passed = actual == expected and (not pilot or actual != "unclassified")
    return {
        "pass": passed,
        "score": 1 if passed else 0,
        "reason": (
            "Policy category matched; pilot unclassified fallback is a failure."
            if passed
            else f"Expected {expected}; received {actual}."
        ),
    }
