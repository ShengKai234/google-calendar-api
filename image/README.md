**English** | [繁體中文](README.zh-TW.md)

# Ready-to-flash image

`image/` turns the official Raspberry Pi OS Lite image into one with the
calendar already installed: system packages, `.venv`, systemd units, SPI and
the watchdog. Flash it, boot, and the panel goes straight to Wi-Fi setup —
no SSH, no `setup.sh`, nothing downloaded on the Pi.

---

## Releasing

```bash
git tag v1.0.0
git push origin v1.0.0
```

The **Release image** workflow (`.github/workflows/release-image.yml`) runs
the tests, builds the image and publishes a GitHub Release with
`e-pages-v1.0.0.img.xz` and its `.sha256`. Running the workflow by hand from
the Actions tab builds without releasing; the image is kept as an artifact
for 7 days.

## Building locally

Needs Docker (Docker Desktop on a Mac is fine).

```bash
bash image/build-in-docker.sh
# → image/dist/e-pages-<git describe>.img.xz
```

Only committed files go in. `WIFI_COUNTRY=JP` changes the Wi-Fi regulatory
country (default `TW`); `VERSION=…` names the file.

## Flashing

In Raspberry Pi Imager choose **Use custom** and the `.img.xz`. OS
customisation is optional: the calendar needs no login user. Add a user and
SSH only if you want to log in for maintenance.

---

## What the build does

| Step | Detail |
|------|--------|
| Base | Downloads the release pinned in `base.env` and checks its SHA-256 |
| Grow | Adds 768MB to the root partition (the Pi fills the card on first boot) |
| Packages | `watchdog` and the libraries Pillow's piwheels wheel links against |
| Program | The commit, in `/opt/e-pages`, owned by the system user `epd` (groups `spi`, `gpio`) |
| `.venv` | Built in an ARMv6 chroot (`QEMU_CPU=arm1176`), so pip picks Pi Zero wheels |
| Units | `deploy/install.sh`, unchanged, with `sudo` and `systemctl start` stubbed for the chroot |
| Boot | `dtparam=spi=on`; Wi-Fi country on the kernel command line; `rfkill unblock wifi` before the hotspot |

The app runs from `/opt/e-pages` rather than a home directory because the
image has no user yet — Imager creates one, if asked, at first boot.

To move to a newer Raspberry Pi OS, update both lines of `base.env`.
