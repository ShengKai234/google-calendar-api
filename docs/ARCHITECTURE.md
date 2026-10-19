**English** | [繁體中文](ARCHITECTURE.zh-TW.md)

# Architecture

How the code is layered, how `install.sh` turns it into systemd units, and
what runs, in what order, when the Pi boots. For installing and using the
display, see the [README](../README.md).

---

## Code layers

`src/gcal_epd` follows a DDD layout. Two entry points do the wiring; the work
happens in the application and infrastructure layers; `render` draws; `epd.py`
pushes to the panel. Arrows mean "calls / depends on".

```mermaid
flowchart TB
  subgraph ENTRY["Entry points (python -m)"]
    MAIN["main.py<br/>calendar: setup or refresh"]
    WIFI["wifi_setup.py<br/>Wi-Fi hotspot setup"]
  end
  CFG["config.py<br/>PROJECT_ROOT · load_config<br/>font_path · feeds_file"]
  subgraph APP["application"]
    DS["display_service.run()"]
    SS["setup_service<br/>run_onboarding() · apply_pending_feeds()"]
  end
  subgraph INFRA["infrastructure"]
    FF["feeds_file.py<br/>load · write · reset · pending"]
    ICS["ics/repository.py<br/>ICSRepository"]
    OM["open_meteo/repository.py<br/>OpenMeteoRepository"]
    ONB["onboarding/server.py<br/>FeedSetupServer :8080 · check_feed"]
    NM["wifi/nmcli.py<br/>NetworkManager"]
    WS["wifi/server.py<br/>WifiSetupServer :80"]
  end
  subgraph RENDER["render"]
    DRAW["draw.py<br/>render() · render_setup()"]
    LAYOUT["layout.py<br/>build_layout()"]
    WSCR["wifi_screens.py"]
  end
  DOM["domain<br/>CalendarEvent · WeatherInfo<br/>Repository Protocols"]
  EPD["epd.py push_to_display()<br/>→ vendor/waveshare_epd"]

  MAIN --> CFG
  MAIN -->|"load_feeds · reset_feeds"| FF
  MAIN -->|"build repositories"| ICS
  MAIN -->|"build repositories"| OM
  MAIN -->|"setup · links waiting"| SS
  MAIN -->|"refresh"| DS
  SS --> CFG
  SS -->|"form · check_feed"| ONB
  SS -->|"read pending · write feeds"| FF
  SS -->|"setup screen"| DRAW
  SS --> EPD
  DS --> CFG
  DS -->|"Protocols"| DOM
  DS --> ICS
  DS --> OM
  DS --> DRAW
  DS --> EPD
  ONB -->|"write_feeds_file"| FF
  ONB -->|"fetch to check"| ICS
  WIFI --> CFG
  WIFI --> NM
  WIFI --> WS
  WIFI --> WSCR
  WIFI --> EPD
  WIFI -->|"write_pending_feeds"| FF
  WS -->|"AP_ADDRESS"| NM
  WS -->|"validate_feed_url"| ONB
  WSCR -->|"fonts, text helpers"| DRAW
  DRAW --> LAYOUT
  LAYOUT --> DOM
  ICS --> DOM
  OM --> DOM
```

- **The entry points never import each other.** Both read settings from
  `config.py`. A test runs the Wi-Fi panel path and fails if `gcal_epd.main`
  was imported.
- **`main.py` is only the composition root**: parse arguments, build the
  repositories, choose setup or refresh, confirm `--reset`. Setup lives in
  `setup_service`, the refresh in `display_service`.
- **`feeds_file.py` is the only owner of `ics_feeds.toml`** and of its
  twin `ics_feeds.pending.toml`, where links from the hotspot form wait to be
  checked. Their format is read, written and deleted there, and nowhere else.
- **`wifi/nmcli.py` is the only code that changes the system's network
  settings.** It calls `nmcli` with argument lists, never through a shell.
- **Two web forms.** The Wi-Fi form lives on the hotspot (port 80, no PIN —
  joining needs the password shown on the panel). The calendar form lives on
  the home network (port 8080, PIN required).
- **Logging is configured in each `main()`**, never at import.

---

## From code to the Pi

The unit files in `deploy/` are templates. `install.sh` fills them in and
installs them; a copy made by hand will not start.

