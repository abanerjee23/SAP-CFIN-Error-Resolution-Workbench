import asyncio
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from cfin.config import Settings
from cfin.demo_worker import process_demo_once, run, run_worker, run_workers


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


def test_worker_moves_past_a_job_already_claimed_by_other_process(monkeypatch):
    workspace, first_run, second_run = (str(uuid4()) for _ in range(3))
    settings = Settings(_env_file=None, local_demo_enabled=True, demo_workspace_id=workspace,
                        paid_models_enabled=True, openai_api_key='test-only')
    cloud = AsyncMock()
    cloud.rows.side_effect = [
        [{'id': workspace, 'synthetic': True}],
        [{'workspace_id': workspace, 'run_id': first_run},
         {'workspace_id': workspace, 'run_id': second_run}],
        [{'id': first_run, 'workspace_id': workspace, 'workflow_version': 'error-analysis-v1'}],
        [{'id': second_run, 'workspace_id': workspace, 'workflow_version': 'error-analysis-v1'}],
    ]
    dispatch = AsyncMock(side_effect=[{'claimed': False}, {'claimed': True, 'run_id': second_run}])
    monkeypatch.setattr('cfin.demo_worker.process_one', dispatch)
    assert asyncio.run(process_demo_once(cloud, settings, 'second-worker'))['run_id'] == second_run
    assert [call.kwargs['target_run_id'] for call in dispatch.call_args_list] == [
        first_run, second_run,
    ]


def test_two_process_supervisor_stops_remaining_worker_if_peer_exits(monkeypatch):
    first, second = Mock(pid=11), Mock(pid=12)
    first.is_alive.side_effect = [False, False, False]
    second.is_alive.side_effect = [True, False]
    context = Mock()
    context.Process.side_effect = [first, second]
    spawn = Mock(return_value=context)
    monkeypatch.setattr('cfin.demo_worker.multiprocessing.get_context', spawn)
    monkeypatch.setattr('cfin.demo_worker.signal.signal', Mock())
    with pytest.raises(RuntimeError, match='worker exited'):
        run_workers(2)
    spawn.assert_called_once_with('spawn')
    assert context.Process.call_count == 2
    assert all(call.kwargs['target'] is run_worker for call in context.Process.call_args_list)
    first.start.assert_called_once()
    second.start.assert_called_once()
    second.terminate.assert_called_once()
    first.join.assert_called_once()
    second.join.assert_called_once()


@pytest.mark.parametrize('count', [0, 3])
def test_worker_pool_has_a_hard_two_process_limit(count):
    with pytest.raises(ValueError, match='one or two'):
        run_workers(count)
