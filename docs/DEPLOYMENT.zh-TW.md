# 部署

> 語言：[English](DEPLOYMENT.md) · **繁體中文**

說明日曆如何安裝到 Raspberry Pi 上、如何更新，包括建置 release、發布、準備新的 SD 卡，以及在運作中的裝置上安裝 release。內容寫成可以照步驟操作，給人看，也給在這個 repo 裡工作的 AI agent 看。

---

## 組成

| 元件 | 位置 | 在哪裡執行 |
|---|---|---|
| Release 建置 | `python -m gcal_epd.build_release`（`src/gcal_epd/build_release.py`、`infrastructure/release/artifacts.py`） | Mac 或 CI |
| Release workflow | `.github/workflows/release.yml`，推 `vX.Y.Z` tag 時觸發 | GitHub Actions |
| 簽章 | `deploy/release/sign.sh`，金鑰 `~/.ssh/e-pages-release`，公鑰列在 `deploy/release/allowed_signers` | 只在維護者的 Mac 上 |
| SD 卡準備 | `deploy/sdcard/prepare.sh` | 插著 SD 卡的 Mac（或 Linux 電腦） |
| 首次開機 | `deploy/sdcard/firstboot.sh`，由 cloud-init 執行一次 | Pi |
| Release 安裝程式 | `python3 -m gcal_epd.releases`（`src/gcal_epd/releases.py`、`infrastructure/release/`） | Pi，以 root 執行 |
| OTA 自動更新 | `releases update`（`infrastructure/release/updater.py`），由 `epd-update.timer` 每天執行 | Pi，以 root 執行 |
| Units | `deploy/install.sh`（由安裝程式以 `--yes` 呼叫） | Pi |

一個 release 發布成四個檔案：

| 檔案 | 內容 |
|---|---|
| `e-pages-<label>.tar.gz` | 已 commit 的程式碼（`git archive HEAD`），加上標示版本的 `RELEASE` 檔 |
| `e-pages-<label>-wheels-cp313-linux_armv6l.tar` | 所有 Python 套件，預先為 Pi Zero（ARMv6、Python 3.13）編譯好 |
| `e-pages-<label>-sdcard.zip` | 給新卡用的 `epd-bundle/`：程式碼、`wheels/`、`debs/`、`firstboot.sh` |
| `SHA256SUMS`（+ `SHA256SUMS.sig`） | 上面三個檔案的校驗碼，以及維護者對它的簽章 |

`<label>` 在 commit 有 `vX.Y.Z` tag 時是 `X.Y.Z`，否則是 `X.Y.Z+g<commit>`。

在 Pi 上，各版本並排存放：

```
/opt/e-pages/releases/<label>/   程式碼和它自己的 .venv（root 擁有，app 只能讀）
/opt/e-pages/current  -> releases/<label>   systemd units 執行的版本
/opt/e-pages/previous -> releases/<label>   rollback 回到的版本
/opt/e-pages/data/               這台裝置自己的檔案：ics_feeds.toml、config.local.toml、preview.png
```

安裝程式在執行中的版本旁邊建置新版本。新版本必須能 import、能以 app 使用者身分開啟 GPIO chip、回報的版本名稱正確，才會切換 `current`；上一個版本保留給 rollback。更新永遠不會取代 `data/`。

---

## 設定一台新裝置

需要：裝好 Waveshare 7.3" (F) 面板的 Pi Zero W/WH、一張 microSD 卡（8 GB 以上），以及裝了 [Raspberry Pi Imager](https://www.raspberrypi.com/software/) 的 Mac 或電腦。安裝過程 Pi 不需要網路，Wi-Fi 之後再用手機設定。

### 1. 用 Imager 寫入 SD 卡

- 裝置：**Raspberry Pi Zero**（Zero W/WH）。
- 作業系統：**Raspberry Pi OS (other) → Raspberry Pi OS Lite (32-bit)**，Trixie 版。不要選 64-bit：Pi Zero 是 ARMv6 CPU。
- 自訂設定：
  - 主機名稱，例如 `epaper`；
  - **使用者名稱**和密碼（app 會以這個使用者執行）；
  - 時區；
  - 如果之後要登入，開啟 SSH 並放入你的公鑰；
  - Wi-Fi：可不填。沒填的話，裝置會開自己的設定熱點。

