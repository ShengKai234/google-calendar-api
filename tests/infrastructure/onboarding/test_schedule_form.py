"""Tests for the wake-up times on the calendar setup form."""
import re
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import time as clock

import pytest

from gcal_epd.domain.power_schedule import PowerSchedule
from gcal_epd.infrastructure.onboarding.server import FeedSetupServer, ScheduleFields
from tests.infrastructure.onboarding.test_server import feed_server  # noqa: F401 (fixture)

THREE = PowerSchedule(slots=(clock(6, 0), clock(12, 30), clock(21, 15)),
                      enabled=False, wake_lead_minutes=9)


def _start(srv) -> str:
    s = socket.socket(); s.bind(("127.0.0.1", 0))
    srv.port = s.getsockname()[1]; s.close()
    threading.Thread(target=srv.serve_until_configured, daemon=True).start()
    for _ in range(50):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{srv.port}", timeout=1)
            break
        except Exception:
            time.sleep(0.05)
    return f"http://127.0.0.1:{srv.port}"


@pytest.fixture
def scheduled(tmp_path):
    """Start a form with a recording save function; returns (base, server, saved)."""
    def start(schedule=None, save=None):
        saved = []
        srv = FeedSetupServer(tmp_path / "ics_feeds.toml", port=0, pin="123456",
                              timeout=20, schedule=schedule,
                              save_schedule=save or saved.append)
        return _start(srv), srv, saved
    return start


def _submit(base, fields: list[tuple[str, str]], timeout=30):
    """POST fields in order, repeated names included, as a browser does."""
    data = urllib.parse.urlencode(fields).encode()
    try:
        with urllib.request.urlopen(base, data=data, timeout=timeout) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def _form(pin, urls, *slots, enabled=True, section=True):
    fields = [("pin", pin), ("urls", urls)]
    if section:
        fields.append(("schedule", "1"))
    fields += [("slot", s) for s in slots]
    if enabled:
        fields.append(("enabled", "1"))
    return fields


def _time_inputs(body: str) -> list[str]:
    return re.findall(r'<input type="time" name="slot"[^>]*value="([^"]*)"', body)


def _get(base) -> str:
    return urllib.request.urlopen(base, timeout=5).read().decode()


# --- rendering ---

def test_form_prefills_the_default_two_times(scheduled):
    base, _, _ = scheduled()
    body = _get(base)
    assert "Display wake-up times" in body
    assert _time_inputs(body) == ["07:00", "19:00"]
    assert 'name="enabled" value="1" checked' in body
    assert "Turn off between updates to save battery" in body
    assert "wakes a few minutes before each time" in body


def test_form_shows_one_input_per_slot_and_the_checkbox_state(scheduled):
    base, _, _ = scheduled(schedule=THREE)
    body = _get(base)
    assert _time_inputs(body) == ["06:00", "12:30", "21:15"]
    assert 'name="enabled" value="1">' in body  # unticked


def test_time_values_are_escaped():
    html = ScheduleFields(['"><script>x</script>'], True).html()
    assert "<script>" not in html and "&quot;&gt;&lt;script&gt;" in html


def test_section_always_has_a_box_to_type_in():
    assert _time_inputs(ScheduleFields([], True).html()) == [""]


# --- parsing ---

def test_from_form_needs_the_section_marker():
    assert ScheduleFields.from_form({"slot": ["07:00"]}) is None
    fields = ScheduleFields.from_form({"schedule": ["1"], "slot": [" 07:00 ", ""]})
    assert fields == ScheduleFields(["07:00", ""], False)


def test_to_schedule_ignores_blanks_and_keeps_the_lead():
    schedule = ScheduleFields(["", "19:00", "07:00"], True).to_schedule(THREE)
    assert schedule == PowerSchedule(slots=(clock(7, 0), clock(19, 0)),
                                     enabled=True, wake_lead_minutes=9)


# --- saving ---

