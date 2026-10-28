"""Releases side by side; `current` always names one whole release."""
import os

import pytest

from gcal_epd import config
from gcal_epd.infrastructure.release.layout import INCOMPLETE, ReleaseError, ReleaseLayout


def _install(layout, label):
    path = layout.begin(label)
    (path / "app.txt").write_text(label)
    layout.finish(label)
    return path


@pytest.fixture
def layout(tmp_path):
    return ReleaseLayout(tmp_path / "e-pages")


def test_empty_layout(layout):
    assert layout.labels() == []
    assert layout.current() is None and layout.previous() is None


def test_unfinished_build_is_not_a_release(layout):
    layout.begin("0.2.0")
    assert not layout.is_complete("0.2.0")
    assert layout.labels() == []
    with pytest.raises(ReleaseError):
        layout.switch("0.2.0")


def test_finished_release_names_itself(layout):
    path = _install(layout, "0.2.0")
    assert layout.is_complete("0.2.0")
    assert (path / "RELEASE").read_text() == "0.2.0\n"
    assert not (path / INCOMPLETE).exists()


def test_release_is_named_before_it_is_finished(layout):
    """The build checks `--version` against its RELEASE file before finishing."""
    path = layout.begin("0.2.0")
    assert (path / "RELEASE").read_text() == "0.2.0\n"


def test_installed_release_finds_its_data_dir(layout):
    path = _install(layout, "0.2.0")
    assert config.data_dir(path, env={}) == layout.data


def test_first_switch_has_no_previous(layout):
    _install(layout, "0.2.0")
    assert layout.switch("0.2.0") is None
    assert layout.current() == "0.2.0"
    assert layout.previous() is None
    assert (layout.current_link / "app.txt").read_text() == "0.2.0"


def test_switch_keeps_the_old_one_as_previous(layout):
    _install(layout, "0.2.0")
    layout.switch("0.2.0")
    _install(layout, "0.3.0")
    assert layout.switch("0.3.0") == "0.2.0"
    assert (layout.current(), layout.previous()) == ("0.3.0", "0.2.0")


def test_switch_to_current_changes_nothing(layout):
    _install(layout, "0.2.0")
    layout.switch("0.2.0")
    _install(layout, "0.3.0")
    layout.switch("0.3.0")
    layout.switch("0.3.0")
    assert layout.previous() == "0.2.0"


def test_links_are_relative(layout):
    """The tree still works mounted elsewhere (an image being built)."""
    _install(layout, "0.2.0")
    layout.switch("0.2.0")
    assert os.readlink(layout.current_link) == "releases/0.2.0"


def test_no_temporary_link_left_behind(layout):
    _install(layout, "0.2.0")
    layout.switch("0.2.0")
    assert sorted(p.name for p in layout.base.iterdir()) == ["current", "releases"]


def test_rollback_swaps_current_and_previous(layout):
    for label in ("0.2.0", "0.3.0"):
        _install(layout, label)
        layout.switch(label)
    assert layout.rollback() == "0.2.0"
    assert (layout.current(), layout.previous()) == ("0.2.0", "0.3.0")


def test_rollback_without_previous_fails(layout):
    _install(layout, "0.2.0")
    layout.switch("0.2.0")
    with pytest.raises(ReleaseError):
        layout.rollback()


def test_begin_refuses_to_overwrite_a_finished_release(layout):
    _install(layout, "0.2.0")
    with pytest.raises(ReleaseError):
        layout.begin("0.2.0")


def test_begin_replaces_a_leftover_unfinished_build(layout):
    path = layout.begin("0.2.0")
    (path / "half.txt").write_text("power cut here")
    path = layout.begin("0.2.0")
    assert not (path / "half.txt").exists()


@pytest.mark.parametrize("label", ["", ".", "..", "../x", "a/b", ".hidden"])
def test_odd_names_are_refused(layout, label):
    with pytest.raises(ReleaseError):
        layout.path(label)


def test_labels_oldest_first_by_version_not_by_time(layout):
    # 0.10.0 finished "later" on a clock that was wrong (a new card's clock
    # is the image's build date): the version still decides.
    for label, stamp in (("0.10.0", 1000), ("0.9.0", 2000), ("0.9.0+gabc1234", 3000)):
        os.utime(_install(layout, label), (stamp, stamp))
    assert layout.labels() == ["0.9.0", "0.9.0+gabc1234", "0.10.0"]


def test_labels_that_are_not_versions_come_first_by_time(layout):
    for label, stamp in (("0.1.0", 1000), ("test-b", 3000), ("test-a", 2000)):
        os.utime(_install(layout, label), (stamp, stamp))
    assert layout.labels() == ["test-a", "test-b", "0.1.0"]


def test_prune_keeps_current_previous_and_the_newest(layout):
    for i, label in enumerate(("0.1.0", "0.2.0", "0.3.0", "0.4.0")):
        path = _install(layout, label)
        os.utime(path, (1000 + i, 1000 + i))
    layout.switch("0.1.0")   # an old one running, say after a rollback
    layout.switch("0.4.0")
    layout.begin("0.5.0")    # a build cut short
    removed = layout.prune(keep=2)
    assert sorted(removed) == ["0.2.0", "0.5.0"]
    assert layout.labels() == ["0.1.0", "0.3.0", "0.4.0"]


def test_prune_never_removes_current_even_with_keep_zero(layout):
    _install(layout, "0.2.0")
    layout.switch("0.2.0")
    assert layout.prune(keep=0) == []
    assert layout.current() == "0.2.0"


def test_locked_creates_the_base(layout):
    with layout.locked():
        assert layout.base.is_dir()