```mermaid
flowchart LR
  T["deploy/*.service<br/>@PROJECT_DIR@ · @USER@<br/>@FEEDS_FILE@ · @PENDING_FILE@"]
  C["config.toml<br/>feeds_file"]
  P["config.feeds_file()<br/>pending_feeds_path()"]
  I["install.sh<br/>install_unit()"]
  S["/etc/systemd/system/"]
  E["enable<br/>gcal-epd.timer<br/>epd-wifi-setup.service"]
  C --> P
  P -->|"FEEDS_FILE · PENDING_FILE"| I
  T --> I
  I -->|"fill in, refuse leftovers"| S
  S --> E
```

`@PROJECT_DIR@` is where the checkout lives and `@USER@` is who owns it.
`@FEEDS_FILE@` and `@PENDING_FILE@` are asked of the app itself, so the units
and `config.toml` can never disagree. `install.sh` refuses paths with spaces and any placeholder it
does not fill.

---

## Runtime: systemd units

Two things start at boot: `epd-wifi-setup`, and the `gcal-epd.timer`
schedule. Once Wi-Fi setup knows the Pi is online it starts both calendar
units. Their `ConditionPathExists` lines on the feeds file and the pending
file are exact opposites, so systemd runs exactly one: calendar setup while
there are no feeds or links wait to be checked, the refresh otherwise.

```mermaid
flowchart TB
  BOOT(["Boot"]) --> W["epd-wifi-setup.service<br/>root · no time limit<br/>python -m gcal_epd.wifi_setup"]
  BOOT --> TIMER
  W -->|"start_units()<br/>systemctl start --no-block"| COND{"Feeds file exists<br/>and no links waiting?"}
  COND -->|"no"| F["epd-feed-setup.service<br/>user · 900 s<br/>main --display"]
  COND -->|"yes"| G["gcal-epd.service<br/>user · 120 s<br/>main --display --no-setup"]
  TIMER(["gcal-epd.timer<br/>07:00 / 19:00 Asia/Taipei<br/>catches up a missed run at boot"]) --> G
  F -->|"links work / saved"| PANEL[["Panel: calendar"]]
  F -->|"a link fails"| ERRQ[["Panel: setup QR + reason"]]
  F -->|"10 min unused"| EMPTY[["Panel: empty calendar"]]
  G --> PANEL
  W -.->|"Before=: neither starts<br/>until Wi-Fi setup ends"| F
  W -.-> G
  F -.->|"Before=: a timer run<br/>waits for setup"| G
```

| Unit | Runs | As | Time limit | When |
|---|---|---|---|---|
| `epd-wifi-setup.service` | `wifi_setup.main()` | root | none | every boot (enabled) |
| `epd-feed-setup.service` | `main.main()` | checkout owner | 900 s | after Wi-Fi setup, if there is no feeds file or links wait to be checked |
| `gcal-epd.service` | `main.main() --no-setup` | checkout owner | 120 s | otherwise after Wi-Fi setup; on the timer; a missed run at boot |
| `gcal-epd.timer` | starts `gcal-epd.service` | — | — | 07:00 and 19:00 Asia/Taipei |

- **Root is needed for two things only**: `nmcli` changes network settings,
  and the Wi-Fi form listens on port 80. Everything calendar-related runs as
  the checkout's owner.
- **`DefaultDependencies=no`** on Wi-Fi setup: while the hotspot waits for a
  person, the rest of boot (SSH included) carries on.
- **`--no-setup`** keeps the scheduled refresh from ever waiting on the form,
  so its 120 s limit holds.

---

## First boot, step by step

A new display with no Wi-Fi and no calendar links, set up in one go: the
phone sends the Wi-Fi password and the calendar links on the hotspot form.

```mermaid
sequenceDiagram
  autonumber
  participant SD as systemd
  participant W as wifi_setup.run()
  participant NM as NetworkManager
  participant P as Panel
  participant PH as Phone
  participant M as main (feed setup)
  SD->>W: start epd-wifi-setup at boot
  W->>NM: wait_connected(60 s)
  NM-->>W: no network
  W->>NM: scan() first, while the radio is free
  W->>NM: start_hotspot() on 10.42.0.1
  W->>P: render_wifi_setup(): two QR codes
  PH->>NM: QR 1: join the hotspot
  PH->>W: QR 2: Wi-Fi password + calendar links
  W-->>PH: "Connecting…" page
  W->>NM: stop_hotspot(), connect()
  NM-->>W: joined the home network
  W->>W: write_pending_feeds()
  W->>P: render_wifi_connected()
  W->>SD: start_units(), exit
  SD->>M: links waiting → epd-feed-setup
  M->>M: apply_pending_feeds(): fetch each link
  alt every link works
    M->>P: display_service.run(): the calendar
  else a link fails
    M->>P: render_setup(): QR + PIN + reason in red
    PH->>M: fix the link, enter the PIN
    M->>P: display_service.run(): the calendar
  end
```

