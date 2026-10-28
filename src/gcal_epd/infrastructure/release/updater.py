"""
Find, fetch and verify a newer release from GitHub, on the Pi.

The steps `python3 -m gcal_epd.releases update` strings together:

1. list the repository's releases (GitHub API, no token: it is public);
2. pick the newest one this display's channel takes that is newer than
   the running release and not rejected before;
3. fetch its SHA256SUMS and SHA256SUMS.sig, and check the signature with
   the allowed_signers of the release that is RUNNING, never the one
   being fetched (a forged release would vouch for itself);
4. fetch the code and wheels tars, each checked against SHA256SUMS.

Installing, checking health and rolling back are in releases.py. Nothing
here trusts a file before its checksum and signature have been checked.
Standard library only: it runs under the system python3, not a venv.
"""
import hashlib
import json
import logging
import re
import shutil
import tarfile
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from gcal_epd.infrastructure.release.artifacts import SUMS, Names
from gcal_epd.infrastructure.release.installer import InstallError, Run, _safe_extract
from gcal_epd.infrastructure.release.installer import run as default_run
from gcal_epd.infrastructure.release.versions import version_key

log = logging.getLogger(__name__)

DEFAULT_REPO = "ShengKai234/google-calendar-api"
CHANNELS = ("stable", "beta")
SIGNERS = Path("deploy/release/allowed_signers")
NAMESPACE = "e-pages-release"
STATE_FILE = "update-state.json"
SIGNATURE = f"{SUMS}.sig"
# Downloads are a few tens of MB and the new venv about 100 MB: ask for room.
MIN_FREE_BYTES = 400 * 1024 * 1024
MAX_ASSET_BYTES = 200 * 1024 * 1024
USER_AGENT = "e-pages-updater"

Fetch = Callable[[str], bytes]
Download = Callable[[str, Path, int], None]


# --- settings and state ---------------------------------------------------------

@dataclass(frozen=True)
class Settings:
    """config.toml's [update] table, with config.local.toml on top."""
    enabled: bool = True
    channel: str = "stable"
    repo: str = DEFAULT_REPO

    @classmethod
    def from_config(cls, config: dict) -> "Settings":
        table = config.get("update", {})
        s = cls(enabled=bool(table.get("enabled", True)),
                channel=str(table.get("channel", "stable")),
                repo=str(table.get("repo", DEFAULT_REPO)))
        if s.channel not in CHANNELS:
            raise InstallError(f"[update] channel is {s.channel!r}; use one of "
                               f"{', '.join(CHANNELS)}.")
        if not re.fullmatch(r"[\w.-]+/[\w.-]+", s.repo):
            raise InstallError(f"[update] repo {s.repo!r} is not OWNER/NAME.")
        return s


@dataclass
class State:
    """What the updater remembers, in data/update-state.json."""
    rejected: list[str] = field(default_factory=list)   # never tried again
    attempts: dict = field(default_factory=dict)        # label -> failed builds so far
    last_check: float = 0.0
    last_result: str = ""
    updated_at: float = 0.0       # when the running release was switched to
    updated_to: str = ""

    @classmethod
    def load(cls, data: Path) -> "State":
        try:
            raw = json.loads((data / STATE_FILE).read_text())
        except (OSError, ValueError):
            return cls()
        known = {k: raw[k] for k in cls.__dataclass_fields__ if k in raw}
        return cls(**known)

    def save(self, data: Path) -> None:
        tmp = data / f".{STATE_FILE}.tmp"
        tmp.write_text(json.dumps(self.__dict__, indent=2) + "\n")
        tmp.replace(data / STATE_FILE)


def recently_updated(data: Path, seconds: float, now: Callable[[], float] = time.time) -> bool:
    """True for `seconds` after an update: e.g. a power manager stays on
    meanwhile, so a bad release can still be noticed and rolled back."""
    state = State.load(data)
    return bool(state.updated_at) and now() - state.updated_at < seconds


# --- choosing a release -----------------------------------------------------------

@dataclass(frozen=True)
class Candidate:
    label: str
    tag: str
    prerelease: bool
    urls: dict        # asset name -> download URL

    @property
    def names(self) -> Names:
        return Names(self.label)