Imager 完成後，把卡拔出再插回去，讓電腦掛載開機分割區（Mac 上是 `/Volumes/bootfs`）。**這時還不要把卡放進 Pi：**cloud-init 只在第一次開機時讀取下面的設定。

### 2. 把日曆加到卡上

在同一台電腦上，從這個 repo 的 checkout 執行：

```bash
bash deploy/sdcard/prepare.sh --release v0.2.0     # 已發布的 release
```

或者，要安裝還沒發布的程式碼（測試中的分支）：

```bash
venv/bin/python -m gcal_epd.build_release          # 會印出 dist/<label>/
bash deploy/sdcard/prepare.sh --bundle dist/<label>/e-pages-<label>-sdcard.zip
```

`prepare.sh` 會：

1. 把 `epd-bundle/` 複製到開機分割區（約 25 MB）；
2. 在 `config.txt` 開啟 SPI（面板用的匯流排）；
3. 在 `cmdline.txt` 設定 Wi-Fi 國家（`--country`，預設 `TW`）；
4. 在 Imager 產生的 `user-data` 中加入：以 Imager 建立的使用者執行 `epd-bundle/firstboot.sh`，完成後重新開機。

選項：分割區掛在別處時用 `--boot DIR`；release 還沒簽章時用 `--allow-unsigned`。它會拒絕已經開機過的卡，也會拒絕簽章或校驗碼不符的 release。

### 3. 首次開機

退出 SD 卡，放進 Pi，接上電源。Pi Zero 的首次開機約需 10 分鐘，期間面板保持空白：

1. cloud-init 建立使用者，然後執行 `firstboot.sh`；
2. `firstboot.sh` 用 `dpkg` 安裝 `debs/`（Pillow 需要的函式庫、watchdog），再用附帶的 wheels、在沒有網路的情況下執行 release 安裝程式；
3. 安裝程式建置 `/opt/e-pages/releases/<label>`，切換過去，並安裝 systemd units；
4. cloud-init 重新開機。

