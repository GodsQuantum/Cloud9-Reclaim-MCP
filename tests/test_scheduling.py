"""Tests for scheduling tools."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from reclaim_mcp.cache import invalidate_cache
from reclaim_mcp.tools import scheduling


@pytest.fixture(autouse=True)
def _clear_cache():
    invalidate_cache()


@pytest.fixture
def mock_client():
    client = MagicMock()
    client.get = AsyncMock()
    client.post = AsyncMock()
    return client


@pytest.fixture(autouse=True)
def _stub_tz():
    with patch("reclaim_mcp.tools.scheduling.get_user_tz", AsyncMock(return_value="America/Los_Angeles")):
        yield


class TestGetWorkingHours:
    @pytest.mark.asyncio
    async def test_hits_timeschemes(self, mock_client):
        mock_client.get.return_value = [{"name": "work"}]
        with patch.object(scheduling, "_get_client", return_value=mock_client):
            out = await scheduling.get_working_hours()
        mock_client.get.assert_called_once_with("/api/timeschemes")
        assert out == [{"name": "work"}]


class TestFindAvailableTimes:
    @pytest.mark.asyncio
    async def test_no_window(self, mock_client):
        mock_client.post.return_value = {"suggestions": []}
        with patch.object(scheduling, "_get_client", return_value=mock_client):
            out = await scheduling.find_available_times(attendees=["a@x.com"], duration_minutes=30)
        body = mock_client.post.call_args.kwargs["data"]
        assert body["attendees"] == ["a@x.com"]
        assert body["durationMinutes"] == 30
        assert "scheduleWindow" not in body
        assert out == {"suggestions": []}

    @pytest.mark.asyncio
    async def test_nl_window_resolved(self, mock_client):
        mock_client.post.return_value = {}
        with patch.object(scheduling, "_get_client", return_value=mock_client):
            await scheduling.find_available_times(
                attendees=["a@x.com"], duration_minutes=30, when="2026-04-20..2026-04-25"
            )
        body = mock_client.post.call_args.kwargs["data"]
        assert body["scheduleWindow"] == {"start": "2026-04-20", "end": "2026-04-25"}

    @pytest.mark.asyncio
    async def test_limit_passed_through(self, mock_client):
        mock_client.post.return_value = {}
        with patch.object(scheduling, "_get_client", return_value=mock_client):
            await scheduling.find_available_times(attendees=["a@x.com"], duration_minutes=30, limit=5)
        body = mock_client.post.call_args.kwargs["data"]
        assert body["limit"] == 5
