# PROGRESS

> 每完成 SPEC §13 的一步就更新此檔。這是跨 session 的記憶,不要省略。

---

## 目前狀態

**Step 2 CONDITIONAL 補修完成,待審查複核。**

下一步:審查通過後進入 SPEC §13 **Step 3 — 集保 provider (FinMind) + 解析 + PIT 對齊**

DoD:可取得任一股票 3 年還原日線;`tests/test_pit.py` 通過

---

## 已完成步驟

| Step | 內容 | 完成日 | DoD 達成 | Commit |
|---|---|---|---|---|
| 1 | 專案骨架、config schema、CLI 空殼 | 2026-08-18 | 是 | `step-1: initialize project skeleton` |
| 2 | 資料層:FinMind provider + Parquet 快取 + 交易日曆 + 除權息還原 | 2026-08-19 | 是 | `step-2: implement FinMind data layer`;`step-2: fix FinMind batching safeguards` |

---

## 跳過或簡化的部分

> 誠實記錄。這一欄是審查時的第一個檢查點。

| Step | 跳過了什麼 | 原因 | 是否需補做 |
|---|---|---|---|
| 1 | 資料 provider、PIT 過濾、因子、評分、planner、manifest、forward log | Step 1 只要求骨架、config schema、CLI 空殼；不得跳到後續步驟 | 是，依 SPEC §13 後續步驟補做 |
| 1 | §14 的實際帳戶規模與 `top_n` 決策 | Step 1 只建 schema 與 SPEC §11 範例 config；實際策略決策尚未到相應實作步驟 | 是，進入 planner/評分實作前確認 |
| 1 | SPEC §3 的 `data/`、`universe/`、`factors/`、`scoring/`、`planner/`、`record/`、`report/` 與 `tests/fixtures/` 未建立 | Step 1 的 DoD 是可執行 CLI 與 config schema；這些模組若空殼建立反而容易造成假完成感 | 是，依 Step 2 起各自實作時建立；`tests/fixtures/` 於第一個 golden fixture 測試步驟建立 |
| 1 | `configs/base.yaml` 與 `configs/logging.yaml` 目前是佔位空殼、無程式讀取 | Step 1 只建立檔案位置；base/market 合併規則尚未在 SPEC §13 Step 1 要求 | 是，預計在 Step 2 接資料層 CLI/config 流程時先定義讀取邊界，完整 base/market 合併規則在 Step 8 評分執行前完成 |
| 1 | 尚未對 `factors/`、`scoring/`、`planner/` 建立分區 85% coverage gate | 這三個目錄尚未建立；目前 `pyproject.toml` 的 `fail_under = 80` 只作為全套件 Step 1 aggregate baseline | 是，對應模組建立後補上分區門檻或 CI 檢查 |
| 2 | 集保股權分散 provider (`TaiwanStockHoldingSharesPer`) 與級距解析 | SPEC §13 修訂版將集保列為 Step 3；本步不得提前做 | 是，Step 3 補做 |
| 2 | `MetaProvider.get_listings()` 的完整 PIT 股票池重建 | Step 2 聚焦資料取得、快取、交易日曆與還原價；`TaiwanStockInfo` 快照配合下市清單重建 universe 屬 Step 4 | 是，Step 4 補做 |
| 2 | TWSE / TPEx 注意股、全額交割股補充來源 | Step 2 僅接 FinMind 資料層；PROGRESS #13 已裁定缺口需另尋官方來源 | 是，Step 4 L1 gate 前補做 |
| 2 | `symbol_map.parquet` 未建立 | SPEC §4.2 #3 要求記錄符號變更與合併映射；Step 2 尚未接到可驗證的官方符號事件來源，建立空表會讓歷史 symbol 對齊看似完成 | 是，Step 4 universe/PIT listings 重建前補做 |
| 2 | `securities_lending_balance` 目前回傳 `null` | `TaiwanStockSecuritiesLending` 免費層可取得，但實測欄位是借券交易明細，不是日末餘額；無期初餘額時不得把區間淨額偽造成 balance | 是，使用此欄位前需決定可驗證餘額來源或長歷史重建方法 |

