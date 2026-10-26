"""
Build one release from a source: copy the code, make its venv, prove it runs.

Every step happens inside the new release's own directory (marked
INCOMPLETE by the layout), so a failure at any point leaves the running
release untouched.

Standard library only: it runs under the system python3, before any venv.
"""
import io
import logging
import os
import subprocess
import tarfile
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

log = logging.getLogger(__name__)

# The panel driver's packages: only on a Pi (spidev needs Linux headers).
PI_REQUIREMENTS = "requirements-pi.txt"
DEVICE_MODEL = Path("/proc/device-tree/model")
# What must import for the calendar and the Wi-Fi setup to work at all.
SMOKE_IMPORTS = ["gcal_epd.main", "gcal_epd.wifi_setup", "PIL._imagingft", "qrcode"]
PI_SMOKE_IMPORTS = ["spidev", "gpiozero", "lgpio"]

Run = Callable[..., subprocess.CompletedProcess]
# The installer itself runs with PYTHONPATH at the source's src/. Passed on,
# it would make the new release's python import that copy instead of its
# own: install.sh would then ask the wrong copy where the data lives.
FOREIGN_PYTHON_ENV = ("PYTHONPATH", "PYTHONHOME")


class InstallError(RuntimeError):
    """A step of building the release failed; the release is not usable."""


def child_env(extra: dict | None = None) -> dict:
    """This process's environment, minus what points Python at another copy."""
    env = {k: v for k, v in os.environ.items() if k not in FOREIGN_PYTHON_ENV}
    return {**env, **(extra or {})}


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    """subprocess.run that raises InstallError with the command's own output.

    Without an explicit env, the child gets child_env().
    """
    kwargs.setdefault("env", child_env())
    try:
        return subprocess.run(cmd, check=True, capture_output=True, text=True, **kwargs)
    except subprocess.CalledProcessError as e:
        out = (e.stderr or e.stdout or "").strip().splitlines()[-15:]
        raise InstallError(f"{' '.join(cmd[:4])}... failed (exit {e.returncode}):\n"
                           + "\n".join(out)) from None
    except OSError as e:
        raise InstallError(f"{cmd[0]}: {e}") from None


def on_raspberry_pi(model: Path = DEVICE_MODEL) -> bool:
    try:
        return "Raspberry Pi" in model.read_text(errors="replace")
    except OSError:
        return False


# --- Sources: where the code of a release comes from ----------------------

@dataclass(frozen=True)
class Source:
    """A release's code: a git checkout (its HEAD) or a tar file."""
    path: Path

    @property
    def is_git(self) -> bool:
        return self.path.is_dir()

    def label(self, run: Run = run) -> str:
        """The release's name.

        From git: "X.Y.Z" when HEAD is tagged vX.Y.Z (pyproject.toml's
        version), otherwise "X.Y.Z+g<commit>", so two untagged builds of
        the same version never share a name. From a tar file: its RELEASE
        file, or failing that its pyproject.toml version.
        """
        if self.is_git:
            git = ["git", "-C", str(self.path)]
            pyproject = run(git + ["show", "HEAD:pyproject.toml"]).stdout
            version = _project_version(pyproject)
            tags = run(git + ["tag", "--points-at", "HEAD"]).stdout.split()
            if f"v{version}" in tags:
                return version
            commit = run(git + ["rev-parse", "--short=7", "HEAD"]).stdout.strip()
            return f"{version}+g{commit}"
        with tarfile.open(self.path) as tar:
            for name in ("RELEASE", "./RELEASE"):
                try:
                    return tar.extractfile(name).read().decode().strip()
                except (KeyError, AttributeError):
                    pass
            for name in ("pyproject.toml", "./pyproject.toml"):
                try:
                    return _project_version(tar.extractfile(name).read().decode())
                except (KeyError, AttributeError):
                    pass
        raise InstallError(f"{self.path.name} has neither RELEASE nor pyproject.toml.")

    def uncommitted(self, run: Run = run) -> bool:
        """True if a git source has tracked changes that will NOT be installed."""
        if not self.is_git:
            return False
        out = run(["git", "-C", str(self.path), "status", "--porcelain",
                   "--untracked-files=no"]).stdout
        return bool(out.strip())

    def extract(self, dest: Path, run: Run = run) -> None:
        """Copy the code into `dest`.

        From git, only committed, tracked files (`git archive HEAD`): the
        feeds file and other gitignored secrets can never ride along.
        """
        if self.is_git:
            data = subprocess.run(["git", "-C", str(self.path), "archive", "HEAD"],
                                  check=True, capture_output=True).stdout
            _safe_extract(tarfile.open(fileobj=io.BytesIO(data)), dest)
        else:
            with tarfile.open(self.path) as tar:
                _safe_extract(tar, dest)


