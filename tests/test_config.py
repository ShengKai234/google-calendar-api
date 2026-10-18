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


def test_feeds_file_uses_first_ics_source():
    cfg = {"sources": [{"type": "open_meteo"}, {"type": "ics", "feeds_file": "mine.toml"}]}
    assert config.feeds_file(cfg) == config.PROJECT_ROOT / "mine.toml"


def test_feeds_file_default():
    assert config.feeds_file({}) == config.PROJECT_ROOT / "ics_feeds.toml"


def test_project_config_loads():
    assert "sources" in config.load_config()


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
