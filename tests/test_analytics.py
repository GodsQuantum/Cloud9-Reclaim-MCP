"""Tests for analytics tools."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from reclaim_mcp.cache import invalidate_cache
from reclaim_mcp.tools import analytics


@pytest.fixture(autouse=True)
def _clear_cache():
    invalidate_cache()


@pytest.fixture
def mock_client():
    client = MagicMock()
    client.get = AsyncMock()
    return client


@pytest.fixture(autouse=True)
def _stub_tz():
    with patch("reclaim_mcp.tools.analytics.get_user_tz", AsyncMock(return_value="America/Los_Angeles")):
        yield


class TestGetUserAnalytics:
    @pytest.mark.asyncio
    async def test_valid_metric(self, mock_client):
        mock_client.get.return_value = {"data": []}
        with patch.object(analytics, "_get_client", return_value=mock_client):
            out = await analytics.get_user_analytics(
                when="2026-04-01..2026-04-30",
                metric_name="DURATION_BY_CATEGORY",
            )
        params = mock_client.get.call_args.kwargs["params"]
        assert params == {"start": "2026-04-01", "end": "2026-04-30", "metricName": "DURATION_BY_CATEGORY"}
        assert out == {"data": []}

    @pytest.mark.asyncio
    async def test_invalid_metric(self):
        with pytest.raises(Exception) as exc:
            await analytics.get_user_analytics(when="today", metric_name="BOGUS")
        assert "metric_name must be" in str(exc.value)


class TestGetFocusInsights:
    @pytest.mark.asyncio
    async def test_range_resolved(self, mock_client):
        mock_client.get.return_value = {}
        with patch.object(analytics, "_get_client", return_value=mock_client):
            await analytics.get_focus_insights(when="this week")
        params = mock_client.get.call_args.kwargs["params"]
        assert "start" in params and "end" in params
