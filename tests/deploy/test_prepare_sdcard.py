"""deploy/sdcard/prepare.sh on a fake boot partition, as Imager leaves it."""
import shutil
import subprocess
import zipfile

import pytest

from gcal_epd.config import PROJECT_ROOT

SCRIPT = PROJECT_ROOT / "deploy" / "sdcard" / "prepare.sh"
FIRSTBOOT_ITEM = "  - [ env, EPD_USER=admin, bash, /boot/firmware/epd-bundle/firstboot.sh ]"
pytestmark = pytest.mark.skipif(not shutil.which("unzip"), reason="needs unzip")

IMAGER_USER_DATA = """#cloud-config
hostname: epaper
user:
  name: admin
  shell: /bin/bash
  sudo: null
ssh_pwauth: false
runcmd:
  - [ systemctl, enable, --now, ssh ]
  - [ rfkill, unblock, wifi ]
"""


@pytest.fixture
def card(tmp_path):
    boot = tmp_path / "bootfs"
    boot.mkdir()
    (boot / "config.txt").write_text("#dtparam=i2c_arm=on\n#dtparam=spi=on\n[all]\n")
    (boot / "cmdline.txt").write_text("console=tty1 root=PARTUUID=x rootwait\n")
    (boot / "user-data").write_text(IMAGER_USER_DATA)
    return boot


@pytest.fixture
def bundle(tmp_path):
    path = tmp_path / "e-pages-0.2.0-sdcard.zip"
    with zipfile.ZipFile(path, "w") as z:
        for name in ("app.tar.gz", "firstboot.sh", "wheels/a.whl", "debs/b.deb"):
            z.writestr(f"epd-bundle/{name}", "x")
    return path


def prepare(card, bundle, *extra):
    return subprocess.run(["bash", str(SCRIPT), "--boot", str(card), "--bundle", str(bundle),
                           *extra], capture_output=True, text=True)


def test_fresh_card_gets_bundle_spi_country_and_first_boot(card, bundle):
    result = prepare(card, bundle, "--country", "JP")
    assert result.returncode == 0, result.stderr
    assert (card / "epd-bundle" / "wheels" / "a.whl").is_file()
    assert "\ndtparam=spi=on\n" in (card / "config.txt").read_text()
    assert (card / "cmdline.txt").read_text() == \
        "console=tty1 root=PARTUUID=x rootwait cfg80211.ieee80211_regdom=JP\n"
    user_data = (card / "user-data").read_text()
    # Imager's own commands stay first; ours is last in the same list.
    assert user_data.index("rfkill") < user_data.index(FIRSTBOOT_ITEM)
    assert "power_state:\n  mode: reboot\n  condition: test -f /var/lib/epd-firstboot.done" \
        in user_data


def test_running_twice_adds_nothing_twice(card, bundle):
    prepare(card, bundle)
    first = {f: (card / f).read_text() for f in ("config.txt", "cmdline.txt", "user-data")}
    assert prepare(card, bundle).returncode == 0
    assert {f: (card / f).read_text() for f in first} == first


def test_user_data_without_runcmd_gets_one(card, bundle):
    (card / "user-data").write_text("#cloud-config\nuser:\n  name: admin\n")
    assert prepare(card, bundle).returncode == 0
    assert f"runcmd:\n  # e-Paper" in (card / "user-data").read_text()
    assert FIRSTBOOT_ITEM in (card / "user-data").read_text()


def test_runcmd_followed_by_another_key_keeps_the_item_in_the_list(card, bundle):
    (card / "user-data").write_text(
        "#cloud-config\nuser:\n  name: admin\nruncmd:\n- [ a ]\ntimezone: Asia/Taipei\n")
    assert prepare(card, bundle).returncode == 0
    text = (card / "user-data").read_text()
    item = "- [ env, EPD_USER=admin, bash, /boot/firmware/epd-bundle/firstboot.sh ]"
    assert text.index("- [ a ]") < text.index(item) < text.index("timezone:")


def test_card_that_booted_is_refused(card, bundle):
    (card / "epd-firstboot.log").write_text("")
    result = prepare(card, bundle)
    assert result.returncode != 0 and "booted before" in result.stderr


def test_card_without_a_user_is_refused(card, bundle):
    (card / "user-data").write_text("#cloud-config\nhostname: epaper\n")
    result = prepare(card, bundle)
    assert result.returncode != 0 and "username" in result.stderr


def test_inline_runcmd_is_left_for_a_person(card, bundle):
    (card / "user-data").write_text("#cloud-config\nuser:\n  name: a\nruncmd: [ [ ls ] ]\n")
    result = prepare(card, bundle)
    assert result.returncode != 0 and "by hand" in result.stderr
    assert "firstboot" not in (card / "user-data").read_text()


def test_not_a_bundle_is_refused(card, tmp_path):
    other = tmp_path / "other.zip"
    with zipfile.ZipFile(other, "w") as z:
        z.writestr("readme.txt", "x")
    result = prepare(card, other)
    assert result.returncode != 0 and "epd-bundle" in result.stderr
