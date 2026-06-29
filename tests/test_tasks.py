"""Tests for task tools."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from reclaim_mcp.cache import invalidate_cache
from reclaim_mcp.tools import tasks


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


@pytest.fixture(autouse=True)
def _stub_tz():
    with patch("reclaim_mcp.tools.tasks.get_user_tz", AsyncMock(return_value="America/Los_Angeles")):
        yield


def _r(iso: str, label: str, dt: datetime):
    """Build a mock ResolvedTime stand-in."""
    return type(
        "R",
        (),
        {
            "iso": iso,
            "iso_utc": iso.replace("-07:00", "Z").replace("-08:00", "Z"),
            "label": label,
            "dt": dt,
        },
    )()


class TestListTasks:
    @pytest.mark.asyncio
    async def test_active_default(self, mock_client):
        mock_client.get.return_value = [
            {"id": 1, "title": "a", "status": "NEW", "timeChunksRequired": 4},
        ]
        with patch.object(tasks, "_get_client", return_value=mock_client):
            out = await tasks.list_tasks()
        params = mock_client.get.call_args.kwargs["params"]
        assert params["status"] == "NEW,SCHEDULED,IN_PROGRESS"
        assert out[0]["duration_minutes"] == 60

    @pytest.mark.asyncio
    async def test_completed(self, mock_client):
        mock_client.get.return_value = []
        with patch.object(tasks, "_get_client", return_value=mock_client):
            await tasks.list_tasks(filter="completed")
        assert mock_client.get.call_args.kwargs["params"]["status"] == "COMPLETE,ARCHIVED"

    @pytest.mark.asyncio
    async def test_overdue_client_side_filter(self, mock_client):
        # With tz stubbed to LA and 'now' real, we simulate two tasks: one due
        # in the past, one due in the future. Only overdue should come back.
        from datetime import date, timedelta

        today = date.today()
        past = (today - timedelta(days=2)).isoformat() + "T00:00:00Z"
        future = (today + timedelta(days=2)).isoformat() + "T00:00:00Z"
        mock_client.get.return_value = [
            {"id": 1, "title": "old", "status": "SCHEDULED", "due": past, "timeChunksRequired": 1},
            {"id": 2, "title": "new", "status": "SCHEDULED", "due": future, "timeChunksRequired": 1},
        ]
        with patch.object(tasks, "_get_client", return_value=mock_client):
            out = await tasks.list_tasks(filter="overdue", detail="full")
        assert len(out) == 1
        assert out[0]["id"] == 1

    @pytest.mark.asyncio
    async def test_invalid_filter(self):
        with pytest.raises(Exception) as exc:
            await tasks.list_tasks(filter="bogus")
        assert "filter must be one of" in str(exc.value)


class TestGetTask:
    @pytest.mark.asyncio
    async def test_full_default(self, mock_client):
        mock_client.get.return_value = {"id": 1, "title": "x", "description": "d"}
        with patch.object(tasks, "_get_client", return_value=mock_client):
            out = await tasks.get_task(task_id=1)
        assert "description" in out


class TestCreateTask:
    @pytest.mark.asyncio
    async def test_nl_due_resolved(self, mock_client):
        mock_client.post.return_value = {"id": 7, "title": "x"}
        tz = ZoneInfo("America/Los_Angeles")
        with patch.object(tasks, "_get_client", return_value=mock_client):
            with patch("reclaim_mcp.tools.tasks.parse_when") as m_parse:
                m_parse.return_value = _r(
                    "2026-04-24T09:00:00-07:00", "Friday, April 24 at 9:00 AM PDT", datetime(2026, 4, 24, 9, tzinfo=tz)
                )
                r = await tasks.create_task(
                    title="Draft plan",
                    duration_minutes=60,
                    due_at="next Friday",
                    priority="P1",
                )
        body = mock_client.post.call_args.args[1]
        assert body["title"] == "Draft plan"
        assert body["deadline"] == "2026-04-24"
        assert body["priority"] == "P1"
        assert body["timeChunksRequired"] == 4
        assert r["resolved"]["due_at"].startswith("2026-04-24T09:00")
        assert "Draft plan" in r["summary"]

    @pytest.mark.asyncio
    async def test_no_due(self, mock_client):
        mock_client.post.return_value = {"id": 1}
        with patch.object(tasks, "_get_client", return_value=mock_client):
            r = await tasks.create_task(title="x", duration_minutes=30)
        body = mock_client.post.call_args.args[1]
        assert "deadline" not in body
        assert "resolved" not in r


class TestSnoozeTask:
    @pytest.mark.asyncio
    async def test_clear_when_none(self, mock_client):
        mock_client.post.return_value = {}
        with patch.object(tasks, "_get_client", return_value=mock_client):
            r = await tasks.snooze_task(task_id=1, until=None)
        assert mock_client.post.call_args.args[0].endswith("/clear-snooze")
        assert "Cleared" in r["summary"]

    @pytest.mark.asyncio
    async def test_nl_snooze(self, mock_client):
        mock_client.patch.return_value = {}
        tz = ZoneInfo("America/Los_Angeles")
        with patch.object(tasks, "_get_client", return_value=mock_client):
            with patch("reclaim_mcp.tools.tasks.parse_when") as m_parse:
                m_parse.return_value = _r(
                    "2026-04-18T09:00:00-07:00",
                    "Saturday, April 18 at 9:00 AM PDT",
                    datetime(2026, 4, 18, 9, tzinfo=tz),
                )
                r = await tasks.snooze_task(task_id=1, until="tomorrow")
        body = mock_client.patch.call_args.args[1]
        assert "snoozeUntil" in body
        assert r["resolved"]["until"].startswith("2026-04-18T09:00")


class TestComplete:
    @pytest.mark.asyncio
    async def test_hits_done_endpoint(self, mock_client):
        mock_client.post.return_value = {}
        with patch.object(tasks, "_get_client", return_value=mock_client):
            r = await tasks.complete_task(task_id=1)
        assert mock_client.post.call_args.args[0].endswith("/done/task/1")
        assert "Completed" in r["summary"]


class TestLogWork:
    @pytest.mark.asyncio
    async def test_logs_minutes_as_query_param(self, mock_client):
        mock_client.post.return_value = {}
        with patch.object(tasks, "_get_client", return_value=mock_client):
            r = await tasks.log_work(task_id=1, minutes=45)
        params = mock_client.post.call_args.kwargs["params"]
        assert params["minutes"] == 45
        assert "Logged 45 min" in r["summary"]

    @pytest.mark.asyncio
    async def test_notes_patched_separately(self, mock_client):
        mock_client.post.return_value = {}
        with patch.object(tasks, "_get_client", return_value=mock_client):
            await tasks.log_work(task_id=1, minutes=30, notes="drafted intro")
        mock_client.patch.assert_called_once()
        assert mock_client.patch.call_args.args[1] == {"notes": "drafted intro"}


class TestExtendTask:
    @pytest.mark.asyncio
    async def test_hits_add_time_endpoint(self, mock_client):
        mock_client.post.return_value = {}
        with patch.object(tasks, "_get_client", return_value=mock_client):
            r = await tasks.extend_task(task_id=1, minutes=30)
        assert "/add-time/" in mock_client.post.call_args.args[0]
        assert "Extended" in r["summary"]


class TestPlanTaskWork:
    @pytest.mark.asyncio
    async def test_resolves_at(self, mock_client):
        mock_client.post.return_value = {}
        tz = ZoneInfo("America/Los_Angeles")
        with patch.object(tasks, "_get_client", return_value=mock_client):
            with patch("reclaim_mcp.tools.tasks.parse_when") as m_parse:
                m_parse.return_value = _r(
                    "2026-04-20T10:00:00-07:00",
                    "Monday, April 20 at 10:00 AM PDT",
                    datetime(2026, 4, 20, 10, tzinfo=tz),
                )
                r = await tasks.plan_task_work(task_id=1, at="Monday 10am", duration_minutes=60)
        params = mock_client.post.call_args.kwargs["params"]
        assert "dateTime" in params
        assert params["durationMinutes"] == 60
        assert r["resolved"]["at"].startswith("2026-04-20T10:00")


class TestRestoreTask:
    @pytest.mark.asyncio
    async def test_archived_calls_unarchive(self, mock_client):
        mock_client.get.return_value = {"id": 1, "status": "ARCHIVED"}
        mock_client.post.return_value = {}
        with patch.object(tasks, "_get_client", return_value=mock_client):
            r = await tasks.restore_task(task_id=1)
        assert "/unarchive/" in mock_client.post.call_args.args[0]
        assert "Unarchived" in r["summary"]

    @pytest.mark.asyncio
    async def test_completed_calls_restart(self, mock_client):
        mock_client.get.return_value = {"id": 1, "status": "COMPLETE"}
        mock_client.post.return_value = {}
        with patch.object(tasks, "_get_client", return_value=mock_client):
            r = await tasks.restore_task(task_id=1)
        assert "/restart/" in mock_client.post.call_args.args[0]
        assert "Restarted" in r["summary"]


class TestStartStop:
    @pytest.mark.asyncio
    async def test_start(self, mock_client):
        mock_client.post.return_value = {}
        with patch.object(tasks, "_get_client", return_value=mock_client):
            r = await tasks.start_task(task_id=1)
        assert "/start/task/1" in mock_client.post.call_args.args[0]
        assert "Started" in r["summary"]

    @pytest.mark.asyncio
    async def test_stop(self, mock_client):
        mock_client.post.return_value = {}
        with patch.object(tasks, "_get_client", return_value=mock_client):
            r = await tasks.stop_task(task_id=1)
        assert "/stop/task/1" in mock_client.post.call_args.args[0]
