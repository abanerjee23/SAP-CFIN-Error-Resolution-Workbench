import asyncio
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from cfin.config import Settings
from cfin.demo_worker import process_demo_once


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
