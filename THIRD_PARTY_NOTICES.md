# Third-party notices

e-pages itself is under the MIT License (see [LICENSE](LICENSE)). It ships
or uses the work of others, listed here with their licenses. Each license
text travels with the component it covers: next to the font, in the file
headers, inside each wheel's `*.dist-info`, or in each Debian package's
`/usr/share/doc/<package>/copyright`.

This file is in English only: it is a legal notice, not documentation.
`tests/test_licenses.py` checks it lists every font, pinned Python package
and Debian package, so a re-pin cannot leave it behind.

## In this repository

| Component | Where | License |
|---|---|---|
| Fonts | `assets/fonts/` | Noto fonts by Google and Adobe, SIL Open Font License 1.1. Each font ships with its license and copyright notice next to it (`*-OFL.txt`). "Noto" is a trademark of Google. |
| Waveshare e-Paper driver | `vendor/waveshare_epd/` | MIT-style, in each file's header (Copyright Waveshare). |

## Python packages

Installed from PyPI and piwheels on a development machine, and bundled as
wheels in each release (`*-wheels-*.tar` and the SD card bundle). Each
wheel carries its own license file. The pinned versions are in
`requirements.txt`, `requirements-pi.txt` and `requirements-build.txt`.

| Package | License |
|---|---|
| certifi | MPL-2.0 |
| charset-normalizer | MIT |
| click | BSD-3-Clause |
| colorzero | BSD-3-Clause |
| gpiozero | BSD-3-Clause |
| icalendar | BSD-2-Clause |
| idna | BSD-3-Clause |
| lgpio | Unlicense |
| pillow | MIT-CMU |
| python-dateutil | Apache-2.0 or BSD-3-Clause |
| qrcode | BSD-3-Clause |
| recurring-ical-events | LGPL-3.0-or-later |
| requests | Apache-2.0 |
| setuptools | MIT |
| six | MIT |
| spidev | MIT |
| typing-extensions | PSF-2.0 |
| tzdata | Apache-2.0 |
| urllib3 | MIT |
| x-wr-timezone | LGPL-3.0-or-later |

`recurring-ical-events` and `x-wr-timezone` are LGPL-3.0-or-later. e-pages
only imports them, and ships them as the unmodified, pure-Python wheels
published on PyPI, which contain their source. Anyone may replace them with
another version.

## Debian packages on the SD card

The SD card bundle (`*-sdcard.zip`) carries the `.deb` packages a fresh
Raspberry Pi OS Lite card lacks, pinned in `deploy/sdcard/debs.lock`.

| Package | Version | License | Source |
|---|---|---|---|
| libfreetype6 | 2.13.3+dfsg-1+deb13u2 | FTL | Raspbian `trixie`: `apt-get source freetype=2.13.3+dfsg-1+deb13u2` |
| liblcms2-2 | 2.16-2+deb13u2 | MIT | `apt-get source lcms2=2.16-2+deb13u2` |
| libopenjp2-7 | 2.5.3-2.1~deb13u2 | BSD-2-Clause | `apt-get source openjpeg2=2.5.3-2.1~deb13u2` |
| libwebpdemux2 | 1.5.0-0.1 | BSD-3-Clause | `apt-get source libwebp=1.5.0-0.1` |
| libwebpmux3 | 1.5.0-0.1 | BSD-3-Clause | `apt-get source libwebp=1.5.0-0.1` |
| libavif16 | 1.2.1-1.2 | BSD-2-Clause | `apt-get source libavif=1.2.1-1.2` |
| libaom3 | 3.12.1-1+deb13u1 | BSD-2-Clause | `apt-get source aom=3.12.1-1+deb13u1` |
| libdav1d7 | 1.5.1-1+rpi1 | BSD-2-Clause | `apt-get source dav1d=1.5.1-1+rpi1` |
| libgav1-1 | 0.19.0-3+rpi1+b1 | Apache-2.0 | `apt-get source libgav1=0.19.0-3+rpi1` |
| librav1e0.7 | 0.7.1-9 | BSD-2-Clause | `apt-get source rust-rav1e=0.7.1-9` |
| libsvtav1enc2 | 2.3.0+dfsg-1 | BSD-3-Clause-Clear | `apt-get source svt-av1=2.3.0+dfsg-1` |
| libyuv0 | 0.0.1904.20250204-1 | BSD-3-Clause | `apt-get source libyuv=0.0.1904.20250204-1` |
| watchdog | 5.16-1.1 | GPL-2.0-or-later | `apt-get source watchdog=5.16-1.1` |
| libonig5 | 6.9.9-1 | BSD-2-Clause | `apt-get source libonig=6.9.9-1` |
| libjq1 | 1.7.1-6+deb13u4 | MIT | `apt-get source jq=1.7.1-6+deb13u4` |
| jq | 1.7.1-6+deb13u4 | MIT | `apt-get source jq=1.7.1-6+deb13u4` |
| pisugar-server | 2.4.0-1 | GPL-3.0 | https://github.com/PiSugar/pisugar-power-manager-rs/tree/v2.4.0 |
| pisugar-poweroff | 2.4.0-1 | GPL-3.0 | https://github.com/PiSugar/pisugar-power-manager-rs/tree/v2.4.0 |

The licenses are the main (`Files: *`) license in each package's own
`copyright` file; some packages contain files under other licenses, listed
there in full. The packages are shipped unmodified. Their complete
corresponding source is available at the versions above: Debian packages
from the Raspbian archive named in `debs.lock`
(`http://raspbian.raspberrypi.com/raspbian`, suite `trixie`, source
packages under `pool/`), and the PiSugar daemon from its upstream tag. If
a version is no longer available there, ask for it in an issue on this
repository and it will be provided.

## Data

| Source | Use | License |
|---|---|---|
| [Open-Meteo](https://open-meteo.com/) | The weather on the panel, fetched from the free API | Data under [CC BY 4.0](https://open-meteo.com/en/licence): "Weather data by Open-Meteo.com". The free API is for non-commercial use only. |

## Inspiration

The idea for e-pages came from [Glance](https://github.com/bolintw/Glance)
by Bo Lin, an e-paper calendar in a picture frame (CC BY-NC-SA 4.0).
e-pages is a separate implementation in Python for the Raspberry Pi and
contains no code, text or images from Glance.
