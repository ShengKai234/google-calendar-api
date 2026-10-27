"""Which version is running: the release label, else pyproject.toml's."""
import subprocess
import sys
from pathlib import Path

from gcal_epd import version as v

ROOT = Path(__file__).parent.parent


def test_checkout_reports_the_project_version():
    assert v.version(ROOT) == v.project_version(ROOT) != v.UNKNOWN


def test_release_label_wins(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "0.2.0"\n')
    (tmp_path / "RELEASE").write_text("0.2.0+g1a2b3c4\n")
    assert v.version(tmp_path) == "0.2.0+g1a2b3c4"


def test_empty_release_file_falls_back(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "0.2.0"\n')
    (tmp_path / "RELEASE").write_text("\n")
    assert v.version(tmp_path) == "0.2.0"


def test_nothing_to_read_is_unknown(tmp_path):
    assert v.version(tmp_path) == v.UNKNOWN
    (tmp_path / "pyproject.toml").write_text("not toml [")
    assert v.version(tmp_path) == v.UNKNOWN


def test_main_prints_its_version():
    out = subprocess.run([sys.executable, "-m", "gcal_epd.main", "--version"],
                         capture_output=True, text=True, check=True,
                         env={"PYTHONPATH": str(ROOT / "src")}).stdout
    assert out.strip() == f"gcal-epd {v.version(ROOT)}"
