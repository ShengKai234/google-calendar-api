[English](ARCHITECTURE.md) | **繁體中文**

# 架構

這份文件說明三件事：程式碼怎麼分層、`install.sh` 怎麼把程式變成 systemd unit，以及 Pi 開機後依什麼順序執行哪些程式。安裝和使用方式請看 [README](../README.zh-TW.md)。

---

## 程式分層

`src/gcal_epd` 採用 DDD 分層：兩個入口負責組裝，實際工作在 application 和 infrastructure 層，`render` 負責畫圖，`epd.py` 把圖推到面板。箭頭代表「呼叫／依賴」。

```mermaid
flowchart TB
  subgraph ENTRY["入口（python -m）"]
    MAIN["main.py<br/>日曆：設定或更新"]
    WIFI["wifi_setup.py<br/>Wi-Fi 熱點設定"]
  end
  CFG["config.py<br/>PROJECT_ROOT · load_config<br/>font_path · feeds_file"]
  subgraph APP["application"]
    DS["display_service.run()"]
    SS["setup_service.run_onboarding()"]
  end
  subgraph INFRA["infrastructure"]
    FF["feeds_file.py<br/>讀 · 寫 · 重置"]
    ICS["ics/repository.py<br/>ICSRepository"]
    OM["open_meteo/repository.py<br/>OpenMeteoRepository"]
    ONB["onboarding/server.py<br/>FeedSetupServer :8080"]
    NM["wifi/nmcli.py<br/>NetworkManager"]
    WS["wifi/server.py<br/>WifiSetupServer :80"]
  end
  subgraph RENDER["render"]
    DRAW["draw.py<br/>render() · render_setup()"]
    LAYOUT["layout.py<br/>build_layout()"]
    WSCR["wifi_screens.py"]
  end
  DOM["domain<br/>CalendarEvent · WeatherInfo<br/>Repository Protocol"]
  EPD["epd.py push_to_display()<br/>→ vendor/waveshare_epd"]

  MAIN --> CFG
  MAIN -->|"load_feeds · reset_feeds"| FF
  MAIN -->|"建立 repository"| ICS
  MAIN -->|"建立 repository"| OM
  MAIN -->|"沒有日曆 / --setup"| SS
  MAIN -->|"更新"| DS
  SS --> CFG
  SS --> ONB
  SS -->|"設定畫面"| DRAW
  SS --> EPD
  DS --> CFG
  DS -->|"Protocol"| DOM
  DS --> ICS
  DS --> OM
  DS --> DRAW
  DS --> EPD
  ONB -->|"write_feeds_file"| FF
  ONB -->|"probe_feed"| ICS
  WIFI --> CFG
  WIFI --> NM
  WIFI --> WS
  WIFI --> WSCR
  WIFI --> EPD
  WS -->|"AP_ADDRESS"| NM
  WSCR -->|"字型、文字工具"| DRAW
  DRAW --> LAYOUT
  LAYOUT --> DOM
  ICS --> DOM
  OM --> DOM
```

- **兩個入口互不 import。** 設定都從 `config.py` 讀。有一個測試會跑 Wi‑Fi 面板流程，只要過程中 import 了 `gcal_epd.main` 就會失敗。
- **`main.py` 只是組裝中心**：解析參數、建立 repository、決定跑設定還是更新、確認 `--reset`。設定流程在 `setup_service`，更新流程在 `display_service`。
- **`ics_feeds.toml` 只歸 `feeds_file.py` 管。** 檔案格式的讀、寫、刪除都只在這裡。
- **只有 `wifi/nmcli.py` 會修改系統網路設定。** 它用參數清單呼叫 `nmcli`，從不經過 shell。
- **有兩個網頁表單。** Wi‑Fi 表單開在熱點上（port 80、不需 PIN，因為要連上熱點就得看到面板上的密碼）；日曆表單開在家裡網路上（port 8080、需要 PIN）。
- **logging 在各自的 `main()` 裡設定**，import 時不會設定。

---

## 從程式到 Pi

`deploy/` 裡的 unit 檔是範本，由 `install.sh` 填好值再安裝。手動複製的檔案無法啟動。

