"""Tests for domain.battery — what the footer shows of the PiSugar's charge."""
import pytest

from gcal_epd.domain.battery import BatteryStatus


@pytest.mark.parametrize("percent, shown", [(87.5, 88), (87.4, 87), (0.4, 0), (99.6, 100),
                                            (19.5, 20), (20.5, 21)])
def test_percent_is_rounded_half_up(percent, shown):
    assert BatteryStatus(percent).shown_percent == shown


def test_unknown_has_no_percent():
    status = BatteryStatus.unknown()
    assert not status.known
    assert status.shown_percent is None
    assert not status.charging


def test_known_status_keeps_the_charging_flag():
    assert BatteryStatus(50, charging=True).charging
    assert BatteryStatus(50).known


@pytest.mark.parametrize("percent, low", [(19.4, True), (19.5, False), (20, False),
                                          (0, True), (85, False)])
def test_low_compares_the_percent_shown(percent, low):
    """Red exactly when the number on the panel is below the threshold."""
    assert BatteryStatus(percent).is_low(20) is low


def test_unknown_is_never_low():
    assert not BatteryStatus.unknown().is_low(20)
