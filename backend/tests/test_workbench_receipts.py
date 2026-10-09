"""Verify API retries reach SQL's receipt-before-version guard."""
import asyncio
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from cfin.operations import ActionRequest, Operations


@pytest.mark.parametrize('conflict', [False, True])
def test_stale_error_analysis_action_uses_database_receipt_guard(conflict):
    workspace, case_id, actor = uuid4(), uuid4(), uuid4()
    user = AsyncMock()
    user.rows.return_value = [{
        'id': str(case_id), 'workspace_id': str(workspace), 'version': 4,
        'workflow_version': 'error-analysis-v1', 'work_cycle': 1,
    }]
    if conflict:
        user.rpc.side_effect = HTTPException(409, 'Current canonical case version required')
    else:
        user.rpc.return_value = {'saved': True, 'case': {'version': 3}}
    body = ActionRequest(
        workspace_id=workspace, expected_version=2, acting_role='process_owner',
        action='comment', request_key='stable-receipt', payload={'note': 'Saved comment'},
    )
    operation = Operations(user, AsyncMock())
    if conflict:
        with pytest.raises(HTTPException) as error:
            asyncio.run(operation.action('token', actor, case_id, body))
        assert error.value.status_code == 409
    else:
        assert asyncio.run(operation.action('token', actor, case_id, body))['saved'] is True
    user.require_member.assert_awaited_once()
    user.rpc.assert_awaited_once()
    assert user.rpc.call_args.args[0] == 'cfin_error_workbench_action'
    assert user.rpc.call_args.args[2]['expected_version'] == 2
    assert user.rpc.call_args.args[2]['request_key'] == 'stable-receipt'