```mermaid
flowchart LR
  T["deploy/*.service<br/>@PROJECT_DIR@ · @USER@<br/>@FEEDS_FILE@"]
  C["config.toml<br/>feeds_file"]
  P["config.feeds_file()"]
  I["install.sh<br/>install_unit()"]
  S["/etc/systemd/system/"]
  E["啟用<br/>gcal-epd.timer<br/>epd-wifi-setup.service"]
  C --> P
  P -->|"FEEDS_FILE"| I
  T --> I
  I -->|"填值，有殘留就拒絕"| S
  S --> E
```

`@PROJECT_DIR@` 是程式所在的資料夾，`@USER@` 是擁有這個資料夾的使用者，`@FEEDS_FILE@` 則直接問程式本身，所以 unit 和 `config.toml` 不可能對不上。路徑含空白，或有沒填到的佔位符，`install.sh` 都會拒絕安裝。

---

## 執行架構：systemd unit

開機時會啟動兩樣東西：`epd-wifi-setup`，以及 `gcal-epd.timer` 排程。Wi‑Fi 設定確認有網路後，會同時啟動兩個日曆 unit；兩者對日曆檔的 `ConditionPathExists` 條件相反，所以 systemd 只會真的執行其中一個。

```mermaid
flowchart TB
  BOOT(["開機"]) --> W["epd-wifi-setup.service<br/>root · 不設時間上限<br/>python -m gcal_epd.wifi_setup"]
  BOOT --> TIMER
  W -->|"start_units()<br/>systemctl start --no-block"| COND{"日曆檔<br/>存在嗎？"}
  COND -->|"不存在"| F["epd-feed-setup.service<br/>一般使用者 · 900 秒<br/>main --display"]
  COND -->|"存在"| G["gcal-epd.service<br/>一般使用者 · 120 秒<br/>main --display --no-setup"]
  TIMER(["gcal-epd.timer<br/>07:00 / 19:00 Asia/Taipei<br/>開機時補跑錯過的排程"]) --> G
  F -->|"存好日曆網址"| PANEL[["面板：日曆"]]
  F -->|"10 分鐘沒人填"| EMPTY[["面板：空白日曆"]]
  G --> PANEL
  W -.->|"Before=：Wi-Fi 設定結束前<br/>兩者都不會開始"| F
  W -.-> G
```

| Unit | 執行 | 身分 | 時間上限 | 什麼時候 |
|---|---|---|---|---|
| `epd-wifi-setup.service` | `wifi_setup.main()` | root | 無 | 每次開機（已啟用） |
| `epd-feed-setup.service` | `main.main()` | 程式擁有者 | 900 秒 | Wi‑Fi 設定後，且沒有日曆檔 |
| `gcal-epd.service` | `main.main() --no-setup` | 程式擁有者 | 120 秒 | Wi‑Fi 設定後且有日曆檔；排程觸發；開機補跑 |
| `gcal-epd.timer` | 啟動 `gcal-epd.service` | — | — | Asia/Taipei 07:00、19:00 |

- **需要 root 的原因只有兩個**：`nmcli` 要修改網路設定，Wi‑Fi 表單要聽 port 80。和日曆相關的程式都以程式擁有者的身分執行。
- **Wi‑Fi 設定加了 `DefaultDependencies=no`**：熱點在等人操作時，其他開機流程（包括 SSH）照常進行。
- **`--no-setup`** 讓定時更新永遠不會停下來等表單，所以 120 秒的上限一定夠用。

---

## 第一次開機的完整流程

一台全新的機器：沒有 Wi‑Fi，也沒有日曆網址。

```mermaid
sequenceDiagram
  autonumber
  participant SD as systemd
  participant W as wifi_setup.run()
  participant NM as NetworkManager
  participant P as 面板
  participant PH as 手機
  participant M as main（日曆設定）
  SD->>W: 開機啟動 epd-wifi-setup
  W->>NM: wait_connected(60 秒)
  NM-->>W: 沒有網路
  W->>NM: 趁網卡空著先 scan()
  W->>NM: start_hotspot()，位址 10.42.0.1
  W->>P: render_wifi_setup()：兩個 QR
  PH->>NM: 掃 QR 1 連上熱點
  PH->>W: 掃 QR 2 打開表單、送出帳密
  W-->>PH: 「Connecting…」頁面
  W->>NM: stop_hotspot()、connect()
  NM-->>W: 連上家裡網路
  W->>P: render_wifi_connected()
  W->>SD: start_units()，結束
  SD->>M: 沒有日曆檔 → epd-feed-setup
  M->>P: render_setup()：QR + PIN
  PH->>M: 貼上日曆網址 + PIN
  M->>M: probe_feed() → write_feeds_file()
  M->>P: render_setup_success()
  M->>P: display_service.run()：日曆
```

