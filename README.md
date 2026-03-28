# TixCraft 票卷監控器

當有票時自動推播 Slack 通知，部署至 GitHub Actions，完全免費免掛機。

## 🚀 特色

- ✅ **完全免費** - 使用 GitHub Actions 排程，無需伺服器
- ✅ **免掛機** - 雲端執行，不影響你的電腦
- ✅ **Slack 通知** - 即時推播票況變化
- ✅ **狀態追蹤** - 只在狀態變化時通知，避免轟炸

## 📋 前提條件

1. GitHub 帳號
2. Slack Workspace (需要建立 Incoming Webhook)
3. 要監控的 TixCraft 活動頁 URL

## 🛠 安裝步驟

### 1. 建立 Slack Incoming Webhook

1. 前往 [Slack API](https://api.slack.com/apps) 
2. 點擊 "Create New App" → "From scratch"
3. 輸入 App 名稱，選擇你的 Workspace
4. 在左側選單點擊 "Incoming Webhooks"
5. 啟用 Incoming Webhooks，點擊 "Add New Webhook to Workspace"
6. 選擇要發送訊息的頻道
7. 複製 Webhook URL (長這樣: `https://hooks.slack.com/services/XXX/YYY/ZZZ`)

### 2. Fork 或建立新 Repo

```bash
# 方式一: 直接使用這個範本
# 點擊 "Use this template" 建立新 repo

# 方式二: Clone 並修改
git clone https://github.com/your-username/tixcraft-monitor.git
cd tixcraft-monitor
```

### 3. 設定 GitHub Secrets

1. 在你的 Repo 頁面，進入 **Settings** → **Secrets and variables** → **Actions**
2. 點擊 **New repository secret**，新增以下兩項:

| Name | Value |
|------|-------|
| `SLACK_WEBHOOK_URL` | 你的 Slack Webhook URL |
| `TIXCRAFT_ACTIVITY_URL` | 要監控的 TixCraft 活動頁 URL |

### 4. 啟用 GitHub Actions

Repo 建立後，GitHub Actions 會自動啟用。

可以在 **Actions** 頁面查看執行日誌。

## ⏰ 執行頻率

預設每 **30 秒**檢查一次。

修改 `.github/workflows/monitor.yml` 中的 cron 表達式:

```yaml
schedule:
  - cron: '*/30 * * * *'  # 每 30 秒
  # - cron: '*/5 * * * *'  # 每 5 分鐘
```

> ⚠️ GitHub Actions 免費版每小時最多 60 次 API 呼叫

## 🧪 測試

本機測試:

```bash
# 複製環境變數範本
cp .env.example .env

# 編輯 .env 填入實際值
vim .env

# 安裝依賴
pip install -r requirements.txt

# 執行
python monitor.py
```

## 📁 專案結構

```
tixcraft-monitor/
├── monitor.py              # 主程式
├── requirements.txt        # Python 依賴
├── .env.example           # 環境變數範本
├── .gitignore             # Git 忽略檔案
└── .github/
    └── workflows/
        └── monitor.yml    # GitHub Actions 工作流
```

## 🔧 自訂

### 修改通知頻道

在 Slack Webhook 設定中選擇不同的頻道，或建立多個 Webhook。

### 修改檢查頻率

編輯 `.github/workflows/monitor.yml`:

```yaml
schedule:
  - cron: '*/60 * * * *'  # 改成每分鐘
```

### 監控多個活動

修改 `monitor.py`，加入多 URL 迴圈:

```python
urls = [
    "https://tixcraft.com/activity/detail/event1",
    "https://tixcraft.com/activity/detail/event2",
]

for url in urls:
    config.tixcraft_activity_url = url
    monitor = TixCraftMonitor(config)
    # ... 監控邏輯
```

## ❓ 常見問題

**Q: 被 Cloudflare 擋住怎麼辦?**
A: GitHub Actions 的 IP 可能被封。可以:
- 降低檢查頻率
- 更換 GitHub Actions 的 runner IP (使用不同的 GitHub-hosted runners)
- 等待一段時間後再試

**Q: 如何確認是否正常運作?**
A: 在 GitHub Actions 頁面查看 workflow 執行日誌，會顯示每次檢查的結果。

**Q: 可以監控其他票務平台嗎?**
A: 可以，修改 `monitor.py` 中的解析邏輯，針對不同網站調整 HTML 選擇器。

## ⚠️ 免責聲明

本工具僅供學習研究用途。請遵守:
- 網站的使用條款
- 當地法律法規
- 不要用於黃牛行為

## 📜 License

MIT License
