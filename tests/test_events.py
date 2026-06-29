"""Tests for calendar event tools."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from reclaim_mcp.cache import invalidate_cache
from reclaim_mcp.tools import events


@pytest.fixture(autouse=True)
def _clear_cache():
    invalidate_cache()
    yield
    invalidate_cache()


@pytest.fixture
def mock_client() -> MagicMock:
    client = MagicMock()
    client.get = AsyncMock()
    client.post = AsyncMock()
    client.put = AsyncMock()
    return client


@pytest.fixture(autouse=True)
def _stub_user_tz():
    with patch("reclaim_mcp.tools.events.get_user_tz", AsyncMock(return_value="America/Los_Angeles")):
        yield


class TestListEvents:
    @pytest.mark.asyncio
    async def test_all_scope_hits_both_endpoints(self, mock_client):
        mock_client.get.side_effect = [
            [{"eventId": "e1", "title": "Sync"}],
            [{"eventId": "p1", "title": "Focus"}],
        ]
        with patch.object(events, "_get_client", return_value=mock_client):
            result = await events.list_events(when="today", scope="all")
        assert len(result) == 2
        assert mock_client.get.call_count == 2

    @pytest.mark.asyncio
    async def test_external_scope_only_hits_events(self, mock_client):
        mock_client.get.return_value = [{"eventId": "e1", "title": "Sync"}]
        with patch.object(events, "_get_client", return_value=mock_client):
            result = await events.list_events(when="today", scope="external")
        assert len(result) == 1
        assert mock_client.get.call_args.args[0] == "/api/events"

    @pytest.mark.asyncio
    async def test_personal_scope_only_hits_personal(self, mock_client):
        mock_client.get.return_value = [{"eventId": "p1", "title": "Focus"}]
        with patch.object(events, "_get_client", return_value=mock_client):
            result = await events.list_events(when="today", scope="personal")
        assert mock_client.get.call_args.args[0] == "/api/events/personal"
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_invalid_scope_errors(self):
        with pytest.raises(Exception) as exc:
            await events.list_events(when="today", scope="bogus")
        assert "scope must be one of" in str(exc.value)

    @pytest.mark.asyncio
    async def test_thin_projection(self, mock_client):
        mock_client.get.side_effect = [
            [
                {
                    "eventId": "e1",
                    "title": "Sync",
                    "eventStart": "2026-04-17",
                    "eventEnd": "2026-04-17",
                    "type": "EXTERNAL",
                    "rsvpStatus": "ACCEPTED",
                    "calendarId": 3,
                    "description": "lots of other fields",
                }
            ],
            [],
        ]
        with patch.object(events, "_get_client", return_value=mock_client):
            result = await events.list_events(when="today", detail="thin")
        assert result[0] == {
            "event_id": "e1",
            "calendar_id": 3,
            "title": "Sync",
            "start": "2026-04-17",
            "end": "2026-04-17",
            "type": "EXTERNAL",
            "rsvp": "ACCEPTED",
        }
        # Extra fields are dropped.
        assert "description" not in result[0]

    @pytest.mark.asyncio
    async def test_nl_when_resolves_to_range(self, mock_client):
        mock_client.get.return_value = []
        with patch.object(events, "_get_client", return_value=mock_client):
            await events.list_events(when="2026-04-20..2026-04-25", scope="external")
        call = mock_client.get.call_args
        assert call.kwargs["params"]["start"] == "2026-04-20"
        assert call.kwargs["params"]["end"] == "2026-04-25"


class TestGetEvent:
    @pytest.mark.asyncio
    async def test_returns_full_by_default(self, mock_client):
        mock_client.get.return_value = {"eventId": "e1", "title": "Sync", "description": "d"}
        with patch.object(events, "_get_client", return_value=mock_client):
            result = await events.get_event(calendar_id=3, event_id="e1")
        assert result["description"] == "d"

    @pytest.mark.asyncio
    async def test_thin_variant(self, mock_client):
        mock_client.get.return_value = {
            "eventId": "e1",
            "title": "Sync",
            "calendarId": 3,
            "description": "d",
            "eventStart": "2026-04-17",
            "eventEnd": "2026-04-17",
        }
        with patch.object(events, "_get_client", return_value=mock_client):
            result = await events.get_event(calendar_id=3, event_id="e1", detail="thin")
        assert "description" not in result


class TestRsvpEvent:
    @pytest.mark.asyncio
    async def test_accepted_maps_to_enum(self, mock_client):
        mock_client.put.return_value = {"ok": True}
        with patch.object(events, "_get_client", return_value=mock_client):
            result = await events.rsvp_event(calendar_id=3, event_id="e1", response="accepted")
        body = mock_client.put.call_args.args[1]
        assert body["responseStatus"] == "Accepted"
        assert body["sendUpdates"] is True
        assert "data" in result and "summary" in result

    @pytest.mark.asyncio
    async def test_notify_attendees_false(self, mock_client):
        mock_client.put.return_value = {}
        with patch.object(events, "_get_client", return_value=mock_client):
            await events.rsvp_event(calendar_id=3, event_id="e1", response="declined", notify_attendees=False)
        assert mock_client.put.call_args.args[1]["sendUpdates"] is False

    @pytest.mark.asyncio
    async def test_case_insensitive(self, mock_client):
        mock_client.put.return_value = {}
        with patch.object(events, "_get_client", return_value=mock_client):
            await events.rsvp_event(calendar_id=3, event_id="e1", response="TENTATIVE")
        assert mock_client.put.call_args.args[1]["responseStatus"] == "TentativelyAccepted"

    @pytest.mark.asyncio
    async def test_invalid_response(self):
        with pytest.raises(Exception) as exc:
            await events.rsvp_event(calendar_id=3, event_id="e1", response="maybe")
        assert "response must be one of" in str(exc.value)


class TestRescheduleEvent:
    @pytest.mark.asyncio
    async def test_nl_times_resolved_and_echoed(self, mock_client):
        from datetime import datetime
        from zoneinfo import ZoneInfo

        mock_client.post.return_value = {"eventId": "e1"}
        with patch.object(events, "_get_client", return_value=mock_client):
            # Patch parse_when to use a pinned reference for determinism.
            with patch("reclaim_mcp.tools.events.parse_when") as m_parse:
                tz = ZoneInfo("America/Los_Angeles")
                m_parse.side_effect = [
                    # First call: start
                    type(
                        "R",
                        (),
                        {
                            "iso": "2026-04-20T15:00:00-07:00",
                            "iso_utc": "2026-04-20T22:00:00Z",
                            "label": "Monday, April 20 at 3:00 PM PDT",
                            "dt": datetime(2026, 4, 20, 15, tzinfo=tz),
                        },
                    )(),
                    type(
                        "R",
                        (),
                        {
                            "iso": "2026-04-20T16:00:00-07:00",
                            "iso_utc": "2026-04-20T23:00:00Z",
                            "label": "Monday, April 20 at 4:00 PM PDT",
                            "dt": datetime(2026, 4, 20, 16, tzinfo=tz),
                        },
                    )(),
                ]
                result = await events.reschedule_event(event_id="e1", start_at="Monday 3pm", end_at="Monday 4pm")
        assert result["resolved"]["start_at"].startswith("2026-04-20T15:00")
        assert "Monday" in result["summary"]
        params = mock_client.post.call_args.kwargs["params"]
        assert params["start"] == "2026-04-20T22:00:00Z"
        assert params["end"] == "2026-04-20T23:00:00Z"

    @pytest.mark.asyncio
    async def test_start_after_end_errors(self, mock_client):
        from datetime import datetime
        from zoneinfo import ZoneInfo

        tz = ZoneInfo("America/Los_Angeles")
        with patch("reclaim_mcp.tools.events.parse_when") as m_parse:
            m_parse.side_effect = [
                type(
                    "R", (), {"iso": "x", "iso_utc": "x", "label": "late", "dt": datetime(2026, 4, 20, 16, tzinfo=tz)}
                )(),
                type(
                    "R", (), {"iso": "y", "iso_utc": "y", "label": "early", "dt": datetime(2026, 4, 20, 15, tzinfo=tz)}
                )(),
            ]
            with pytest.raises(Exception) as exc:
                await events.reschedule_event(event_id="e1", start_at="late", end_at="early")
        assert "before" in str(exc.value)
