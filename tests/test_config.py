"""Tests for the shared config helpers."""
import subprocess
import sys
from pathlib import Path

from gcal_epd import config


def test_resolve_relative_is_taken_from_root(tmp_path):
    assert config.resolve("assets/f.otf", tmp_path) == str(tmp_path / "assets/f.otf")


def test_resolve_keeps_absolute_paths(tmp_path):
    assert config.resolve("/usr/share/fonts/x.ttf", tmp_path) == "/usr/share/fonts/x.ttf"


def test_resolve_empty_stays_empty(tmp_path):
    """draw.py falls back to system fonts only when it is handed ""."""
    assert config.resolve("", tmp_path) == ""


def test_font_path_from_display_section(tmp_path):
    cfg = {"display": {"font_path": "assets/fonts/x.otf"}}
    assert config.font_path(cfg, tmp_path) == str(tmp_path / "assets/fonts/x.otf")
    assert config.font_path({}, tmp_path) == ""


def test_feeds_file_uses_first_ics_source(tmp_path):
    cfg = {"sources": [{"type": "open_meteo"}, {"type": "ics", "feeds_file": "mine.toml"}]}
    assert config.feeds_file(cfg, tmp_path) == tmp_path / "mine.toml"


def test_feeds_file_default(tmp_path):
    assert config.feeds_file({}, tmp_path) == tmp_path / "ics_feeds.toml"


def test_feeds_file_lives_in_the_data_dir():
    assert config.feeds_file({}) == config.DATA_DIR / "ics_feeds.toml"


def test_output_path_lives_in_the_data_dir(tmp_path):
    assert config.output_path({}, tmp_path) == str(tmp_path / "preview.png")
    cfg = {"display": {"output_path": "out/p.png"}}
    assert config.output_path(cfg, tmp_path) == str(tmp_path / "out/p.png")


def test_project_config_loads():
    assert "sources" in config.load_config()


# --- Data directory: the code and this display's files kept apart ---------

def test_checkout_keeps_its_data_in_itself(tmp_path):
    assert config.data_dir(tmp_path, env={}) == tmp_path


def test_installed_release_keeps_data_next_to_the_releases(tmp_path):
    release = tmp_path / "releases" / "0.2.0"
    release.mkdir(parents=True)
    (release / "RELEASE").write_text("0.2.0\n")
    assert config.data_dir(release, env={}) == tmp_path / "data"


def test_releases_dir_without_marker_is_still_a_checkout(tmp_path):
    """A checkout that happens to sit in a folder named "releases"."""
    checkout = tmp_path / "releases" / "google-calendar-api"
    checkout.mkdir(parents=True)
    assert config.data_dir(checkout, env={}) == checkout


def test_env_overrides_the_data_dir(tmp_path):
    release = tmp_path / "releases" / "0.2.0"
    release.mkdir(parents=True)
    (release / "RELEASE").write_text("0.2.0\n")
    env = {"EPD_DATA_DIR": str(tmp_path / "elsewhere")}
    assert config.data_dir(release, env=env) == tmp_path / "elsewhere"


def test_this_checkout_is_its_own_data_dir(monkeypatch):
    if "EPD_DATA_DIR" in __import__("os").environ:
        return
    assert config.DATA_DIR == config.PROJECT_ROOT


# --- config.local.toml: this display's settings on top of the shipped ones --

def test_no_local_config_gives_the_shipped_one(tmp_path):
    assert config.load_config(data=tmp_path) == config.load_config(data=tmp_path / "none")


def test_local_config_overrides_and_keeps_the_rest(tmp_path):
    (tmp_path / "config.local.toml").write_text(
        '[display]\noutput_path = "here.png"\n')
    shipped = config.load_config(data=tmp_path / "none")
    merged = config.load_config(data=tmp_path)
    assert merged["display"]["output_path"] == "here.png"
    assert merged["display"]["font_path"] == shipped["display"]["font_path"]
    assert merged["sources"] == shipped["sources"]


def test_local_list_replaces_the_shipped_list(tmp_path):
    """[[sources]] is a list: a local one replaces it whole (another city)."""
    (tmp_path / "config.local.toml").write_text(
        '[[sources]]\ntype = "open_meteo"\nlatitude = 35.68\nlongitude = 139.69\n'
        'location = "Tokyo"\n')
    merged = config.load_config(data=tmp_path)
    assert merged["sources"] == [{"type": "open_meteo", "latitude": 35.68,
                                  "longitude": 139.69, "location": "Tokyo"}]


def test_merge_is_recursive_and_leaves_inputs_alone():
    base = {"a": {"b": 1, "c": {"d": 2}}, "e": [1]}
    over = {"a": {"c": {"d": 3}}, "e": [2], "f": 4}
    assert config._merge(base, over) == {"a": {"b": 1, "c": {"d": 3}}, "e": [2], "f": 4}
    assert base == {"a": {"b": 1, "c": {"d": 2}}, "e": [1]}


def test_wifi_setup_does_not_import_main():
    """Entry points must not depend on each other; settings come from config."""
    # display=True runs the panel path, where settings are read; with no panel
    # attached the push itself fails and is swallowed, which is fine here.
    code = ("import sys, gcal_epd.wifi_setup as w; "
            "w._make_push(True)('ap', ap_ssid='S', ap_password='abcdefgh23', "
            "url='http://10.42.0.1'); print('gcal_epd.main' in sys.modules)")
    src = Path(__file__).parent.parent / "src"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         env={"PYTHONPATH": str(src)}, check=True).stdout.strip()
    assert out == "False"


def test_importing_entry_points_leaves_logging_alone():
    """basicConfig belongs in main(), not at import: importers keep their logging."""
    code = ("import logging, gcal_epd.main, gcal_epd.wifi_setup; "
            "print(len(logging.getLogger().handlers))")
    src = Path(__file__).parent.parent / "src"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         env={"PYTHONPATH": str(src)}, check=True).stdout.strip()
    assert out == "0"


def test_wifi_setup_never_refers_to_main():
    """Covers every path, including _stash_feeds, which once imported main."""
    src = Path(__file__).parent.parent / "src" / "gcal_epd" / "wifi_setup.py"
    assert "gcal_epd.main" not in src.read_text()
