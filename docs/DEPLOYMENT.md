# Deployment

> Language: **English** · [繁體中文](DEPLOYMENT.zh-TW.md)

How the calendar gets onto a Raspberry Pi and how it is updated: building a
release, publishing it, preparing a new SD card, and installing a release
on a running display. Written to be followed step by step, by a person or
by an AI agent working in this repository.

---

## The pieces

| Piece | Where | Runs on |
|---|---|---|
| Release build | `python -m gcal_epd.build_release` (`src/gcal_epd/build_release.py`, `infrastructure/release/artifacts.py`) | Mac or CI |
| Release workflow | `.github/workflows/release.yml`, on a `vX.Y.Z` tag | GitHub Actions |
| Signing | `deploy/release/sign.sh`, key `~/.ssh/e-pages-release`, public keys in `deploy/release/allowed_signers` | the maintainer's Mac only |
| Card preparation | `deploy/sdcard/prepare.sh` | Mac (or Linux PC) with the card plugged in |
| First boot | `deploy/sdcard/firstboot.sh`, run once by cloud-init | the Pi |
| Release installer | `python3 -m gcal_epd.releases` (`src/gcal_epd/releases.py`, `infrastructure/release/`) | the Pi, as root |
| Over-the-air update | `releases update` (`infrastructure/release/updater.py`), run daily by `epd-update.timer` | the Pi, as root |
| Units | `deploy/install.sh` (called by the installer with `--yes`) | the Pi |

A release is published as four files:

| File | Contents |
|---|---|
| `e-pages-<label>.tar.gz` | the committed code (`git archive HEAD`) plus a `RELEASE` file naming it |
| `e-pages-<label>-wheels-cp313-linux_armv6l.tar` | every Python package, prebuilt for the Pi Zero (ARMv6, Python 3.13) |
| `e-pages-<label>-sdcard.zip` | `epd-bundle/` for a new card: the code, `wheels/`, `debs/`, `firstboot.sh` |
| `SHA256SUMS` (+ `SHA256SUMS.sig`) | checksums of the three, and the maintainer's signature on them |

`<label>` is `X.Y.Z` for a commit tagged `vX.Y.Z`, otherwise `X.Y.Z+g<commit>`.

On the Pi, releases live side by side:

```
/opt/e-pages/releases/<label>/   code and its own .venv (root-owned, read-only to the app)
/opt/e-pages/current  -> releases/<label>   what the systemd units run
/opt/e-pages/previous -> releases/<label>   what a rollback returns to
/opt/e-pages/data/               this display's files: ics_feeds.toml, config.local.toml, preview.png
```

The installer builds a release next to the running one, switches `current`
only after the new release imports, opens the GPIO chip as the app's user
and reports its own label, and keeps the previous release for rollback.
`data/` is never replaced by an update.

---

## Set up a new display