---

## wifi_setup.run() 內部流程

回傳 `online`、`joined` 或 `cancelled` 其中之一。熱點開不起來時（例如另一個網卡已經占用 `10.42.0.x`）會丟出錯誤，unit 失敗，原因會寫進 journal。不管怎麼結束，`finally` 都會關掉表單並刪除熱點設定。

```mermaid
flowchart TB
  S(["run()"]) --> A{"--force？"}
  A -->|"否"| B{"wait_connected(60)"}
  B -->|"有網路"| ON(["回傳 online"])
  B -->|"沒網路"| C
  A -->|"是"| C["scan()<br/>產生熱點名稱與密碼"]
  C --> D["WifiSetupServer 在獨立執行緒<br/>start_hotspot()<br/>面板：熱點畫面"]
  D -.->|"開不起來"| ERR(["丟出 NmcliError<br/>unit 失敗"])
  D --> L{"handle_once()<br/>最多等 1 秒"}
  L -->|"收到帳密"| X["stop_hotspot()<br/>connect()"]
  X -->|"連上"| J(["面板：已連線<br/>回傳 joined"])
  X -->|"失敗"| R["set_error()<br/>resume_hotspot()<br/>面板：紅字錯誤"]
  R --> L
  L -->|"閒置 ≥ 120 秒、距上次重試 ≥ 300 秒、<br/>且有記住的網路"| Y["stop_hotspot()<br/>wait_connected(45)"]
  Y -->|"連回來了"| J
  Y -->|"還是沒網路"| Z["重新 scan()<br/>resume_hotspot()"]
  Z --> L
  L -.->|"Ctrl+C"| CAN(["回傳 cancelled"])
```

表單在獨立的執行緒上執行，每個連線最多等 10 秒。所以主迴圈在等面板刷新時（在 Pi 上大約 15–30 秒）表單照樣能回應，瀏覽器預先開好但沒用到的連線，也不會擋住真正的請求。

---

## main() 內部流程

同一個 `main()` 供兩個 unit 使用。`epd-feed-setup` 執行時不帶 `--no-setup`，可以開表單；`gcal-epd` 帶 `--no-setup`，永遠不會停下來等人。

```mermaid
flowchart TB
  S(["main()"]) --> LOG["logging.basicConfig()<br/>config.load_config()"]
  LOG --> RS{"--reset？"}
  RS -->|"是"| DEL["_confirm_reset()<br/>feeds_file.reset_feeds()"]
  RS -->|"是，但取消"| STOP(["結束，不動日曆檔"])
  RS -->|"否"| REPO
  DEL --> REPO["_build_event_repos()<br/>feeds_file.load_feeds()"]
  REPO --> Q{"--setup 或 --reset，或<br/>沒有日曆且沒有 --no-setup？"}
  Q -->|"是"| ONB["setup_service.run_onboarding()<br/>面板：QR + PIN<br/>表單開放 10 分鐘"]
  ONB -->|"存好"| OK["面板：Connected!"]
  OK --> REPO2["重新 _build_event_repos()"]
  ONB -->|"逾時：空白日曆"| RUN
  REPO2 --> RUN
  Q -->|"否"| RUN["display_service.run()"]
  RUN --> F1["每個日曆 ICSRepository.fetch_events()"]
  F1 --> F2["OpenMeteoRepository.fetch_weather()"]
  F2 --> F3["render()：build_layout() 排版、畫圖"]
  F3 --> F4["push_to_display()（有 --display 時）"]
```

---

## 已知的不足

- **同一時間只能有一個程式使用面板。** `Before=` 保證開機交接的順序，但手動執行的程式，或 `epd-feed-setup` 剛存好日曆、正在畫圖的那幾秒剛好碰上排程，都可能撞成 `GPIO busy`。
- **日曆表單沒人填，最後會顯示空白日曆。** 10 分鐘的表單時間結束後，面板顯示的是沒有行程的日曆，而不是設定 QR。要再試一次，請重開機或執行 `--setup`。
- **多個 `ics` 來源只支援一半。** 更新時會讀每個來源各自的 `feeds_file`，但設定和重置只處理第一個來源。`config.toml` 預設只有一個來源。
