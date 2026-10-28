"""Choosing, fetching and checking a release from GitHub."""
import hashlib
import io
import json
import shutil
import subprocess
import tarfile

import pytest

from gcal_epd.infrastructure.release import updater
from gcal_epd.infrastructure.release.installer import InstallError
from gcal_epd.infrastructure.release.versions import version_key

needs_ssh_keygen = pytest.mark.skipif(not shutil.which("ssh-keygen"), reason="needs ssh-keygen")


# --- versions ------------------------------------------------------------------

def test_versions_compare_as_numbers():
    assert version_key("0.10.0") > version_key("0.9.9")
    assert version_key("1.0.0") > version_key("0.99.0")


def test_a_local_build_sits_between_its_version_and_the_next():
    assert version_key("0.2.0") < version_key("0.2.0+gabc1234") < version_key("0.2.1")


@pytest.mark.parametrize("label", ["", "v0.2.0", "0.2", "0.2.0-rc1", "latest", "0.2.0+"])
def test_other_names_are_not_versions(label):
    assert version_key(label) is None


# --- settings and state ------------------------------------------------------------

def test_settings_default_to_stable_updates():
    s = updater.Settings.from_config({})
    assert (s.enabled, s.channel, s.repo) == (True, "stable", updater.DEFAULT_REPO)


def test_settings_from_update_table():
    s = updater.Settings.from_config({"update": {"channel": "beta", "enabled": False}})
    assert (s.enabled, s.channel) == (False, "beta")


@pytest.mark.parametrize("table", [{"channel": "nightly"}, {"repo": "not a repo"}])
def test_bad_settings_are_refused(table):
    with pytest.raises(InstallError):
        updater.Settings.from_config({"update": table})


def test_state_round_trips_and_survives_a_bad_file(tmp_path):
    assert updater.State.load(tmp_path) == updater.State()
    state = updater.State(rejected=["0.3.0"], last_check=5.0, last_result="x")
    state.save(tmp_path)
    assert updater.State.load(tmp_path) == state
    (tmp_path / updater.STATE_FILE).write_text("{not json")
    assert updater.State.load(tmp_path) == updater.State()


def test_recently_updated(tmp_path):
    updater.State(updated_at=1000.0).save(tmp_path)
    assert updater.recently_updated(tmp_path, 600, now=lambda: 1500.0)
    assert not updater.recently_updated(tmp_path, 600, now=lambda: 1700.0)
    assert not updater.recently_updated(tmp_path / "none", 600)


# --- picking ------------------------------------------------------------------------

def _release(label, prerelease=False, draft=False, assets=None):
    names = updater.Names(label)
    if assets is None:
        assets = [names.app, names.wheels, updater.SUMS, updater.SIGNATURE]
    return {"tag_name": f"v{label}", "prerelease": prerelease, "draft": draft,
            "assets": [{"name": a, "browser_download_url": f"https://dl/{label}/{a}"}
                       for a in assets]}


RELEASES = [_release("0.2.0"), _release("0.3.0"), _release("0.4.0", prerelease=True),
            _release("0.5.0", draft=True)]


def test_stable_takes_the_newest_full_release():
    assert updater.pick(RELEASES, "stable", "0.2.0", []).label == "0.3.0"


def test_beta_takes_pre_releases_too():
    cand = updater.pick(RELEASES, "beta", "0.2.0", [])
    assert (cand.label, cand.prerelease) == ("0.4.0", True)


def test_nothing_newer_means_none():
    assert updater.pick(RELEASES, "stable", "0.3.0", []) is None


def test_never_goes_back_to_an_older_release():
    assert updater.pick([_release("0.2.0")], "stable", "0.3.0", []) is None


def test_a_local_build_takes_the_next_release_not_its_own_version():
    assert updater.pick([_release("0.2.0")], "stable", "0.2.0+gabc1234", []) is None
    assert updater.pick([_release("0.2.1")], "stable", "0.2.0+gabc1234", []).label == "0.2.1"


def test_rejected_release_is_skipped():
    assert updater.pick(RELEASES, "stable", "0.2.0", ["0.3.0"]) is None


def test_unsigned_release_waits_until_signed():
    names = updater.Names("0.3.0")
    unsigned = _release("0.3.0", assets=[names.app, names.wheels, updater.SUMS])
    assert updater.pick([unsigned], "stable", "0.2.0", []) is None


def test_odd_tags_are_ignored():
    odd = _release("0.9.0")
    odd["tag_name"] = "nightly"
    assert updater.pick([odd], "beta", "0.2.0", []) is None


# --- listing --------------------------------------------------------------------------

def test_list_releases_asks_the_repos_api():
    urls = []
    data = updater.list_releases("o/r", fetch=lambda u: urls.append(u) or b"[]")
    assert data == [] and urls == ["https://api.github.com/repos/o/r/releases?per_page=30"]


@pytest.mark.parametrize("answer", [b"{}", b"<html>"])
def test_odd_api_answer_is_an_install_error(answer):
    with pytest.raises(InstallError):
        updater.list_releases("o/r", fetch=lambda u: answer)


