# 網站更新監測系統（AI Agent 版）

這個專案的目標很簡單：  
**幫你自動盯網站有沒有更新，並把變更整理成看得懂的重點。**

你可以新增任何想追蹤的網址，設定「想看哪個區塊」，系統就會定時抓取、比對、記錄，必要時寄通知。

---

## 這個專案可以做什麼

- 會員註冊 / 登入後管理自己的追蹤清單
- 新增追蹤網址，指定要監看的區塊（例如：最新公告、新聞列表、法規頁面）
- 系統排程自動檢查，偵測內容是否變更
- 產生差異摘要（不是只有 raw diff，會盡量整理成可讀敘述）
- 在儀表板查看歷史快照與變更紀錄
- 可選擇啟用 Email 通知（SMTP）
- 支援 `Gemini` / `Hugging Face` 作為 LLM 提供者

---

## 專案架構（先看這段就懂）

整體是「Flask 後端 + HTML/JS 前端 + SQLite」：

1. 前端介面讓使用者管理訂閱與查看更新結果  
2. 後端排程器定時執行每個訂閱的抓取與比對  
3. 抓取結果存成快照（Snapshot）  
4. 有變更時產生通知內容，寫入資料庫並可發信

### 主要目錄

```text
.
├── app.py
├── backend/
│   ├── models/                  # User / Subscription / Snapshot / Notification
│   ├── routes/                  # 登入、訂閱、頁面 API
│   ├── scheduler.py             # 排程與檢查主流程
│   └── services/
│       ├── scraper.py           # 抓頁 + 抽取內容 + fallback
│       ├── page_target_agent.py # Agent 3：頁面理解與目標對位
│       ├── gemini_service.py    # Agent 1：依指令擷取監看內容
│       ├── change_agent.py      # Agent 2：變更比對與摘要
│       ├── llm_narrative.py     # 將機械摘要改寫成自然語言
│       └── ...                  # 各站點專屬 monitor/diff agents
└── frontend/
    ├── templates/
    └── static/
```

---

## 使用方式（第一次用照著做）

### 1) 安裝與啟動（Windows PowerShell）

```powershell
git clone https://github.com/En0526/PwC_project_final.git
cd PwC_project_final

python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt

Copy-Item .env.example .env
python app.py
```

啟動後開啟：<http://127.0.0.1:5000>

> 如果 `Activate.ps1` 被擋，先執行：  
> `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`

### 2) 實際操作流程

1. 註冊 / 登入帳號  
2. 新增一筆追蹤網址  
3. 輸入「要觀看的區塊描述」（可空白）  
4. 設定檢查頻率  
5. 等排程或手動觸發檢查  
6. 在儀表板查看是否有變更與摘要內容

### 3) 重要：`.env` 設定（AI 功能需 Key）

> **提醒：要使用 AI 擷取與 AI 摘要，必須先設定 API Key。**  
> 沒有設定 Key 時，系統仍可運作，但會改用較基礎的文字比對（不啟用 AI）。

- `AI_PROVIDER=gemini` 或 `huggingface`
- `GEMINI_API_KEY`：使用 Gemini 時必填
- `HF_API_TOKEN`：使用 Hugging Face 時必填
- `CHECK_INTERVAL_MINUTES`：預設檢查頻率
- `SMTP_HOST`、`SMTP_FROM`、`SMTP_PASSWORD`：啟用 Email 通知
- `SMTP_FROM`：寄件者地址（必填，建議與 `SMTP_USERNAME` 相同）
- `AUTO_SEND_NOTIFICATION_REPORT=1`：有更新時自動寄送彙整信

範例（擇一）：

```env
# 使用 Gemini
AI_PROVIDER=gemini
GEMINI_API_KEY=your_gemini_key

# 或使用 Hugging Face
# AI_PROVIDER=huggingface
# HF_API_TOKEN=your_hf_token

# Email（Gmail 範例）
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=your_email@gmail.com
SMTP_PASSWORD=your_16_digit_app_password
SMTP_FROM=your_email@gmail.com
AUTO_SEND_NOTIFICATION_REPORT=1
```

---

## 功能重點（給第一次接手的人）

- **訂閱管理**：每位使用者有自己的監測清單與設定
- **多種來源處理**：一般 HTML、RSS/Atom、以及部分站點專屬解析流程
- **反爬/動態頁 fallback**：requests 失敗可切 Playwright，降低抓不到內容的機率
- **差異判斷與去重**：用內容 hash + diff 判斷是否真的有更新，避免重複通知
- **通知機制**：變更寫入 Notification，可彙整並寄送 Email
- **歷史可追溯**：每次抓取保留 Snapshot，可回看前後變化

---

## 核心所在：三個 AI Agent

這個專案最核心的設計，是把「看網頁更新」拆成 3 個 AI Agent，各自做不同工作：

### Agent 1：網頁區塊擷取 Agent（Extraction）

- 位置：`backend/services/gemini_service.py`
- 任務：根據使用者描述，從整頁文字中擷取「真正要監看」的內容
- 輸出：一段可穩定比對的監看文本（供快照與 hash）

### Agent 2：變更比對解讀 Agent（Change Reporter）

- 位置：`backend/services/change_agent.py`
- 任務：比較前後快照，產生可讀的更新重點（含站點專屬 diff 策略）
- 輸出：通知可直接使用的變更摘要（必要時再交給敘事改寫）

### Agent 3：頁面理解與目標對位 Agent（Page Target Resolver）

- 位置：`backend/services/page_target_agent.py`
- 任務：先理解頁面有哪些區塊，再把使用者目標對位，產生更精準的擷取指令給 Agent 1
- 輸出：`extraction_instruction`（提升擷取精準度，降低抓錯區塊）

### 三者怎麼串起來

`Agent 3（先理解頁面）` → `Agent 1（擷取要監測的內容）` → `Agent 2（比對並寫成摘要）`

這樣的好處是：  
不是只做「字串 diff」，而是更接近「人真的在看公告更新」的流程。

---

## 常見問題

**Q：5000 埠被佔用怎麼辦？**  
改 `app.py` 的啟動埠（例如 `5001`）。

**Q：Playwright 相關套件安裝失敗？**  
可先跑核心功能；需要動態頁時再執行 `playwright install chromium`。

**Q：第一次啟動需要手動建資料庫嗎？**  
不用。首次啟動會自動建立 `instance/site.db`。