---

## 待人類決定(對應 SPEC §14)

| # | 事項 | 狀態 | 決定(2026-08-18 由使用者裁定) |
|---|---|---|---|
| 1 | 帳戶規模 `account.value` | **已決定** | `account.value = 1,000,000`(NT$),使用者確認為實際可交易金額。並**允許零股**:SPEC §8.5 的 `floor(.../1000)×1000` 整張限制取消(SPEC 已於 2026-08-18 修訂) |
| 2 | 集保歷史深度 | **已決定(選項 A)** | **改用 FinMind `TaiwanStockHoldingSharesPer` 取得集保股權分散表**(2010-01-29 起,Backer/Sponsor 層)。集保官網爬蟲降級為 Phase 2 備援,不在 Phase 1 實作。SPEC §4.4 與 §13 Step 3 需依此修訂 |
| 3 | 下市股票清單來源 | **已決定** | 使用 FinMind `TaiwanStockDelisting`(2001-01-01 起,免費層)。**不接受倖存者偏差**,universe 必須納入已下市股票 |
| 4 | 產業分類 | **已決定** | Phase 1 使用 TWSE 官方分類(來源 `TaiwanStockInfo` 的產業別欄位)。自訂主題分類延後,不在 Phase 1 |
| 5 | 是否納入興櫃 | **已決定** | 排除。維持 config `gates.l0.exclude_markets: [EMERGING]` |
| 6 | `top_n` 是否為 30 | **已決定** | 維持 30 |
| 7 | 憑證管理(SPEC 未涵蓋,新增) | **已決定** | FinMind token 走環境變數 `FINMIND_TOKEN`,本機以 `.env` 載入(已加入 `.gitignore`)。**絕不得寫入 YAML config**——SPEC §9.1 的 `config_snapshot` 會將整份 config 明文寫入 manifest。缺 token 時啟動即中止並報錯,不得降級繼續 |
| 8 | SPEC §6.2 集保 tier 編號錯誤(新增) | **已決定** | SPEC 原表 tier 編號與集保官方差 1,且與同節 `retail_pct = tier 1..3` 自相矛盾。**SPEC §6.2 已於 2026-08-18 修訂**:改以級距的**股數下界**判定(`big_holder_pct` 取 `lower >= 400_001`、`retail_pct` 取 `lower <= 5_001`),不再依賴任何 tier 序號,「合計」列須排除 |
| 9 | **G1** `shares_outstanding` FinMind 無對應 dataset | **已決定** | **雙推導交叉驗證**:(a) `TaiwanStockBalanceSheet` 普通股股本 ÷ 面額 10 元;(b) `TaiwanStockMarketValue` ÷ 收盤價。兩者差異超出容忍範圍時**報錯**,不得任選其一靜默使用。PIT 要求:取 `as_of` 當時的值,不是最新值 |
| 10 | **G2** 會計師意見 FinMind 無資料 | **已決定** | **Phase 1 不實作**,明確記錄為已知缺口。L1 的「會計師意見非無保留 → 排除」該條停用,不得以任何預設值假裝有跑 |
| 11 | **G3** 財報延遲申報 FinMind 無直接欄位 | **已決定** | **另尋 TWSE 來源**(公開資訊觀測站)。在來源接上前,該條 L1 停用並記錄 |
| 12 | **G4** 董監質押比 FinMind 無資料 | **已決定** | **Phase 1 不實作**,明確記錄為已知缺口。該條原本即為「標記」而非「排除」,影響較小 |
| 13 | **G5** 注意股 / 全額交割股 FinMind 僅有處置股 | **已決定** | 處置股用 `TaiwanStockDispositionSecuritiesPeriod`;注意股與全額交割股**另尋 TWSE / TPEx 來源**。在來源接上前,L1 僅攔截處置股並記錄缺口 |
| 14 | **集保資料 2016 年前為月頻**(2026-08-19 實測發現) | **已決定** | 實測 2330:2010–2015 為月頻(每月最後營業日),2016 起才是週頻。C05 的 `slope_weeks: 8` / `zscore_weeks: 52` 假設週頻,`as_of < 2016` 時語意錯誤但不會報錯。實際可用起點為 2016-01,早於此日期 C05 應回傳 null 並記錄。詳見 `docs/FinMind_API_Inventory.md` §4.1 |
| 15 | **FinMind 財報無公布日欄位**(2026-08-19 實測確認) | **已決定** | 實測回傳欄位僅 `date`(期別)/`origin_name`/`stock_id`/`type`/`value`。`publish_date` 須自行推導,**Q4 用 +75 天**而非 +45 天。此為 Phase 1 最大 PIT 風險點,Step 2 須以 Review Protocol §2.1 方法驗證。財報為 long format,Altman Z / Beneish M 輸入需先 pivot |
| 16 | FinMind 訂閱方案 | **已決定** | **Backer($699/月)**。2026-08-19 實測 17 個 Phase 1 dataset 全部可存取。$999 多的分點/分K/即時報價 Phase 1 均用不到(SPEC §4.4 明列分點不實作)。速率 1,600 req/hr,**回補必須按日期批次下載,不得逐檔查詢** |

