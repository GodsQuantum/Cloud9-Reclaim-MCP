"""Tests for reclaim_mcp.responses — envelope + thin projectors."""

from reclaim_mcp.responses import make_response, thin_event, thin_habit, thin_task


class TestMakeResponse:
    def test_minimal_envelope(self):
        r = make_response({"id": 1}, "Did the thing.")
        assert r == {"data": {"id": 1}, "summary": "Did the thing."}

    def test_with_resolved(self):
        r = make_response(
            {"id": 1},
            "Snoozed until Monday.",
            resolved={"until": "2026-04-20T09:00:00-07:00"},
        )
        assert r["resolved"] == {"until": "2026-04-20T09:00:00-07:00"}

    def test_with_warnings(self):
        r = make_response({"id": 1}, "OK", warnings=["cache stale"])
        assert r["warnings"] == ["cache stale"]

    def test_no_empty_keys(self):
        # Don't include resolved/warnings when unused — keeps output clean.
        r = make_response({"id": 1}, "OK")
        assert "resolved" not in r
        assert "warnings" not in r


class TestThinTask:
    def test_converts_chunks_to_minutes(self):
        out = thin_task(
            {
                "id": 42,
                "title": "Draft plan",
                "status": "SCHEDULED",
                "priority": "P2",
                "timeChunksRequired": 4,
                "timeChunksSpent": 1,
            }
        )
        assert out["duration_minutes"] == 60
        assert out["minutes_worked"] == 15

    def test_includes_due_and_snooze(self):
        out = thin_task({"id": 1, "title": "x", "due": "2026-04-20", "snoozeUntil": "2026-04-18"})
        assert out["due"] == "2026-04-20"
        assert out["snooze_until"] == "2026-04-18"


class TestThinEvent:
    def test_uses_eventId_first(self):
        out = thin_event({"eventId": "abc", "id": "xyz", "calendarId": 1, "title": "Sync"})
        assert out["event_id"] == "abc"

    def test_falls_back_to_id(self):
        out = thin_event({"id": "xyz", "title": "Sync"})
        assert out["event_id"] == "xyz"


class TestThinHabit:
    def test_extracts_recurrence(self):
        out = thin_habit(
            {
                "lineageId": 7,
                "title": "Stretch",
                "enabled": True,
                "idealTime": "09:00:00",
                "durationMinMins": 15,
                "durationMaxMins": 30,
                "recurrence": {"frequency": "WEEKLY", "idealDays": ["MONDAY", "WEDNESDAY"]},
                "defenseAggression": "DEFAULT",
            }
        )
        assert out["habit_id"] == 7
        assert out["frequency"] == "WEEKLY"
        assert out["ideal_days"] == ["MONDAY", "WEDNESDAY"]

    def test_handles_missing_recurrence(self):
        out = thin_habit({"lineageId": 7, "title": "x"})
        assert out["frequency"] is None
