"""Promptfoo deterministic fixture provider for Error Analysis policy checks.

It intentionally makes no model request. Model quality is assessed separately when
the paid provider and reviewed examples are enabled.
"""

import json


CASES = {
    "pilot-master-data": "master_data",
    "pilot-mapping": "mapping",
    "nonpilot-tax": "tax",
    "genuinely-ambiguous": "unclassified",
    "injection-text": "unclassified",
}


def call_api(prompt, options, context):
    case_id = str(prompt).strip()
    return {"output": json.dumps({"case_id": case_id, "category_id": CASES[case_id]})}
