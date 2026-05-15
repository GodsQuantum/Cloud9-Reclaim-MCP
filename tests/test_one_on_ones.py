"""Tests for one_on_ones tools."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastmcp.exceptions import ToolError

from reclaim_mcp.exceptions import ReclaimError
from reclaim_mcp.tools import one_on_ones


@pytest.fixture
def mock_client() -> MagicMock:
    client = MagicMock()
    client.get = AsyncMock()
    client.post = AsyncMock()
    client.patch = AsyncMock()
    client.delete = AsyncMock()
    return client


@pytest.mark.asyncio
async def test_list_one_on_ones_basic(mock_client: MagicMock) -> None:
    mock_client.get.return_value = [{"id": 1, "title": "Chris+Lara"}]
    with patch.object(one_on_ones, "_get_client", return_value=mock_client):
        result = await one_on_ones.list_one_on_ones()
    assert result == [{"id": 1, "title": "Chris+Lara"}]
    mock_client.get.assert_called_once_with("/api/oneOnOne", params=None)


@pytest.mark.asyncio
async def test_list_one_on_ones_with_instances(mock_client: MagicMock) -> None:
    mock_client.get.return_value = []
    with patch.object(one_on_ones, "_get_client", return_value=mock_client):
        await one_on_ones.list_one_on_ones(include_instances=True)
    mock_client.get.assert_called_once_with(
        "/api/oneOnOne", params={"instances": "true"}
    )


@pytest.mark.asyncio
async def test_create_one_on_one_strips_none(mock_client: MagicMock) -> None:
    mock_client.post.return_value = {"id": 7}
    with patch.object(one_on_ones, "_get_client", return_value=mock_client):
        result = await one_on_ones.create_one_on_one(
            title="Weekly w/ Lara",
            invitee_email="lara@example.com",
            duration_minutes=30,
        )
    assert result == {"id": 7}
    mock_client.post.assert_called_once_with(
        "/api/oneOnOne",
        data={
            "title": "Weekly w/ Lara",
            "inviteeEmail": "lara@example.com",
            "durationMinutes": 30,
            "recurrence": "WEEKLY",
        },
    )


@pytest.mark.asyncio
async def test_update_one_on_one_requires_a_field(mock_client: MagicMock) -> None:
    with patch.object(one_on_ones, "_get_client", return_value=mock_client):
        with pytest.raises(ToolError, match="No fields to update"):
            await one_on_ones.update_one_on_one(one_on_one_id=1)


@pytest.mark.asyncio
async def test_update_one_on_one_sends_only_provided(mock_client: MagicMock) -> None:
    mock_client.patch.return_value = {"id": 1, "title": "New"}
    with patch.object(one_on_ones, "_get_client", return_value=mock_client):
        await one_on_ones.update_one_on_one(one_on_one_id=1, title="New")
    mock_client.patch.assert_called_once_with(
        "/api/oneOnOne/1", data={"title": "New"}
    )


@pytest.mark.asyncio
async def test_skip_one_on_one_day(mock_client: MagicMock) -> None:
    mock_client.post.return_value = {"skipped": True}
    with patch.object(one_on_ones, "_get_client", return_value=mock_client):
        await one_on_ones.skip_one_on_one_day(one_on_one_id=5, event_id="ev_abc")
    mock_client.post.assert_called_once_with(
        "/api/planner/one-on-one/skip-day/5/ev_abc", data={}
    )


@pytest.mark.asyncio
async def test_reschedule_one_on_one_with_start(mock_client: MagicMock) -> None:
    mock_client.post.return_value = {}
    with patch.object(one_on_ones, "_get_client", return_value=mock_client):
        await one_on_ones.reschedule_one_on_one(
            one_on_one_id=5,
            event_id="ev_abc",
            new_start="2026-05-15T14:00:00Z",
        )
    mock_client.post.assert_called_once_with(
        "/api/planner/one-on-one/reschedule/5/ev_abc",
        data={"start": "2026-05-15T14:00:00Z"},
    )


@pytest.mark.asyncio
async def test_delete_one_on_one(mock_client: MagicMock) -> None:
    mock_client.delete.return_value = True
    with patch.object(one_on_ones, "_get_client", return_value=mock_client):
        result = await one_on_ones.delete_one_on_one(one_on_one_id=42)
    assert result is True
    mock_client.delete.assert_called_once_with("/api/oneOnOne/42")


@pytest.mark.asyncio
async def test_list_one_on_ones_error_wrapped(mock_client: MagicMock) -> None:
    mock_client.get.side_effect = ReclaimError("nope")
    with patch.object(one_on_ones, "_get_client", return_value=mock_client):
        with pytest.raises(ToolError, match="Error listing one-on-ones"):
            await one_on_ones.list_one_on_ones()
