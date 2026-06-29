"""Tests for reclaim_mcp.tools.context — context anchor tool."""

import os
from datetime import datetime
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

import pytest

os.environ.setdefault("RECLAIM_API_KEY", "test")

from reclaim_mcp.tools.context import (
    _active_timer,
    _extract_tz_from_timeschemes,
    _system_tz,
    _task_counts,
    _working_hours_for_today,
    get_context,
)


class TestExtractTzFromTimeschemes:
    def test_top_level_timezone(self):
        schemes = [{"timezone": "America/Los_Angeles"}]
        assert _extract_tz_from_timeschemes(schemes) == "America/Los_Angeles"

    def test_top_level_camelCase(self):
        schemes = [{"timeZone": "Europe/Berlin"}]
        assert _extract_tz_from_timeschemes(schemes) == "Europe/Berlin"

    def test_nested_in_schedule(self):
        schemes = [{"name": "work", "schedule": {"timezone": "Asia/Tokyo"}}]
        assert _extract_tz_from_timeschemes(schemes) == "Asia/Tokyo"

    def test_invalid_tz_falls_through(self):
        schemes = [{"timezone": "Middle-earth/Shire"}, {"timezone": "UTC"}]
        assert _extract_tz_from_timeschemes(schemes) == "UTC"

    def test_empty_returns_none(self):
        assert _extract_tz_from_timeschemes([]) is None
        assert _extract_tz_from_timeschemes(None) is None

    def test_no_tz_keys(self):
        assert _extract_tz_from_timeschemes([{"name": "work"}]) is None


class TestWorkingHoursForToday:
    def test_dict_shape(self):
        schemes = [
            {
                "primary": True,
                "hours": {"FRIDAY": {"start": "09:00", "end": "17:00"}},
            }
        ]
        assert _working_hours_for_today(schemes, "FRIDAY") == {"start": "09:00", "end": "17:00"}

    def test_list_of_intervals(self):
        schemes = [
            {
                "hours": {"MONDAY": [{"start": "10:00", "end": "12:00"}, {"start": "13:00", "end": "18:00"}]},
            }
        ]
        assert _working_hours_for_today(schemes, "MONDAY") == {"start": "10:00", "end": "12:00"}

    def test_missing_day_returns_none(self):
        assert _working_hours_for_today([{"hours": {}}], "SATURDAY") is None

    def test_empty_timeschemes(self):
        assert _working_hours_for_today([], "MONDAY") is None
        assert _working_hours_for_today(None, "MONDAY") is None


class TestTaskCounts:
    def test_counts_overdue_and_due_today(self):
        now = datetime(2026, 4, 17, 12, 0, 0, tzinfo=ZoneInfo("UTC"))
        tasks = [
            {"status": "SCHEDULED", "due": "2026-04-17T15:00:00Z"},  # due today
            {"status": "SCHEDULED", "due": "2026-04-15T15:00:00Z"},  # overdue
            {"status": "COMPLETE", "due": "2026-04-01T00:00:00Z"},  # completed, ignored
            {"status": "IN_PROGRESS", "due": "2026-04-17T20:00:00Z"},  # due today + in progress
            {"status": "NEW", "due": None},  # unscheduled
        ]
        counts = _task_counts(tasks, now)
        assert counts["total"] == 5
        assert counts["due_today"] == 2
        assert counts["overdue"] == 1
        assert counts["in_progress"] == 1
        assert counts["unscheduled"] == 1

    def test_ignores_malformed_due(self):
        now = datetime(2026, 4, 17, tzinfo=ZoneInfo("UTC"))
        counts = _task_counts([{"status": "NEW", "due": "not-a-date"}], now)
        assert counts["overdue"] == 0

    def test_non_list_returns_zeros(self):
        now = datetime(2026, 4, 17, tzinfo=ZoneInfo("UTC"))
        assert _task_counts(None, now)["total"] == 0


class TestActiveTimer:
    def test_finds_in_progress_task(self):
        tasks = [
            {"id": 1, "status": "NEW", "title": "x"},
            {"id": 2, "status": "IN_PROGRESS", "title": "Focus work", "timeChunksSpent": 2, "timeChunksRequired": 4},
        ]
        timer = _active_timer(tasks)
        assert timer == {
            "task_id": 2,
            "title": "Focus work",
            "minutes_worked": 30,
            "minutes_total": 60,
        }

    def test_none_if_no_active(self):
        assert _active_timer([{"status": "NEW"}]) is None
        assert _active_timer([]) is None
        assert _active_timer(None) is None


class TestSystemTz:
    def test_returns_a_valid_zone(self):
        tz = _system_tz()
        # Should at minimum be parseable.
        from zoneinfo import ZoneInfo

        ZoneInfo(tz)


@pytest.mark.asyncio
class TestGetContextEndToEnd:
    async def test_composes_four_endpoints(self):
        # Import inside test so we can patch the module-level client factory.
        # Ensure TTL cache miss for this call.
        from reclaim_mcp.cache import invalidate_cache
        from reclaim_mcp.tools import context as ctx_module

        invalidate_cache("get_context")

        mock_client = AsyncMock()
        mock_client.get.side_effect = [
            [
                {
                    "primary": True,
                    "timezone": "America/Los_Angeles",
                    "hours": {"FRIDAY": {"start": "09:00", "end": "17:00"}},
                }
            ],
            {"title": "Focus work"},
            {"title": "Sync with team"},
            [
                {
                    "id": 1,
                    "status": "IN_PROGRESS",
                    "title": "Focus work",
                    "timeChunksSpent": 1,
                    "timeChunksRequired": 4,
                    "due": None,
                }
            ],
        ]

        with patch.object(ctx_module, "_get_client", return_value=mock_client):
            result = await get_context()

        assert result["timezone"] == "America/Los_Angeles"
        assert result["current_moment"] == {"title": "Focus work"}
        assert result["next_moment"] == {"title": "Sync with team"}
        assert result["active_timer"]["title"] == "Focus work"
        assert result["task_counts"]["in_progress"] == 1

    async def test_env_tz_overrides_api(self, monkeypatch):
        from reclaim_mcp.cache import invalidate_cache
        from reclaim_mcp.tools import context as ctx_module

        invalidate_cache("get_context")
        monkeypatch.setenv("RECLAIM_TIMEZONE", "Europe/Berlin")

        mock_client = AsyncMock()
        mock_client.get.side_effect = [
            [{"timezone": "America/Los_Angeles"}],  # API says LA
            {},
            {},
            [],
        ]

        # Clear the settings lru_cache if there is one — config reads env each call.
        with patch.object(ctx_module, "_get_client", return_value=mock_client):
            result = await get_context()

        assert result["timezone"] == "Europe/Berlin"