> **G2/G4 的副作用(審查時必讀):** L1 少掉兩條排除條件,實際攔截檔數會低於 SPEC §5.2 預期的 50–150 檔。
> 這是已知且已接受的缺口,**不得為了把數字湊回預期區間而放寬其他 L1 門檻**——那違反 SPEC §15 第 8 條。

---

## 已知問題

| # | 問題 | 影響範圍 | 狀態 |
|---|---|---|---|
| 1 | `flowscope.exe` 安裝於 user Scripts 目錄，但該目錄目前不在系統 `PATH` | 直接在新 shell 執行 `flowscope` 可能找不到命令；本次以臨時加入 `%APPDATA%\Python\Python313\Scripts` 驗證 entry point | 已記錄 |
| 2 | 還原股價 `TaiwanStockPriceAdj` 由 FinMind 以最新除權息回算,**疑似 PIT 洩漏** | 所有技術面因子 | Step 2 已處理:探測顯示不同 `end_date` 的重疊區間報酬率相同,但 API 無歷史 `as_of` 快照可證明基準日；正式 provider 不採用 `TaiwanStockPriceAdj`,改用原始價 + `TaiwanStockDividendResult` 且還原事件截止日不晚於查詢 `end/as_of` |
| 3 | 集保頻率 2016 年前為月頻 | C05 及整個籌碼維度 | 見待決表 #14,實際可用起點暫定 2016-01 |
| 4 | SPEC §4.2 第 1 點原寫「還原以最新價為基準」,與 Review Protocol §2.1 將最新基準列為 PIT 洩漏風險相矛盾 | 還原價實作依據與後續審查口徑 | 已由使用者裁定並修訂 SPEC §4.2:改為 `as_of` 基準；Step 2 provider 已採用原始價 + `TaiwanStockDividendResult` 自行 backward adjustment,且除權息事件截止日不得晚於 `as_of` |
| 5 | 全市場回補時間受 FinMind Backer 1,600 req/hr 限制 | 初次建置資料湖與 `--no-cache` 大範圍重抓 | 粗估 3 年全市場 Step 2 來源約 11,900 requests、至少 7.5 小時:日頻 bulk 4 個 dataset 約 2,920 requests/1.8 小時；財報三表逐檔約 5,400 requests/3.4 小時；股利與月營收逐檔約 3,600 requests/2.3 小時。實際時間會因重試、限流與快取命中率增加或減少 |

---

## 審查紀錄

| 日期 | Step | 判定 | 主要 blocking 項 |
|---|---|---|---|
| 2026-08-18 | 1 | CONDITIONAL | 需補跳過揭露、factor params 驗證、distribution warning 門檻驗證 |
| 2026-08-19 | 2 | CONDITIONAL | 需補多檔逐日期抓取、財報逐檔抓取、法人欄位改名防呆、借券餘額揭露、SPEC §4.2 矛盾揭露 |
