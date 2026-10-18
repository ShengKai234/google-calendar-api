[English](README.md) | **繁體中文**

# 可直接燒錄的映像檔

`image/` 會把官方的 Raspberry Pi OS Lite 映像檔，做成已經裝好日曆的版本：系統套件、`.venv`、systemd 服務、SPI 和 watchdog 全部設定完成。燒錄、開機後，面板會直接進入 Wi-Fi 設定 —— 不需要 SSH、不需要跑 `setup.sh`，Pi 上也不用下載任何東西。

---

## 發布

```bash
git tag v1.0.0
git push origin v1.0.0
```

**Release image** 這個 workflow（`.github/workflows/release-image.yml`）會先跑測試，再建置映像檔，最後發布一個 GitHub Release，附上 `e-pages-v1.0.0.img.xz` 和它的 `.sha256`。從 Actions 頁面手動執行時只會建置、不會發布，映像檔會以 artifact 保留 7 天。

## 在本機建置

需要 Docker（Mac 上的 Docker Desktop 即可）。

```bash
bash image/build-in-docker.sh
# → image/dist/e-pages-<git describe>.img.xz
```

只會放入已 commit 的檔案。`WIFI_COUNTRY=JP` 可改 Wi-Fi 的法規國家（預設 `TW`）；`VERSION=…` 決定檔名。

## 燒錄

在 Raspberry Pi Imager 選 **Use custom**，再選這個 `.img.xz`。OS customisation 可以不填：日曆不需要登入用的帳號。只有想登入維護時，才需要加帳號和 SSH。

---

## 建置做了什麼

| 步驟 | 內容 |
|------|------|
| 基底 | 下載 `base.env` 指定的版本，並檢查 SHA-256 |
| 擴大 | 根分割區多加 768MB（Pi 第一次開機時會再擴大到整張卡） |
| 套件 | `watchdog`，以及 piwheels 的 Pillow wheel 需要的函式庫 |
| 程式 | 這個 commit 的程式，放在 `/opt/e-pages`，擁有者是系統帳號 `epd`（屬於 `spi`、`gpio` 群組） |
| `.venv` | 在 ARMv6 的 chroot 裡建置（`QEMU_CPU=arm1176`），pip 才會選 Pi Zero 能跑的 wheel |
| 服務 | 原封不動執行 `deploy/install.sh`，只是把 `sudo` 和 `systemctl start` 換成 chroot 用的替身 |
| 開機 | `dtparam=spi=on`；在核心參數設定 Wi-Fi 國家；開熱點前先 `rfkill unblock wifi` |

程式放在 `/opt/e-pages` 而不是家目錄，是因為映像檔裡還沒有使用者 —— 如果有要求，Imager 會在第一次開機時才建立。

要換成較新的 Raspberry Pi OS，請同時更新 `base.env` 的兩行。