def _project_version(pyproject_text: str) -> str:
    try:
        return str(tomllib.loads(pyproject_text)["project"]["version"])
    except (KeyError, tomllib.TOMLDecodeError) as e:
        raise InstallError(f"pyproject.toml has no [project] version: {e}") from None


def _safe_extract(tar: tarfile.TarFile, dest: Path) -> None:
    """Extract regular files and directories only, and only below `dest`."""
    dest = dest.resolve()
    members = []
    for m in tar.getmembers():
        target = (dest / m.name).resolve()
        if target != dest and dest not in target.parents:
            raise InstallError(f"Refusing {m.name!r}: it points outside the release.")
        if m.issym() or m.islnk():
            link = (target.parent / m.linkname).resolve()
            if link != dest and dest not in link.parents:
                raise InstallError(f"Refusing link {m.name!r} -> {m.linkname!r}.")
        elif not (m.isfile() or m.isdir()):
            raise InstallError(f"Refusing {m.name!r}: not a file or directory.")
        m.uid = m.gid = 0
        m.uname = m.gname = "root"
        members.append(m)
    if hasattr(tarfile, "data_filter"):   # Python 3.12+, and 3.11.4+
        tar.extractall(dest, members=members, filter="data")
    else:
        tar.extractall(dest, members=members)


# --- Building -------------------------------------------------------------

def build_venv(release: Path, wheels: Path | None, on_pi: bool, run: Run = run,
               python: str = "python3") -> None:
    """The release's own .venv: pinned requirements, then the app (editable,
    so PROJECT_ROOT stays the release directory with its fonts and vendor/).

    With `wheels`, nothing is downloaded: every package must be there.
    """
    venv = release / ".venv"
    run([python, "-m", "venv", str(venv)])
    pip = [str(venv / "bin" / "python"), "-m", "pip", "install",
           "--disable-pip-version-check", "--no-input", "--quiet"]
    if wheels is not None:
        pip += ["--no-index", "--find-links", str(wheels)]
    reqs = ["-r", str(release / "requirements.txt")]
    if on_pi and (release / PI_REQUIREMENTS).is_file():
        reqs += ["-r", str(release / PI_REQUIREMENTS)]
    log.info("Installing packages%s...", " from the bundled wheels" if wheels else "")
    run(pip + reqs)
    run(pip + ["--no-deps", "-e", str(release)])
    # The release is read-only to the app's user: compile now, not at every start.
    run([str(venv / "bin" / "python"), "-m", "compileall", "-q",
         str(release / "src"), str(release / "vendor")])


def smoke_test(release: Path, label: str, data: Path, on_pi: bool, run: Run = run) -> None:
    """The new release imports and names itself; nothing touches the panel."""
    python = str(release / ".venv" / "bin" / "python")
    env = {"EPD_DATA_DIR": str(data), "PATH": "/usr/bin:/bin"}
    imports = SMOKE_IMPORTS + (PI_SMOKE_IMPORTS if on_pi else [])
    run([python, "-c", "import " + ", ".join(imports)], cwd=release, env=env)
    out = run([python, "-m", "gcal_epd.main", "--version"], cwd=release, env=env).stdout
    if out.strip() != f"gcal-epd {label}":
        raise InstallError(f"The new release reports {out.strip()!r}, not {label}.")