def pick(releases: list[dict], channel: str, current: str | None,
         rejected: list[str]) -> Candidate | None:
    """The newest release for `channel` that is newer than `current`.

    stable takes full releases only; beta takes pre-releases too. A release
    must carry the four files a display needs (an unsigned one is skipped
    until it is signed), be tagged vX.Y.Z and not have failed here before.
    """
    floor = version_key(current) if current else None
    best, best_key = None, None
    for r in releases:
        if r.get("draft") or (r.get("prerelease") and channel != "beta"):
            continue
        tag = str(r.get("tag_name", ""))
        label = tag[1:] if tag.startswith("v") else ""
        key = version_key(label)
        if key is None or key[3] or label in rejected:   # tags carry no +local
            continue
        if floor is not None and key <= floor:
            continue
        urls = {a.get("name"): a.get("browser_download_url") for a in r.get("assets", [])}
        names = Names(label)
        if not all(urls.get(n) for n in (names.app, names.wheels, SUMS, SIGNATURE)):
            continue
        if best_key is None or key > best_key:
            best, best_key = Candidate(label, tag, bool(r.get("prerelease")), urls), key
    return best


# --- the network -------------------------------------------------------------------

def _request(url: str) -> urllib.request.Request:
    return urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"})


def fetch(url: str) -> bytes:
    with urllib.request.urlopen(_request(url), timeout=60) as r:
        return r.read(MAX_ASSET_BYTES + 1)


def download(url: str, dest: Path, limit: int = MAX_ASSET_BYTES) -> None:
    """Stream `url` into `dest`, refusing anything larger than `limit`."""
    done = 0
    with urllib.request.urlopen(_request(url), timeout=60) as r, open(dest, "wb") as f:
        for block in iter(lambda: r.read(1 << 16), b""):
            done += len(block)
            if done > limit:
                raise InstallError(f"{dest.name} is larger than {limit // 2**20} MB.")
            f.write(block)


def list_releases(repo: str, fetch: Fetch = fetch) -> list[dict]:
    try:
        data = json.loads(fetch(f"https://api.github.com/repos/{repo}/releases?per_page=30"))
    except (OSError, ValueError) as e:
        raise InstallError(f"Could not list the releases of {repo}: {e}") from None
    if not isinstance(data, list):
        raise InstallError(f"Unexpected answer listing the releases of {repo}.")
    return data


# --- checking -------------------------------------------------------------------------

def parse_sums(text: str) -> dict[str, str]:
    sums = {}
    for line in text.splitlines():
        m = re.fullmatch(r"([0-9a-f]{64})  (\S+)", line.strip())
        if m:
            sums[m.group(2)] = m.group(1)
    return sums


def verify_signature(sums: bytes, signature: Path, signers: Path, run: Run = default_run) -> None:
    """SHA256SUMS must be signed by a key the running release trusts."""
    if not signers.is_file() or not any(
            l.strip() and not l.startswith("#") for l in signers.read_text().splitlines()):
        raise InstallError(f"{signers} lists no key: cannot check any release.")
    try:
        run(["ssh-keygen", "-Y", "verify", "-f", str(signers), "-I", NAMESPACE,
             "-n", NAMESPACE, "-s", str(signature)], input=sums.decode())
    except InstallError:
        raise InstallError(f"{SUMS} is NOT signed by a key in {signers}.") from None


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def fetch_release(cand: Candidate, dest: Path, signers: Path, fetch: Fetch = fetch,
                  download: Download = download, run: Run = default_run) -> tuple[Path, Path]:
    """Fetch and check `cand` into `dest`; returns (code tar, wheels dir)."""
    sums_bytes = fetch(cand.urls[SUMS])
    sig = dest / SIGNATURE
    sig.write_bytes(fetch(cand.urls[SIGNATURE]))
    verify_signature(sums_bytes, sig, signers, run)
    sums = parse_sums(sums_bytes.decode())
    names = cand.names
    paths = {}
    for name in (names.app, names.wheels):
        if name not in sums:
            raise InstallError(f"{SUMS} of {cand.tag} does not list {name}.")
        path = dest / name
        log.info("Downloading %s...", name)
        download(cand.urls[name], path, MAX_ASSET_BYTES)
        if _sha256(path) != sums[name]:
            raise InstallError(f"{name} does not match {SUMS}: not installing {cand.tag}.")
        paths[name] = path
    wheels = dest / "wheels-tar"
    wheels.mkdir()
    with tarfile.open(paths[names.wheels]) as tar:
        _safe_extract(tar, wheels)
    if not (wheels / "wheels").is_dir():
        raise InstallError(f"{names.wheels} has no wheels/ folder.")
    return paths[names.app], wheels / "wheels"


def enough_room(base: Path, need: int = MIN_FREE_BYTES) -> bool:
    return shutil.disk_usage(base).free >= need
