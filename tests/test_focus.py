"""Tests for focus-time tools."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from reclaim_mcp.cache import invalidate_cache
from reclaim_mcp.tools import focus


@pytest.fixture(autouse=True)
def _clear_cache():
    invalidate_cache()


@pytest.fixture
def mock_client():
    client = MagicMock()
    client.get = AsyncMock()
    client.post = AsyncMock()
    client.patch = AsyncMock()
    return client


@pytest.fixture(autouse=True)
def _stub_tz():
    with patch("reclaim_mcp.tools.focus.get_user_tz", AsyncMock(return_value="America/Los_Angeles")):
        yield


class TestSetFocusBlockLocked:
    @pytest.mark.asyncio
    async def test_lock(self, mock_client):
        mock_client.post.return_value = {}
        with patch.object(focus, "_get_client", return_value=mock_client):
            r = await focus.set_focus_block_locked(calendar_id=1, event_id="fb", locked=True)
        assert "lock" in mock_client.post.call_args.args[0]
        assert "/unlock" not in mock_client.post.call_args.args[0]
        assert "Locked" in r["summary"]

    @pytest.mark.asyncio
    async def test_unlock(self, mock_client):
        mock_client.post.return_value = {}
        with patch.object(focus, "_get_client", return_value=mock_client):
            r = await focus.set_focus_block_locked(calendar_id=1, event_id="fb", locked=False)
        assert "/unlock" in mock_client.post.call_args.args[0]
        assert "Unlocked" in r["summary"]


class TestRescheduleFocusBlock:
    @pytest.mark.asyncio
    async def test_ai_pick_when_no_times(self, mock_client):
        mock_client.post.return_value = {}
        with patch.object(focus, "_get_client", return_value=mock_client):
            r = await focus.reschedule_focus_block(calendar_id=1, event_id="fb")
        # Empty payload means Reclaim picks.
        assert mock_client.post.call_args.args[1] == {}
        assert "resolved" not in r  # nothing to echo back

    @pytest.mark.asyncio
    async def test_explicit_times(self, mock_client):
        from datetime import datetime
        from zoneinfo import ZoneInfo

        tz = ZoneInfo("America/Los_Angeles")
        mock_client.post.return_value = {}
        with patch.object(focus, "_get_client", return_value=mock_client):
            with patch("reclaim_mcp.tools.focus.parse_when") as m_parse:
                m_parse.side_effect = [
                    type(
                        "R",
                        (),
                        {
                            "iso": "2026-04-20T10:00:00-07:00",
                            "iso_utc": "2026-04-20T17:00:00Z",
                            "label": "Monday 10am",
                            "dt": datetime(2026, 4, 20, 10, tzinfo=tz),
                        },
                    )(),
                    type(
                        "R",
                        (),
                        {
                            "iso": "2026-04-20T11:00:00-07:00",
                            "iso_utc": "2026-04-20T18:00:00Z",
                            "label": "Monday 11am",
                            "dt": datetime(2026, 4, 20, 11, tzinfo=tz),
                        },
                    )(),
                ]
                r = await focus.reschedule_focus_block(
                    calendar_id=1,
                    event_id="fb",
                    start_at="Monday 10am",
                    end_at="Monday 11am",
                )
        body = mock_client.post.call_args.args[1]
        assert body["start"] == "2026-04-20T17:00:00Z"
        assert body["end"] == "2026-04-20T18:00:00Z"
        assert r["resolved"]["start_at"].startswith("2026-04-20T10:00")
