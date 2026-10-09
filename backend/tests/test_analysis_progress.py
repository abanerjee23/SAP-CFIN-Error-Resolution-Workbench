from cfin.analysis_progress import analysis_progress


def test_pending_case_is_never_a_diagnosis_and_uses_current_run_only():
    case = {"requested_run_id": "new", "analysis_status": "pending"}
    result = analysis_progress(case, [{"id": "old", "state": "succeeded"}], [
        {"run_id": "old", "stage": "agent_3", "state": "succeeded", "invocation": 1},
    ])
    assert result["status"] == "queued"
    assert result["stage"] is None and result["attempt"] == 1


def test_retry_and_success_come_from_saved_state():
    case = {"requested_run_id": "new", "analysis_status": "running"}
    calls = [
        {"run_id": "new", "stage": "agent_1", "state": "failed", "invocation": 0,
         "created_at": "2026-10-09T10:00:00Z"},
        {"run_id": "new", "stage": "agent_1", "state": "in_flight", "invocation": 1,
         "created_at": "2026-10-09T10:01:00Z"},
    ]
    result = analysis_progress(case, [], calls)
    assert result["status"] == "running" and result["retrying"] is True
    assert result["attempt"] == 2 and result["completed_stages"] == []
    case.update(analysis_status="available", published_run_id="new")
    assert analysis_progress(case, [], calls)["status"] == "ready"


def test_failed_run_is_attention_not_unclassified_or_endless_loading():
    case = {"requested_run_id": "new", "analysis_status": "pending"}
    result = analysis_progress(case, [{"id": "new", "state": "failed"}], [])
    assert result["status"] == "failed" and result["retrying"] is False
