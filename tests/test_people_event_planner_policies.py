"""Smoke tests for people / event_planner / schedule_policies tools."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastmcp.exceptions import ToolError

from reclaim_mcp.exceptions import ReclaimError
from reclaim_mcp.tools import event_planner, people, schedule_policies


@pytest.fixture
def mock_client() -> MagicMock:
    c = MagicMock()
    c.get = AsyncMock()
    c.post = AsyncMock()
    c.put = AsyncMock()
    c.delete = AsyncMock()
    return c


# ---- people --------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_people(mock_client: MagicMock) -> None:
    mock_client.get.return_value = [{"id": 1, "name": "Alice"}]
    with patch.object(people, "_get_client", return_value=mock_client):
        result = await people.list_people()
    assert result == [{"id": 1, "name": "Alice"}]
    mock_client.get.assert_called_once_with("/api/people")


@pytest.mark.asyncio
async def test_sync_people(mock_client: MagicMock) -> None:
    mock_client.post.return_value = {"synced": 4}
    with patch.object(people, "_get_client", return_value=mock_client):
        result = await people.sync_people()
    assert result == {"synced": 4}
    mock_client.post.assert_called_once_with("/api/people/sync", data={})


@pytest.mark.asyncio
async def test_list_people_subscriptions(mock_client: MagicMock) -> None:
    mock_client.get.return_value = []
    with patch.object(people, "_get_client", return_value=mock_client):
        await people.list_people_subscriptions()
    mock_client.get.assert_called_once_with("/api/people/subscriptions")


# ---- event_planner -------------------------------------------------------


@pytest.mark.asyncio
async def test_pin_event(mock_client: MagicMock) -> None:
    mock_client.post.return_value = {"pinned": True}
    with patch.object(event_planner, "_get_client", return_value=mock_client):
        await event_planner.pin_event(calendar_id=12, event_id="ev_77")
    mock_client.post.assert_called_once_with(
        "/api/planner/event/12/ev_77/pin", data={}
    )


@pytest.mark.asyncio
async def test_unpin_event(mock_client: MagicMock) -> None:
    mock_client.post.return_value = {}
    with patch.object(event_planner, "_get_client", return_value=mock_client):
        await event_planner.unpin_event(calendar_id=12, event_id="ev_77")
    mock_client.post.assert_called_once_with(
        "/api/planner/event/12/ev_77/unpin", data={}
    )


@pytest.mark.asyncio
async def test_categorize_event(mock_client: MagicMock) -> None:
    mock_client.post.return_value = {}
    with patch.object(event_planner, "_get_client", return_value=mock_client):
        await event_planner.categorize_event(
            calendar_id=12, event_id="ev_77", category="WORK"
        )
    mock_client.post.assert_called_once_with(
        "/api/planner/event/category/12/ev_77", data={"category": "WORK"}
    )


@pytest.mark.asyncio
async def test_bulk_reschedule_tasks(mock_client: MagicMock) -> None:
    mock_client.post.return_value = {"rescheduled": 3}
    with patch.object(event_planner, "_get_client", return_value=mock_client):
        result = await event_planner.bulk_reschedule_tasks(
            task_ids=[1, 2, 3], after="2026-05-15T09:00:00Z"
        )
    assert result == {"rescheduled": 3}
    mock_client.post.assert_called_once_with(
        "/api/planner/task/reschedule/bulk",
        data={"taskIds": [1, 2, 3], "after": "2026-05-15T09:00:00Z"},
    )


@pytest.mark.asyncio
async def test_bulk_reschedule_empty_rejected() -> None:
    with pytest.raises(ToolError, match="cannot be empty"):
        await event_planner.bulk_reschedule_tasks(task_ids=[])


# ---- schedule_policies ---------------------------------------------------


@pytest.mark.asyncio
async def test_list_schedule_policies(mock_client: MagicMock) -> None:
    mock_client.get.return_value = []
    with patch.object(schedule_policies, "_get_client", return_value=mock_client):
        await schedule_policies.list_schedule_policies()
    mock_client.get.assert_called_once_with("/api/schedule-policy")


@pytest.mark.asyncio
async def test_get_schedule_policy(mock_client: MagicMock) -> None:
    mock_client.get.return_value = {"id": "task-default"}
    with patch.object(schedule_policies, "_get_client", return_value=mock_client):
        await schedule_policies.get_schedule_policy("task-default")
    mock_client.get.assert_called_once_with("/api/schedule-policy/task-default")


@pytest.mark.asyncio
async def test_update_schedule_policy(mock_client: MagicMock) -> None:
    mock_client.put.return_value = {"updated": True}
    body = {"dayHours": {"MONDAY": {"startTime": "09:00", "endTime": "17:00"}}}
    with patch.object(schedule_policies, "_get_client", return_value=mock_client):
        await schedule_policies.update_schedule_policy("p1", body=body)
    mock_client.put.assert_called_once_with("/api/schedule-policy/p1", data=body)


@pytest.mark.asyncio
async def test_update_schedule_policy_wraps_error(mock_client: MagicMock) -> None:
    mock_client.put.side_effect = ReclaimError("boom")
    with patch.object(schedule_policies, "_get_client", return_value=mock_client):
        with pytest.raises(ToolError, match="Error updating schedule policy"):
            await schedule_policies.update_schedule_policy("p1", body={"a": 1})