def test_network_failure_is_an_install_error():
    def down(url):
        raise OSError("Network is unreachable")
    with pytest.raises(InstallError, match="unreachable"):
        updater.list_releases("o/r", fetch=down)


# --- fetching a release, with real signatures -------------------------------------------

def _keygen(path):
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(path)], check=True)
    return path


def _signers(path, *keys):
    path.write_text("".join(f'{updater.NAMESPACE} namespaces="{updater.NAMESPACE}" '
                            f'{(k.parent / (k.name + ".pub")).read_text()}' for k in keys))
    return path


def _tar(files: dict, gz: bool) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz" if gz else "w") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def make_release(tmp_path, label, key, tamper=None):
    """A published release as bytes by URL, signed with `key`."""
    names = updater.Names(label)
    files = {
        names.app: _tar({"RELEASE": f"{label}\n".encode(), "config.toml": b""}, gz=True),
        names.wheels: _tar({"wheels/a-1-py3-none-any.whl": b"w"}, gz=False),
    }
    sums = "".join(f"{hashlib.sha256(d).hexdigest()}  {n}\n" for n, d in files.items())
    sums_path = tmp_path / f"sums-{label}"
    sums_path.write_text(sums)
    subprocess.run(["ssh-keygen", "-Y", "sign", "-q", "-f", str(key), "-n", updater.NAMESPACE,
                    str(sums_path)], check=True, capture_output=True)
    files[updater.SUMS] = sums.encode()
    files[updater.SIGNATURE] = (tmp_path / f"sums-{label}.sig").read_bytes()
    if tamper:
        files[tamper] = files[tamper] + b"x"
    return {f"https://dl/{label}/{n}": d for n, d in files.items()}


def fakes(blobs):
    def fetch(url):
        return blobs[url]

    def download(url, dest, limit):
        dest.write_bytes(blobs[url])
    return fetch, download


@needs_ssh_keygen
def test_a_signed_release_is_fetched_and_checked(tmp_path):
    key = _keygen(tmp_path / "k")
    signers = _signers(tmp_path / "allowed", key)
    fetch, download = fakes(make_release(tmp_path, "0.3.0", key))
    cand = updater.pick([_release("0.3.0")], "stable", "0.2.0", [])
    dest = tmp_path / "dl"
    dest.mkdir()
    app, wheels = updater.fetch_release(cand, dest, signers, fetch, download)
    assert app.name == "e-pages-0.3.0.tar.gz"
    assert [w.name for w in wheels.iterdir()] == ["a-1-py3-none-any.whl"]


@needs_ssh_keygen
def test_a_release_signed_by_another_key_is_refused(tmp_path):
    trusted, stranger = _keygen(tmp_path / "k"), _keygen(tmp_path / "s")
    signers = _signers(tmp_path / "allowed", trusted)
    fetch, download = fakes(make_release(tmp_path, "0.3.0", stranger))
    cand = updater.pick([_release("0.3.0")], "stable", "0.2.0", [])
    (tmp_path / "dl").mkdir()
    with pytest.raises(InstallError, match="NOT signed"):
        updater.fetch_release(cand, tmp_path / "dl", signers, fetch, download)


@needs_ssh_keygen
@pytest.mark.parametrize("tampered", ["app", "sums"])
def test_a_changed_file_is_refused(tmp_path, tampered):
    key = _keygen(tmp_path / "k")
    signers = _signers(tmp_path / "allowed", key)
    names = updater.Names("0.3.0")
    target = names.app if tampered == "app" else updater.SUMS
    fetch, download = fakes(make_release(tmp_path, "0.3.0", key, tamper=target))
    cand = updater.pick([_release("0.3.0")], "stable", "0.2.0", [])
    (tmp_path / "dl").mkdir()
    with pytest.raises(InstallError, match="does not match|NOT signed"):
        updater.fetch_release(cand, tmp_path / "dl", signers, fetch, download)


def test_no_trusted_key_means_no_update(tmp_path):
    signers = tmp_path / "allowed"
    signers.write_text("# no keys yet\n")
    with pytest.raises(InstallError, match="lists no key"):
        updater.verify_signature(b"x", tmp_path / "sig", signers)


def test_parse_sums_ignores_other_lines():
    sums = updater.parse_sums(f"{'a' * 64}  one\nnoise\n{'b' * 64}  two\n")
    assert sums == {"one": "a" * 64, "two": "b" * 64}


def test_download_refuses_an_oversized_file(tmp_path, monkeypatch):
    class Body(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
    monkeypatch.setattr(updater.urllib.request, "urlopen",
                        lambda req, timeout: Body(b"x" * 100))
    with pytest.raises(InstallError, match="larger"):
        updater.download("https://dl/x", tmp_path / "x", limit=10)
    updater.download("https://dl/x", tmp_path / "y", limit=1000)
    assert (tmp_path / "y").read_bytes() == b"x" * 100


def test_json_state_file_is_readable_by_people(tmp_path):
    updater.State(rejected=["0.3.0"]).save(tmp_path)
    assert json.loads((tmp_path / updater.STATE_FILE).read_text())["rejected"] == ["0.3.0"]
