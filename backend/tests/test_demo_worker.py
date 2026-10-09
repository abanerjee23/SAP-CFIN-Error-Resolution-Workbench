import asyncio
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from cfin.config import Settings
from cfin.demo_worker import process_demo_once, run


@pytest.mark.parametrize('synthetic', [False, True])
def test_demo_worker_only_dispatches_a_verified_target_in_its_workspace(monkeypatch, synthetic):
    workspace, run = str(uuid4()), str(uuid4())
    settings = Settings(_env_file=None, local_demo_enabled=True, demo_workspace_id=workspace,
                        paid_models_enabled=True, openai_api_key='test-only')
    cloud = AsyncMock()
    cloud.rows.side_effect = [
        [{'id': workspace, 'synthetic': synthetic}],
        [{'workspace_id': workspace, 'run_id': run}],
        [{'id': run, 'workspace_id': workspace, 'workflow_version': 'error-analysis-v1'}],
    ]
    dispatch = AsyncMock(return_value={'claimed': True})
    monkeypatch.setattr('cfin.demo_worker.process_one', dispatch)
    if not synthetic:
        with pytest.raises(RuntimeError, match='synthetic'):
            asyncio.run(process_demo_once(cloud, settings, 'test-worker'))
        dispatch.assert_not_awaited()
    else:
        assert asyncio.run(process_demo_once(cloud, settings, 'test-worker'))['claimed']
        dispatch.assert_awaited_once_with(cloud, settings, 'test-worker', target_run_id=run)
        for call in cloud.rows.call_args_list[1:]:
            assert call.args[1]['workspace_id'] == 'eq.' + workspace


def test_demo_worker_rejects_a_queue_response_outside_its_workspace(monkeypatch):
    workspace = str(uuid4())
    settings = Settings(_env_file=None, local_demo_enabled=True, demo_workspace_id=workspace,
                        paid_models_enabled=True, openai_api_key='test-only')
    cloud = AsyncMock()
    cloud.rows.side_effect = [[{'id': workspace, 'synthetic': True}],
                              [{'workspace_id': str(uuid4()), 'run_id': str(uuid4())}]]
    dispatch = AsyncMock()
    monkeypatch.setattr('cfin.demo_worker.process_one', dispatch)
    with pytest.raises(RuntimeError, match='outside'):
        asyncio.run(process_demo_once(cloud, settings, 'test-worker'))
    dispatch.assert_not_awaited()


def test_continuous_worker_recovers_from_transient_service_failure(monkeypatch):
    dispatch = AsyncMock(side_effect=[HTTPException(503, 'Temporary failure'),
                                     {'claimed': False}, asyncio.CancelledError()])
    pause = AsyncMock()
    monkeypatch.setattr('cfin.demo_worker.process_demo_once', dispatch)
    monkeypatch.setattr('cfin.demo_worker.asyncio.sleep', pause)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(run(False))
    assert [call.args[0] for call in pause.call_args_list] == [2, 3]
    assert dispatch.await_count == 3


def test_worker_does_not_retry_denied_access(monkeypatch):
    dispatch = AsyncMock(side_effect=HTTPException(403, 'Denied'))
    pause = AsyncMock()
    monkeypatch.setattr('cfin.demo_worker.process_demo_once', dispatch)
    monkeypatch.setattr('cfin.demo_worker.asyncio.sleep', pause)
    with pytest.raises(HTTPException):
        asyncio.run(run(False))
    pause.assert_not_awaited()
