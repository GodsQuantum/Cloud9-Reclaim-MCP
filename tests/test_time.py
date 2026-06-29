"""Tests for reclaim_mcp.time — NL time parsing and range resolution."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from reclaim_mcp.time import TimeParseError, parse_date, parse_range, parse_when

TZ = "America/Los_Angeles"
NOW = datetime(2026, 4, 17, 12, 0, 0, tzinfo=ZoneInfo(TZ))  # Friday noon


class TestParseWhen:
    def test_iso_with_offset_preserves_tz(self):
        r = parse_when("2026-04-20T15:00:00-07:00", tz=TZ, now=NOW)
        assert r.iso == "2026-04-20T15:00:00-07:00"

    def test_iso_with_z_converts_to_user_tz(self):
        r = parse_when("2026-04-20T15:00:00Z", tz=TZ, now=NOW)
        assert r.dt.hour == 8  # 15 UTC = 8 PDT
        assert r.iso_utc == "2026-04-20T15:00:00Z"

    def test_date_only_uses_day_start_hour(self):
        r = parse_when("2026-04-20", tz=TZ, now=NOW)
        assert r.dt.hour == 9
        assert r.dt.minute == 0

    def test_date_only_custom_day_start(self):
        r = parse_when("2026-04-20", tz=TZ, now=NOW, day_start_hour=10)
        assert r.dt.hour == 10

    def test_tomorrow(self):
        r = parse_when("tomorrow", tz=TZ, now=NOW)
        assert r.dt.day == 18
        assert r.dt.hour == 9

    def test_tomorrow_at_3pm(self):
        r = parse_when("tomorrow at 3pm", tz=TZ, now=NOW)
        assert r.dt.day == 18
        assert r.dt.hour == 15

    def test_tomorrow_morning(self):
        r = parse_when("tomorrow morning", tz=TZ, now=NOW)
        assert r.dt.day == 18
        assert r.dt.hour == 9

    def test_tomorrow_afternoon(self):
        r = parse_when("tomorrow afternoon", tz=TZ, now=NOW)
        assert r.dt.hour == 14

    def test_in_n_hours(self):
        r = parse_when("in 2 hours", tz=TZ, now=NOW)
        assert r.dt.hour == 14

    def test_in_n_minutes(self):
        r = parse_when("in 30 minutes", tz=TZ, now=NOW)
        assert r.dt.hour == 12 and r.dt.minute == 30

    def test_next_weekday_applies_day_start(self):
        r = parse_when("next Tuesday", tz=TZ, now=NOW)
        assert r.dt.weekday() == 1
        assert r.dt.hour == 9

    def test_next_weekday_with_time(self):
        r = parse_when("next Friday at 10am", tz=TZ, now=NOW)
        assert r.dt.weekday() == 4
        assert r.dt.hour == 10

    def test_bare_weekday_applies_day_start(self):
        r = parse_when("Friday", tz=TZ, now=NOW)
        assert r.dt.weekday() == 4
        assert r.dt.hour == 9

    def test_tonight(self):
        r = parse_when("tonight", tz=TZ, now=NOW)
        assert r.dt.day == 17
        assert r.dt.hour == 21

    def test_tonight_with_explicit_time(self):
        r = parse_when("tonight at 11pm", tz=TZ, now=NOW)
        assert r.dt.day == 17
        assert r.dt.hour == 23

    def test_this_evening(self):
        r = parse_when("this evening", tz=TZ, now=NOW)
        assert r.dt.day == 17
        assert r.dt.hour == 18

    def test_noon(self):
        r = parse_when("noon tomorrow", tz=TZ, now=NOW)
        assert r.dt.day == 18
        assert r.dt.hour == 12

    def test_empty_raises(self):
        with pytest.raises(TimeParseError):
            parse_when("", tz=TZ, now=NOW)

    def test_garbage_raises(self):
        with pytest.raises(TimeParseError):
            parse_when("asdfghjkl", tz=TZ, now=NOW)

    def test_label_includes_weekday_and_time(self):
        r = parse_when("Monday at 2pm", tz=TZ, now=NOW)
        assert "Monday" in r.label
        assert "2:00 PM" in r.label


class TestParseDate:
    def test_returns_ymd(self):
        assert parse_date("tomorrow", tz=TZ, now=NOW) == "2026-04-18"

    def test_iso_input(self):
        assert parse_date("2026-04-20T15:00:00Z", tz=TZ, now=NOW) == "2026-04-20"


class TestParseRange:
    def test_today(self):
        assert parse_range("today", tz=TZ, now=NOW) == ("2026-04-17", "2026-04-17")

    def test_tomorrow(self):
        assert parse_range("tomorrow", tz=TZ, now=NOW) == ("2026-04-18", "2026-04-18")

    def test_this_week(self):
        # Friday 2026-04-17 → week is Mon 04-13 .. Sun 04-19
        assert parse_range("this week", tz=TZ, now=NOW) == ("2026-04-13", "2026-04-19")

    def test_next_week(self):
        assert parse_range("next week", tz=TZ, now=NOW) == ("2026-04-20", "2026-04-26")

    def test_last_week(self):
        assert parse_range("last week", tz=TZ, now=NOW) == ("2026-04-06", "2026-04-12")

    def test_next_n_days(self):
        assert parse_range("next 7 days", tz=TZ, now=NOW) == ("2026-04-17", "2026-04-24")

    def test_this_month(self):
        assert parse_range("this month", tz=TZ, now=NOW) == ("2026-04-01", "2026-04-30")

    def test_explicit_range(self):
        assert parse_range("2026-04-20..2026-04-25", tz=TZ, now=NOW) == ("2026-04-20", "2026-04-25")

    def test_single_date_same_start_end(self):
        assert parse_range("next Tuesday", tz=TZ, now=NOW) == ("2026-04-21", "2026-04-21")