重新開機後，面板顯示 Wi-Fi 設定的 QR code（如果在 Imager 設了 Wi-Fi，則顯示日曆設定畫面）。接下來照面板指示操作，參考 [Wi-Fi 設定](../README.zh-TW.md#wi-fi-設定)與[日曆網址](../README.zh-TW.md#日曆網址)。

### 4. 面板一直空白時

把卡插回電腦，讀開機分割區上的 `epd-firstboot.log`：最後一行會是 `=== done`，或是 `FAILED ... at line N`。用 SSH 的話：

```bash
sudo cat /var/log/epd-firstboot.log
sudo cloud-init status --long
python3 -m gcal_epd.releases list 2>/dev/null || ls -l /opt/e-pages
journalctl -b -u epd-wifi-setup -u gcal-epd --no-pager | tail -50
```

要重跑首次開機，用 Imager 重新寫入 SD 卡，從步驟 1 重來（cloud-init 每張卡只執行一次 `user-data`）。

---

## 發布 release

1. 在 `develop` 上更新 `pyproject.toml` 的 `version`，合併到要發布的分支，並在那個 commit 打 tag：

   ```bash
   git tag v0.2.0 && git push origin v0.2.0
   ```

2. `release.yml` 會跑測試、確認 tag 和 `pyproject.toml` 一致、建置四個檔案，發布成 GitHub **pre-release**，也就是 beta 頻道。

3. 在維護者的 Mac 上簽章：

   ```bash
   bash deploy/release/sign.sh v0.2.0
   ```

   它會下載所有檔案、逐一對照 `SHA256SUMS`、簽署 `SHA256SUMS`，並上傳 `SHA256SUMS.sig`。簽好之後，beta 頻道的裝置會在下次每日檢查時安裝它。

4. 在 beta 裝置上運作正常後，升級為 stable；stable 頻道的裝置會在下次檢查時安裝：

   ```bash
   gh release edit v0.2.0 --prerelease=false --latest
   ```

### 簽章金鑰（只需做一次）

在第一個 release 打 tag 之前，建立兩把金鑰：

| 金鑰 | 存放位置 | 用來簽 |
|---|---|---|
| 日常金鑰，`~/.ssh/e-pages-release` | 維護者的 Mac | 每一個 release |
| 備用金鑰 | 離線保存：密碼管理器，或收好的 USB 隨身碟 | 只簽「取代遺失或外洩的日常金鑰」的那一個 release |

裝置接受的 release，必須由它**目前執行中**那個版本的 `allowed_signers` 裡任一把金鑰簽章。從一開始就列入備用金鑰，日常金鑰遺失時只需要多發一個版本，不必逐台處理。

1. 建立兩把金鑰，都設定密碼：

   ```bash
   ssh-keygen -t ed25519 -f ~/.ssh/e-pages-release -C e-pages-release
   ssh-keygen -t ed25519 -f ~/e-pages-release-backup -C e-pages-release-backup
   ```

2. 把兩把公鑰都列進 `deploy/release/allowed_signers`：

   ```bash
   for k in ~/.ssh/e-pages-release ~/e-pages-release-backup; do
       echo "e-pages-release namespaces=\"e-pages-release\" $(cat "$k.pub")"
   done >> deploy/release/allowed_signers
   ```

3. 保存備用金鑰：把 `~/e-pages-release-backup`（私鑰檔）存進密碼管理器或 USB 隨身碟，它的密碼另外分開保存。然後從 Mac 上刪除：

   ```bash
   rm ~/e-pages-release-backup ~/e-pages-release-backup.pub
   ```

4. Commit `allowed_signers`，再為第一個 release 打 tag；之後每台裝置都會信任這兩把金鑰。

私鑰絕不放進 repo、CI secrets 或對話中。公鑰不是機密。

### 金鑰遺失或外洩時

用備用金鑰簽一個 release，換掉日常金鑰：

1. 建立新的日常金鑰（上面步驟 1 的第一行）。在 `allowed_signers` 中，把舊的日常金鑰那行換成新的；備用金鑰那行保留。
2. 更新版本號、合併、打 tag。release 發布後，暫時把備用金鑰放回 Mac，用它簽章：

   ```bash
   bash deploy/release/sign.sh v0.5.0 --key /path/to/e-pages-release-backup
   rm /path/to/e-pages-release-backup
   ```

3. 裝置用它已經信任的備用金鑰驗證、安裝這個版本，之後就改為信任新的日常金鑰；舊的日常金鑰在任何裝置上都不再有效。新卡不需要額外處理：執行 `prepare.sh` 前先 `git pull` 即可。
4. 如果連備用金鑰也外洩了，用同樣方式建立新的備用金鑰，放進下一個 release，用新的日常金鑰簽章。

在這個版本發布期間一直沒開機的裝置，仍然只信任舊金鑰：用備用金鑰簽的那個 release 必須保留，直到它也更新完成。如果兩把金鑰都遺失，每台裝置都只能手動重裝：透過 SSH 執行 `deploy/install-release.sh`，或重新寫入 SD 卡。

### 只建置不發布

```bash
venv/bin/python -m gcal_epd.build_release             # dist/<label>/
venv/bin/python -m gcal_epd.build_release --out DIR
```

它建置已 commit 的 `HEAD`（未 commit 的修改不會包含，並會警告），而且需要網路：piwheels、PyPI 和 Raspberry Pi OS 的套件庫。在 Actions 頁面手動執行 Release workflow 也一樣，檔案會保留為 workflow artifact。

### .deb 下載失敗時

`deploy/sdcard/debs.lock` 釘住新卡需要的每個 `.deb` 和它的 SHA-256。套件庫只保留最新版，所以安全更新後釘住的版本會失效。重新釘選、檢查差異、commit：

```bash
venv/bin/python -m gcal_epd.build_release --refresh-debs
git diff deploy/sdcard/debs.lock
```

---

## 更新運作中的裝置

### 自動更新

安裝成 release 的裝置會自己更新。`epd-update.timer` 每天執行一次 `python3 -m gcal_epd.releases update`，時間是晚上刷新後一分鐘：台灣時間 19:01，或設定表單上最後一個喚醒時間的一分鐘後（由 `power_manager apply-schedule` 寫入 drop-in）。早上的刷新不會更新；Pi 關機時錯過的檢查會等到隔天晚上。用 PiSugar 電池時，10 分鐘內有更新檢查、或更新正在進行，電源管理都不會關機。步驟如下：

1. 列出 repo 在 GitHub 上的所有 release；
2. 挑出符合裝置頻道、比目前版本新（絕不降版）、而且之前沒在這台失敗過的最新版本；
3. 用**目前執行中**那個版本的 `allowed_signers` 驗證 `SHA256SUMS.sig`，再逐一比對 `SHA256SUMS`；還沒簽章的版本會等到簽好才裝；
4. 建置並切換過去，跟一般安裝一樣（新版本能 import 之前，舊版本照常運作）；
5. 用新版本以 app 使用者身分畫一次日曆，但不推到面板。如果當掉或卡住，就 rollback 回上一個版本，之後也不會再試這個版本。建置連續失敗三次的版本同樣會放棄。

接著立刻刷新一次面板，馬上顯示新版本；電池供電的 Pi 會在這次刷新後關機。

### 頻道

| 頻道 | 接受 | 適合 |
|---|---|---|
| `stable`（預設） | 正式版 | 朋友的裝置 |
| `beta` | 也接受 pre-release | 維護者自己的裝置 |

每台裝置在 `/opt/e-pages/data/config.local.toml` 個別設定：

```toml
[update]
channel = "beta"      # 或 "stable"
enabled = true        # false：關閉自動更新
```

### 手動檢查與更新

```bash
P="sudo env PYTHONPATH=/opt/e-pages/current/src python3 -m gcal_epd.releases"
$P status               # 目前版本、頻道、上次檢查時間與結果
$P update --check       # 有沒有新版本？
$P update               # 立刻更新（關閉自動更新時也可以）
$P update --channel beta
journalctl -u epd-update -n 50
```

`status` 也會列出被拒絕的版本。要重試某個版本，把它從 `/opt/e-pages/data/update-state.json` 的 `rejected` 中刪除。

### 手動安裝、切換與 rollback

從 checkout 安裝（安裝它已 commit 的 `HEAD`）：

```bash
cd ~/google-calendar-api && git pull
bash deploy/install-release.sh
```

從發布的檔案安裝（同一個 release 的程式碼與 wheels 兩個 tar）：

```bash
mkdir -p /tmp/rel && cd /tmp/rel
tar -xzf e-pages-0.2.0.tar.gz && tar -xf e-pages-0.2.0-wheels-cp313-linux_armv6l.tar
sudo env PYTHONPATH=/tmp/rel/src python3 -m gcal_epd.releases install \
    --source e-pages-0.2.0.tar.gz --wheels wheels --user "$USER"
```

新版本建置期間（Pi Zero 約 5 分鐘），裝置繼續跑舊版本。之後：

```bash
$P list                 # 已安裝的版本，標出 current 和 previous
$P rollback             # 回到上一個版本
$P switch 0.2.0         # 切到任一已安裝的版本
$P prune                # 刪除舊的和未完成的版本
```

`switch` 和 `rollback` 也會用切換過去那個版本的檔案重新安裝 systemd units，讓 units 和程式碼永遠一致。切換在下次刷新或開機時生效。

還在用 git checkout 執行的裝置，用 `bash deploy/install-release.sh --migrate-from ~/google-calendar-api` 搬到這個結構一次即可。在自動更新功能出現前就安裝的裝置，要先手動安裝一次含有這個功能的版本，之後才會自動更新。

---

## 規則與陷阱

| 規則 | 原因 |
|---|---|
| 絕不 commit、印出或記錄 `ics_feeds.toml` 或其中的網址 | 每個網址都是私人日曆的存取憑證 |
| 絕不把簽章私鑰或裝置密碼複製到任何地方 | 私鑰是 release 可信的依據 |
| Wheels 必須是 `linux_armv6l` 或 `any` | ARMv7 的 wheel 在 Pi Zero 上會 "Illegal instruction" 當掉；建置會拒絕它們 |
| 用 Python 的 `tarfile` 打包，不用 Mac 的 `tar` | macOS 會加上延伸屬性和 `._` 檔案 |
| 不要把 `PYTHONPATH` 傳給 release 自己的指令 | 新版本會 import 到安裝程式那份；`installer.child_env()` 會移除它 |
| App 需要 `LG_WD` 指向 `data/` | lgpio 在工作目錄建立 pipe，而 release 目錄是唯讀的 |
| `prepare.sh` 只對從未開機過的卡有效 | cloud-init 每張卡只執行一次 `user-data` |
| `firstboot.sh` 不能依賴網路 | 新裝置在擁有者設定前沒有 Wi-Fi |
