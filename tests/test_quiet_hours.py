from datetime import datetime

import pytest

from app import quiet_hours


def at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, 31, hour, minute, tzinfo=quiet_hours.LOCAL_TZ)


def test_nothing_is_quiet_when_the_setting_is_empty(monkeypatch):
    monkeypatch.delenv("QUIET_HOURS", raising=False)
    assert not quiet_hours.is_quiet(at(3))


def test_a_window_that_wraps_past_midnight(monkeypatch):
    monkeypatch.setenv("QUIET_HOURS", "22:00-07:00")
    assert quiet_hours.is_quiet(at(23))
    assert quiet_hours.is_quiet(at(3))
    assert quiet_hours.is_quiet(at(22, 0))        # inclusive at the start
    assert not quiet_hours.is_quiet(at(7, 0))     # exclusive at the end
    assert not quiet_hours.is_quiet(at(12))


def test_a_window_inside_one_day(monkeypatch):
    monkeypatch.setenv("QUIET_HOURS", "13:00-14:30")
    assert quiet_hours.is_quiet(at(13, 30))
    assert not quiet_hours.is_quiet(at(14, 30))
    assert not quiet_hours.is_quiet(at(2))


@pytest.mark.parametrize("bad", ["nonsense", "22:00", "25:00-07:00", "22-7", "22:00-", "-"])
def test_a_misspelt_window_sends_as_normal_rather_than_holding_everything(monkeypatch, bad):
    monkeypatch.setenv("QUIET_HOURS", bad)
    assert not quiet_hours.is_quiet(at(3))


def test_a_zero_length_window_is_not_an_all_day_one(monkeypatch):
    monkeypatch.setenv("QUIET_HOURS", "09:00-09:00")
    assert not quiet_hours.is_quiet(at(9))