What you need: the Pi Zero W/WH with the Waveshare 7.3" (F) panel, a
microSD card (8 GB or more), and a Mac or PC with
[Raspberry Pi Imager](https://www.raspberrypi.com/software/). The Pi needs
no network for the install; Wi-Fi is set from a phone afterwards.

### 1. Write the card with Imager

- Device: **Raspberry Pi Zero** (Zero W/WH).
- OS: **Raspberry Pi OS (other) → Raspberry Pi OS Lite (32-bit)**, the
  Trixie release. Not 64-bit: the Pi Zero has an ARMv6 CPU.
- Customisation:
  - hostname, e.g. `epaper`;
  - a **username** and password (the app runs as this user);
  - time zone;
  - SSH on, with your public key, if you want to log in later;
  - Wi-Fi: optional. Without it, the display opens its own setup hotspot.

When Imager has finished, take the card out and put it back in, so the
computer mounts its boot partition (`/Volumes/bootfs` on a Mac). **Do not
put the card in the Pi yet:** cloud-init reads the settings below only on
the very first boot.

### 2. Add the calendar to the card

From a checkout of this repository, on the same computer:

```bash
bash deploy/sdcard/prepare.sh --release v0.2.0     # a published release
```

or, to install code that is not released yet (a branch under test):

```bash
venv/bin/python -m gcal_epd.build_release          # prints dist/<label>/
bash deploy/sdcard/prepare.sh --bundle dist/<label>/e-pages-<label>-sdcard.zip
```

`prepare.sh` then:

1. copies `epd-bundle/` to the boot partition (about 25 MB);
2. turns SPI on in `config.txt` (the panel's bus);
3. sets the Wi-Fi country in `cmdline.txt` (`--country`, default `TW`);
4. adds to Imager's `user-data`: run `epd-bundle/firstboot.sh` as the
   Imager user, and reboot once it has finished.

Options: `--boot DIR` if the partition is mounted elsewhere;
`--allow-unsigned` for a release not signed yet. It refuses a card that has
booted before, and a release whose signature or checksum does not verify.

### 3. First boot

Eject the card, put it in the Pi, power it on. The first boot takes about
10 minutes on a Pi Zero; the panel stays blank meanwhile:

1. cloud-init creates the user, then runs `firstboot.sh`;
2. `firstboot.sh` installs `debs/` with `dpkg` (Pillow's libraries,
   watchdog), then runs the release installer with the bundled wheels and
   no network;
3. the installer builds `/opt/e-pages/releases/<label>`, switches to it and
   installs the systemd units;
4. cloud-init reboots.

After the reboot the panel shows the Wi-Fi setup QR code (or the calendar
setup screen, if Wi-Fi was set in Imager). From there, follow the panel; see
[Wi-Fi setup](../README.md#wi-fi-setup) and
[Calendar feeds](../README.md#calendar-feeds).

### 4. If the panel stays blank

Put the card back in the computer and read `epd-firstboot.log` on the boot
partition: it ends with `=== done` or with `FAILED ... at line N`. Over SSH:

```bash
sudo cat /var/log/epd-firstboot.log
sudo cloud-init status --long
python3 -m gcal_epd.releases list 2>/dev/null || ls -l /opt/e-pages
journalctl -b -u epd-wifi-setup -u gcal-epd --no-pager | tail -50
```

To run the first boot again, write the card again with Imager and repeat
from step 1 (cloud-init runs `user-data` once per card).

---

## Publish a release

1. Bump `version` in `pyproject.toml` on `develop`, merge to the branch you
   release from, and tag that commit:

   ```bash
   git tag v0.2.0 && git push origin v0.2.0
   ```

2. `release.yml` runs the tests, checks the tag matches `pyproject.toml`,
   builds the four files and publishes them as a GitHub **pre-release**:
   the beta channel.

3. On the maintainer's Mac, sign it:

   ```bash
   bash deploy/release/sign.sh v0.2.0
   ```

   It downloads every file, checks each against `SHA256SUMS`, signs
   `SHA256SUMS` and uploads `SHA256SUMS.sig`. From then on, displays on
   the beta channel install it at their next daily check.

4. Once it has run well on the beta display, promote it to stable; stable
   displays then install it at their next check:

   ```bash
   gh release edit v0.2.0 --prerelease=false --latest
   ```

### Signing keys, once

Two keys, made before the first release is tagged:

| Key | Kept | Signs |
|---|---|---|
| everyday, `~/.ssh/e-pages-release` | on the maintainer's Mac | every release |
| backup | offline: a password manager, or a USB stick put away | only the release that replaces a lost or leaked everyday key |

A display accepts a release signed by any key listed in the
`allowed_signers` of the release it is **already running**. With the
backup listed from the start, losing the everyday key costs one release,
not a trip to every display.

1. Make both, each with a passphrase:

   ```bash
   ssh-keygen -t ed25519 -f ~/.ssh/e-pages-release -C e-pages-release
   ssh-keygen -t ed25519 -f ~/e-pages-release-backup -C e-pages-release-backup
   ```

2. List both public keys in `deploy/release/allowed_signers`:

   ```bash
   for k in ~/.ssh/e-pages-release ~/e-pages-release-backup; do
       echo "e-pages-release namespaces=\"e-pages-release\" $(cat "$k.pub")"
   done >> deploy/release/allowed_signers
   ```

3. Store the backup: put `~/e-pages-release-backup` (the private file) in
   the password manager or on the USB stick, with its passphrase kept
   apart from it. Then delete it from the Mac:

   ```bash
   rm ~/e-pages-release-backup ~/e-pages-release-backup.pub
   ```

4. Commit `allowed_signers` and tag the first release; every display then
   trusts both keys.

Private keys never go in the repository, CI secrets or a chat. Public keys
are not secret.

### When a key is lost or leaked

Replace the everyday key with one release signed by the backup:

1. Make a new everyday key (step 1 above, first line). In
   `allowed_signers`, replace the old everyday line with the new one; keep
   the backup line.
2. Bump the version, merge, tag. When the release is published, bring the
   backup key back onto the Mac for a moment and sign with it:

   ```bash
   bash deploy/release/sign.sh v0.5.0 --key /path/to/e-pages-release-backup
   rm /path/to/e-pages-release-backup
   ```

3. Displays verify it with the backup key they already trust, install it,
   and from then on trust the new everyday key; the old one no longer
   works anywhere. New cards need nothing: `git pull` before `prepare.sh`.
4. If the backup itself was exposed, make a new backup the same way and
   ship it in the next release, signed with the new everyday key.

A display that stays off past this release still trusts only the old
keys: the backup-signed release must stay available until it has updated.
If both keys are lost, every display has to be reinstalled by hand: over
SSH with `deploy/install-release.sh`, or by writing its card again.

### Build without publishing

```bash
venv/bin/python -m gcal_epd.build_release             # dist/<label>/
venv/bin/python -m gcal_epd.build_release --out DIR
```

It builds the committed `HEAD` (uncommitted edits are left out, with a
warning) and needs the network: piwheels, PyPI and the Raspberry Pi OS
archive. Running the Release workflow by hand on the Actions tab does the
same and keeps the files as a workflow artifact.

### When a .deb download fails

`deploy/sdcard/debs.lock` pins each `.deb` a new card needs, with its
SHA-256. The archive keeps only the newest version, so a pin breaks after a
security update. Re-pin, review the diff, commit:

```bash
venv/bin/python -m gcal_epd.build_release --refresh-debs
git diff deploy/sdcard/debs.lock
```

---

## Update a running display

### Automatic updates

A display installed as a release updates itself. `epd-update.timer` runs
`python3 -m gcal_epd.releases update` once a day (03:00–04:00 Taiwan time;
soon after the next boot if the Pi was off), which:

1. lists the repository's releases on GitHub;
2. picks the newest one for the display's channel that is newer than the
   running release (never an older one) and has not failed here before;
3. checks `SHA256SUMS.sig` against the `allowed_signers` of the **running**
   release, then every file against `SHA256SUMS`; an unsigned release
   waits until it is signed;
4. builds and switches to it, like any install (the old release keeps
   running until the new one imports);
5. renders the calendar once with it, as the app's user, without touching
   the panel. If that crashes or hangs, it rolls back to the previous
   release and never tries this one again. A release whose build fails
   three times is given up too.

The panel shows the new release at its next scheduled refresh.

### Channel

| Channel | Takes | For |
|---|---|---|
| `stable` (default) | full releases | friends' displays |
| `beta` | pre-releases too | the maintainer's own display |

Set it per display in `/opt/e-pages/data/config.local.toml`:

```toml
[update]
channel = "beta"      # or "stable"
enabled = true        # false: no automatic updates
```

### Check and update by hand

```bash
P="sudo env PYTHONPATH=/opt/e-pages/current/src python3 -m gcal_epd.releases"
$P status               # running release, channel, last check and its result
$P update --check       # is there a newer release?
$P update               # update now (also with updates off)
$P update --channel beta
journalctl -u epd-update -n 50
```

`status` also lists rejected releases. To retry one, remove it from
`rejected` in `/opt/e-pages/data/update-state.json`.

### Install, switch and roll back by hand

From a checkout (installs its committed `HEAD`):

```bash
cd ~/google-calendar-api && git pull
bash deploy/install-release.sh
```

From published files (the code and wheels tars of one release):

```bash
mkdir -p /tmp/rel && cd /tmp/rel
tar -xzf e-pages-0.2.0.tar.gz && tar -xf e-pages-0.2.0-wheels-cp313-linux_armv6l.tar
sudo env PYTHONPATH=/tmp/rel/src python3 -m gcal_epd.releases install \
    --source e-pages-0.2.0.tar.gz --wheels wheels --user "$USER"
```

The display keeps running the old release while the new one builds (about
5 minutes on a Pi Zero). Then:

```bash
$P list                 # installed releases, current and previous marked
$P rollback             # back to the previous release
$P switch 0.2.0         # any installed release
$P prune                # remove old and unfinished releases
```

`switch` and `rollback` also reinstall the systemd units from the release
they switch to, so the units always match the code. A switch takes effect
at the next refresh or boot.

A display that still runs from a git checkout moves to this layout once,
with `bash deploy/install-release.sh --migrate-from ~/google-calendar-api`.
A display installed before automatic updates existed gets them by
installing, once by hand, a release that has them.

---

## Rules and pitfalls

| Rule | Why |
|---|---|
| Never commit, print or log `ics_feeds.toml` or its URLs | each URL is a bearer token to a private calendar |
| Never copy the signing key or a device password anywhere | the key is what makes a release trusted |
| Wheels must be `linux_armv6l` or `any` | ARMv7 wheels crash a Pi Zero with "Illegal instruction"; the build refuses them |
| Build tars with Python's `tarfile`, not a Mac's `tar` | macOS adds extended attributes and `._` files |
| Do not pass `PYTHONPATH` to the release's own commands | the new release would import the installer's copy; `installer.child_env()` strips it |
| The app needs `LG_WD` pointing at `data/` | lgpio makes pipes in its working directory, and the release is read-only |
| `prepare.sh` only works on a card that never booted | cloud-init runs `user-data` once per card |
| `firstboot.sh` must not need the network | a new display has no Wi-Fi until its owner sets it |