---

## Inside wifi_setup.run()

Returns `online`, `joined` or `cancelled`, or raises when the hotspot cannot
start (for example another interface already holds `10.42.0.x`), failing the
unit with the reason in the journal. However it ends, `finally` closes the
form and deletes the hotspot profile.

```mermaid
flowchart TB
  S(["run()"]) --> A{"--force?"}
  A -->|"no"| B{"wait_connected(60)"}
  B -->|"online"| ON(["return online"])
  B -->|"offline"| C
  A -->|"yes"| C["scan()<br/>new hotspot name + password"]
  C --> D["WifiSetupServer on its own thread<br/>start_hotspot()<br/>panel: hotspot screen"]
  D -.->|"cannot start"| ERR(["raise NmcliError<br/>unit fails"])
  D --> L{"handle_once()<br/>wait up to 1 s"}
  L -->|"credentials (+ links)"| X["stop_hotspot()<br/>connect()"]
  X -->|"joined"| J(["park links: write_pending_feeds()<br/>panel: connected<br/>return joined"])
  X -->|"failed"| R["set_error()<br/>resume_hotspot()<br/>panel: error in red"]
  R --> L
  L -->|"idle ≥ 120 s, ≥ 300 s since last try,<br/>a saved network exists"| Y["stop_hotspot()<br/>wait_connected(45)"]
  Y -->|"back online"| J
  Y -->|"still offline"| Z["scan() again<br/>resume_hotspot()"]
  Z --> L
  L -.->|"Ctrl+C"| CAN(["return cancelled"])
```

The form runs on its own thread with a 10 s timeout per connection, so it
keeps answering while the loop is blocked on a panel refresh (about 15–30 s on the Pi), and
a browser's idle pre-connection cannot hold up the real request.

---

## Inside main()

The same `main()` serves two units. `epd-feed-setup` runs it without
`--no-setup`, so it may open the form; `gcal-epd` passes `--no-setup`, so it
never waits on a person.

```mermaid
flowchart TB
  S(["main()"]) --> LOG["logging.basicConfig()<br/>config.load_config()"]
  LOG --> RS{"--reset?"}
  RS -->|"yes"| DEL["_confirm_reset()<br/>feeds_file.reset_feeds()"]
  RS -->|"yes, declined"| STOP(["exit, feeds untouched"])
  RS -->|"no"| PEND
  DEL --> PEND{"links waiting<br/>from the Wi-Fi form?"}
  PEND -->|"yes"| AP["setup_service.apply_pending_feeds()<br/>fetch each link"]
  PEND -->|"no"| REPO
  AP -->|"all work: saved as feeds"| REPO
  AP -->|"one fails: keep the reason"| REPO
  REPO["_build_event_repos()<br/>feeds_file.load_feeds()"] --> Q{"--setup or --reset, or<br/>(no feeds or a link failed)<br/>without --no-setup?"}
  Q -->|"yes"| ONB["setup_service.run_onboarding()<br/>panel: QR + PIN (+ reason)<br/>form open 10 min"]
  ONB -->|"saved"| REPO2["_build_event_repos() again"]
  ONB -->|"timed out: empty calendar"| RUN
  REPO2 --> RUN
  Q -->|"no"| RUN["display_service.run()"]
  RUN --> F1["ICSRepository.fetch_events() per feed"]
  F1 --> F2["OpenMeteoRepository.fetch_weather()"]
  F2 --> F3["render(): build_layout(), draw"]
  F3 --> F4["push_to_display() with --display"]
```

---

## Known gaps

- **Only one process may drive the panel.** `Before=` orders the boot
  hand-over and makes a timer run wait for calendar setup, but a run started
  by hand while another is drawing still fails with `GPIO busy`.
- **An unused calendar form ends in an empty calendar.** After the 10-minute
  window the panel shows no events rather than the setup QR; reboot or run
  `--setup` to try again.
- **Several `ics` sources are only half supported.** The refresh reads every
  source's `feeds_file`, but setup and reset use the first one only.
  `config.toml` ships with a single source.
