"""Tests for smart-habit tools."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from reclaim_mcp.cache import invalidate_cache
from reclaim_mcp.tools import habits


@pytest.fixture(autouse=True)
def _clear_cache():
    invalidate_cache()


@pytest.fixture
def mock_client():
    client = MagicMock()
    client.get = AsyncMock()
    client.post = AsyncMock()
    client.patch = AsyncMock()
    client.delete = AsyncMock()
    return client


class TestListHabits:
    @pytest.mark.asyncio
    async def test_thin_projection(self, mock_client):
        mock_client.get.return_value = [
            {
                "lineageId": 1,
                "title": "Stretch",
                "enabled": True,
                "description": "extra",
                "recurrence": {"frequency": "DAILY"},
                "idealTime": "09:00:00",
                "durationMinMins": 10,
                "durationMaxMins": 20,
                "defenseAggression": "DEFAULT",
            }
        ]
        with patch.object(habits, "_get_client", return_value=mock_client):
            out = await habits.list_habits()
        assert out[0]["habit_id"] == 1
        assert "description" not in out[0]

    @pytest.mark.asyncio
    async def test_full_returns_raw(self, mock_client):
        mock_client.get.return_value = [{"lineageId": 1, "description": "extra"}]
        with patch.object(habits, "_get_client", return_value=mock_client):
            out = await habits.list_habits(detail="full")
        assert out[0]["description"] == "extra"


class TestGetHabit:
    @pytest.mark.asyncio
    async def test_uses_habit_id(self, mock_client):
        mock_client.get.return_value = {"lineageId": 7, "title": "x"}
        with patch.object(habits, "_get_client", return_value=mock_client):
            await habits.get_habit(habit_id=7)
        assert mock_client.get.call_args.args[0].endswith("/7")


class TestCreateHabit:
    @pytest.mark.asyncio
    async def test_builds_payload(self, mock_client):
        mock_client.post.return_value = {"lineageId": 10}
        with patch.object(habits, "_get_client", return_value=mock_client):
            r = await habits.create_habit(
                title="Lunch walk",
                ideal_time="12:30",
                duration_min_mins=20,
                frequency="DAILY",
                event_type="PERSONAL",
            )
        body = mock_client.post.call_args.kwargs["data"]
        assert body["title"] == "Lunch walk"
        assert body["idealTime"] == "12:30:00"
        assert body["recurrence"] == {"frequency": "DAILY"}
        assert body["eventType"] == "PERSONAL"
        assert body["organizer"]["timePolicyType"] == "PERSONAL"
        assert "summary" in r

    @pytest.mark.asyncio
    async def test_weekly_with_days(self, mock_client):
        mock_client.post.return_value = {}
        with patch.object(habits, "_get_client", return_value=mock_client):
            await habits.create_habit(
                title="Gym",
                ideal_time="07:00",
                duration_min_mins=60,
                frequency="WEEKLY",
                ideal_days=["MONDAY", "WEDNESDAY", "FRIDAY"],
            )
        body = mock_client.post.call_args.kwargs["data"]
        assert body["recurrence"]["idealDays"] == ["MONDAY", "WEDNESDAY", "FRIDAY"]


class TestSetHabitEnabled:
    @pytest.mark.asyncio
    async def test_enable(self, mock_client):
        mock_client.post.return_value = {}
        with patch.object(habits, "_get_client", return_value=mock_client):
            r = await habits.set_habit_enabled(habit_id=7, enabled=True)
        assert mock_client.post.call_args.args[0].endswith("/enable")
        assert "Enabled" in r["summary"]

    @pytest.mark.asyncio
    async def test_disable(self, mock_client):
        with patch.object(habits, "_get_client", return_value=mock_client):
            r = await habits.set_habit_enabled(habit_id=7, enabled=False)
        assert mock_client.delete.call_args.args[0].endswith("/disable")
        assert "Disabled" in r["summary"]


class TestInstanceActions:
    @pytest.mark.asyncio
    async def test_complete(self, mock_client):
        mock_client.post.return_value = {}
        with patch.object(habits, "_get_client", return_value=mock_client):
            r = await habits.complete_habit_instance(event_id="inst-1")
        assert mock_client.post.call_args.args[0].endswith("/inst-1/done")
        assert "Completed" in r["summary"]

    @pytest.mark.asyncio
    async def test_skip(self, mock_client):
        mock_client.post.return_value = {}
        with patch.object(habits, "_get_client", return_value=mock_client):
            r = await habits.skip_habit_instance(event_id="inst-1")
        assert mock_client.post.call_args.args[0].endswith("/inst-1/skip")
        assert "Skipped" in r["summary"]

    @pytest.mark.asyncio
    async def test_lock_and_unlock(self, mock_client):
        mock_client.post.return_value = {}
        with patch.object(habits, "_get_client", return_value=mock_client):
            r_lock = await habits.set_habit_instance_locked(event_id="i", locked=True)
            r_un = await habits.set_habit_instance_locked(event_id="i", locked=False)
        endpoints = [c.args[0] for c in mock_client.post.call_args_list]
        assert endpoints[0].endswith("/lock")
        assert endpoints[1].endswith("/unlock")
        assert "Locked" in r_lock["summary"]
        assert "Unlocked" in r_un["summary"]


class TestHabitTimer:
    @pytest.mark.asyncio
    async def test_start(self, mock_client):
        mock_client.post.return_value = {}
        with patch.object(habits, "_get_client", return_value=mock_client):
            r = await habits.start_habit(habit_id=7)
        assert mock_client.post.call_args.args[0].endswith("/start")
        assert "Started" in r["summary"]

    @pytest.mark.asyncio
    async def test_stop(self, mock_client):
        mock_client.post.return_value = {}
        with patch.object(habits, "_get_client", return_value=mock_client):
            r = await habits.stop_habit(habit_id=7)
        assert mock_client.post.call_args.args[0].endswith("/stop")
        assert "Stopped" in r["summary"]


class TestDeleteHabit:
    @pytest.mark.asyncio
    async def test_delete(self, mock_client):
        with patch.object(habits, "_get_client", return_value=mock_client):
            r = await habits.delete_habit(habit_id=7)
        mock_client.delete.assert_called_once()
        assert r["data"]["deleted"] is True


class TestUpdateHabit:
    @pytest.mark.asyncio
    async def test_partial_update(self, mock_client):
        mock_client.patch.return_value = {}
        with patch.object(habits, "_get_client", return_value=mock_client):
            await habits.update_habit(habit_id=7, title="New name")
        body = mock_client.patch.call_args.kwargs["data"]
        assert body == {"title": "New name"}