def test_submission_saves_times_through_the_injected_function(scheduled, feed_server):
    base, srv, saved = scheduled()
    code, body = _submit(base, _form("123456", feed_server, "08:00", "20:30"))
    assert code == 200
    assert saved == [PowerSchedule(slots=(clock(8, 0), clock(20, 30)))]
    assert "Wake-up times: 08:00, 20:30." in body
    assert srv.feeds_path.exists()


def test_submission_keeps_the_wake_up_lead_from_the_file(scheduled, feed_server):
    base, _, saved = scheduled(schedule=THREE)
    _submit(base, _form("123456", feed_server, "09:00", "18:00"))
    assert saved[0].wake_lead_minutes == 9


def test_unticked_checkbox_saves_always_on(scheduled, feed_server):
    base, _, saved = scheduled()
    _submit(base, _form("123456", feed_server, "07:00", "19:00", enabled=False))
    assert saved[0].enabled is False


def test_any_number_of_times_and_blanks_are_ignored(scheduled, feed_server):
    """An "Add time" button only adds inputs; the server already takes them."""
    base, _, saved = scheduled()
    code, _ = _submit(base, _form("123456", feed_server, "19:00", "", "07:00", "12:00"))
    assert code == 200
    assert saved[0].slots == (clock(7, 0), clock(12, 0), clock(19, 0))


def test_a_form_without_the_section_leaves_the_schedule_alone(scheduled, feed_server):
    base, srv, saved = scheduled()
    code, _ = _submit(base, _form("123456", feed_server, section=False, enabled=False))
    assert code == 200
    assert saved == [] and srv.feeds_path.exists()


def test_failed_save_still_finishes_setup(scheduled, feed_server):
    def broken(schedule):
        raise OSError("disk full")
    base, srv, _ = scheduled(save=broken)
    code, body = _submit(base, _form("123456", feed_server, "08:00", "20:00"))
    assert code == 200
    assert "could not be saved" in body
    assert srv.feeds_path.exists()


# --- validation keeps what was typed ---

@pytest.mark.parametrize("slots,message", [
    (("07:00", "25:00"), "25:00 is not a time of day"),
    (("07:00", "7am"), "7am is not a time like 07:00"),
    (("07:00", "07:15"), "at least 30 minutes apart"),
    (("23:50", "00:10"), "at least 30 minutes apart"),  # around midnight
    (("", ""), "Set between 1 and 8 times"),
])
def test_bad_times_are_rejected_and_nothing_is_saved(scheduled, feed_server, slots, message):
    base, srv, saved = scheduled()
    code, body = _submit(base, _form("123456", feed_server, *slots))
    assert code == 400
    assert message in body and 'class="msg err"' in body
    assert saved == [] and not srv.feeds_path.exists()


def test_rejected_times_keep_everything_typed(scheduled):
    base, _, _ = scheduled()
    code, body = _submit(base, _form("123456", "https://h.example/a.ics",
                                     "06:00", "06:10", enabled=False))
    assert code == 400
    assert _time_inputs(body) == ["06:00", "06:10"]
    assert 'value="123456"' in body  # the PIN
    assert "https://h.example/a.ics" in body
    assert 'name="enabled" value="1">' in body  # still unticked


def test_bad_times_and_bad_links_are_reported_together(scheduled):
    base, _, _ = scheduled()
    code, body = _submit(base, _form("123456", "ftp://h/a.ics", "07:00", "07:05"))
    assert code == 400
    assert "URL must start with" in body and "at least 30 minutes apart" in body


def test_wrong_pin_keeps_the_times(scheduled, feed_server):
    base, _, saved = scheduled()
    code, body = _submit(base, _form("000000", feed_server, "05:45", "22:00"))
    assert code == 403
    assert _time_inputs(body) == ["05:45", "22:00"]
    assert saved == []


def test_unreachable_feed_keeps_the_times_and_saves_nothing(scheduled):
    base, _, saved = scheduled()
    code, body = _submit(base, _form("123456", "http://127.0.0.1:9/none.ics",
                                     "08:00", "20:00"))
    assert code == 400
    assert _time_inputs(body) == ["08:00", "20:00"]
    assert saved == []
