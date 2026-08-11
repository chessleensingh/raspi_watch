"""Tests for the spoiler-guard delay buffer.

The buffer's whole job is to answer "what did the world look like N seconds ago",
so every test here is about that question at some boundary.
"""

import pytest

from scoreboard.delay import DelayBuffer


def test_empty_buffer_reports_warming_up():
    buf = DelayBuffer()
    result = buf.get_delayed(delay_seconds=120, now=1000.0)

    assert result.games == []
    assert result.warming_up is True
    assert result.snapshot_age is None


def test_zero_delay_returns_newest_snapshot():
    buf = DelayBuffer()
    buf.append(["old"], timestamp=1000.0)
    buf.append(["new"], timestamp=1010.0)

    result = buf.get_delayed(delay_seconds=0, now=1010.0)

    assert result.games == ["new"]
    assert result.warming_up is False


def test_returns_most_recent_snapshot_at_or_before_target():
    buf = DelayBuffer()
    for ts, label in [(1000.0, "a"), (1015.0, "b"), (1030.0, "c"), (1045.0, "d")]:
        buf.append([label], timestamp=ts)

    # now=1045, delay=30 -> target=1015 -> exactly snapshot "b"
    assert buf.get_delayed(delay_seconds=30, now=1045.0).games == ["b"]

    # target=1020 falls between "b" and "c"; we must not show "c" yet.
    assert buf.get_delayed(delay_seconds=25, now=1045.0).games == ["b"]


def test_target_exactly_on_a_timestamp_is_inclusive():
    buf = DelayBuffer()
    buf.append(["a"], timestamp=1000.0)
    buf.append(["b"], timestamp=1060.0)

    # target == 1000.0 exactly. Inclusive, so "a" is eligible.
    result = buf.get_delayed(delay_seconds=60, now=1060.0)
    assert result.games == ["a"]


def test_delay_longer_than_buffer_span_serves_oldest_and_warns():
    """Right after startup we do not have 3 minutes of history yet.

    Showing fresh data silently would spoil fights, so we serve the oldest thing
    we have and flag it loudly.
    """
    buf = DelayBuffer()
    buf.append(["first"], timestamp=1000.0)
    buf.append(["second"], timestamp=1010.0)

    result = buf.get_delayed(delay_seconds=180, now=1010.0)

    assert result.games == ["first"]
    assert result.warming_up is True


def test_warming_up_clears_once_history_covers_the_delay():
    buf = DelayBuffer()
    buf.append(["a"], timestamp=1000.0)
    buf.append(["b"], timestamp=1100.0)

    assert buf.get_delayed(delay_seconds=60, now=1040.0).warming_up is True
    assert buf.get_delayed(delay_seconds=60, now=1100.0).warming_up is False


def test_snapshot_age_reports_how_stale_the_shown_data_is():
    buf = DelayBuffer()
    buf.append(["a"], timestamp=1000.0)

    result = buf.get_delayed(delay_seconds=0, now=1042.0)

    assert result.snapshot_age == pytest.approx(42.0)


def test_old_snapshots_are_evicted_beyond_retention():
    buf = DelayBuffer(retention_seconds=100)
    buf.append(["ancient"], timestamp=1000.0)
    buf.append(["recent"], timestamp=1150.0)

    # "ancient" is 150s old, past the 100s retention window.
    assert len(buf) == 1
    assert buf.get_delayed(delay_seconds=0, now=1150.0).games == ["recent"]


def test_eviction_never_empties_the_buffer():
    """A long gap in polling must not leave us with nothing to show."""
    buf = DelayBuffer(retention_seconds=100)
    buf.append(["only"], timestamp=1000.0)
    buf.append(["much_later"], timestamp=99999.0)

    assert len(buf) >= 1
    assert buf.get_delayed(delay_seconds=0, now=99999.0).games == ["much_later"]


def test_retention_must_exceed_the_delay_it_will_be_asked_for():
    """Guard against a config where we evict the very snapshot we need."""
    buf = DelayBuffer(retention_seconds=60)
    with pytest.raises(ValueError, match="retention"):
        buf.get_delayed(delay_seconds=120, now=1000.0)


def test_negative_delay_is_rejected():
    buf = DelayBuffer()
    with pytest.raises(ValueError):
        buf.get_delayed(delay_seconds=-5, now=1000.0)


def test_out_of_order_append_is_rejected():
    """Timestamps come from one poller thread and must be monotonic."""
    buf = DelayBuffer()
    buf.append(["a"], timestamp=1000.0)
    with pytest.raises(ValueError, match="monotonic"):
        buf.append(["b"], timestamp=999.0)
