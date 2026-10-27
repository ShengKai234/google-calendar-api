"""
Releases side by side, and an atomic switch between them.

    /opt/e-pages/
      releases/0.2.0/        one complete copy of the app, with its .venv
      releases/0.3.0/
      current  -> releases/0.3.0    what the systemd units run
      previous -> releases/0.2.0    what a rollback goes back to
      data/                  this display's files (see config.DATA_DIR)

A release is built in place under releases/ and marked INCOMPLETE until it
is whole, so a power cut mid-build leaves a directory that is skipped and
later removed, never a half-installed app. `current` is moved with
rename(2), which is atomic: at every instant it names one whole release.
Links are relative, so the tree still works mounted somewhere else (an
image being built, a card read on another computer).

Standard library only: it runs under the system python3, before any venv.
"""
import fcntl
import os
import shutil
from contextlib import contextmanager
from pathlib import Path

from gcal_epd.config import RELEASE_MARKER

DEFAULT_BASE = Path("/opt/e-pages")
INCOMPLETE = "INCOMPLETE"


class ReleaseError(RuntimeError):
    """A release is missing, unfinished, or in the way."""


def _valid_label(label: str) -> bool:
    return bool(label) and "/" not in label and label not in (".", "..") \
        and not label.startswith(".")


class ReleaseLayout:
    def __init__(self, base: Path = DEFAULT_BASE):
        self.base = Path(base)
        self.releases = self.base / "releases"
        self.current_link = self.base / "current"
        self.previous_link = self.base / "previous"
        self.data = self.base / "data"

    # --- reading ----------------------------------------------------------

    def path(self, label: str) -> Path:
        if not _valid_label(label):
            raise ReleaseError(f"Not a release name: {label!r}")
        return self.releases / label

    def is_complete(self, label: str) -> bool:
        p = self.path(label)
        return (p / RELEASE_MARKER).is_file() and not (p / INCOMPLETE).exists()

    def labels(self) -> list[str]:
        """Complete releases, oldest first (by when they were finished)."""
        if not self.releases.is_dir():
            return []
        done = [p.name for p in self.releases.iterdir()
                if p.is_dir() and _valid_label(p.name) and self.is_complete(p.name)]
        # Removing INCOMPLETE is the last change to a release's directory.
        return sorted(done, key=lambda n: self.path(n).stat().st_mtime)

    def _target(self, link: Path) -> str | None:
        try:
            target = os.readlink(link)
        except OSError:
            return None
        parent, _, name = target.rpartition("/")
        return name if parent == "releases" and _valid_label(name) else None

    def current(self) -> str | None:
        return self._target(self.current_link)

    def previous(self) -> str | None:
        return self._target(self.previous_link)

    # --- building ---------------------------------------------------------

    @contextmanager
    def locked(self):
        """One installer, switch or prune at a time."""
        self.base.mkdir(parents=True, exist_ok=True)
        with open(self.base / ".lock", "w") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            yield

    def begin(self, label: str) -> Path:
        """An empty directory for `label`, marked INCOMPLETE.

        A leftover unfinished build of the same name is removed first; a
        finished one is never overwritten (it may be the one running).
        """
        p = self.path(label)
        if p.exists():
            if self.is_complete(label):
                raise ReleaseError(f"Release {label} is already installed.")
            shutil.rmtree(p)
        p.mkdir(parents=True)
        (p / INCOMPLETE).touch()
        # Named from the start, so the build can check `--version` itself.
        (p / RELEASE_MARKER).write_text(label + "\n")
        return p

    def finish(self, label: str) -> None:
        """Mark `label` whole: from now on it can be switched to."""
        p = self.path(label)
        os.sync()   # the whole build on the card before it counts as whole
        (p / INCOMPLETE).unlink()
        _fsync_dir(p)

    # --- switching --------------------------------------------------------

    def _point(self, link: Path, label: str) -> None:
        tmp = link.with_name(f".{link.name}.tmp")
        tmp.unlink(missing_ok=True)
        os.symlink(f"releases/{label}", tmp)
        os.replace(tmp, link)   # rename(2): atomic

    def switch(self, label: str) -> str | None:
        """Make `label` current; the one it replaces becomes previous.

        Returns the release that was current before (None on a first install).
        """
        if not self.is_complete(label):
            raise ReleaseError(f"Release {label} is not installed (or not finished).")
        old = self.current()
        if old == label:
            return old
        if old is not None:
            self._point(self.previous_link, old)
        self._point(self.current_link, label)
        _fsync_dir(self.base)
        return old

    def rollback(self) -> str:
        """Go back to the previous release; returns its name."""
        prev = self.previous()
        if prev is None or not self.is_complete(prev):
            raise ReleaseError("There is no previous release to go back to.")
        self.switch(prev)
        return prev

    def prune(self, keep: int = 2) -> list[str]:
        """Remove unfinished builds, and old releases beyond the newest `keep`.

        current and previous are always kept, whatever `keep` says.
        Returns what was removed.
        """
        removed = []
        if not self.releases.is_dir():
            return removed
        for p in self.releases.iterdir():
            if p.is_dir() and _valid_label(p.name) and not self.is_complete(p.name):
                shutil.rmtree(p)
                removed.append(p.name)
        protected = {self.current(), self.previous()}
        done = self.labels()
        for label in done[:max(len(done) - keep, 0)]:
            if label not in protected:
                shutil.rmtree(self.path(label))
                removed.append(label)
        return removed


def _fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
