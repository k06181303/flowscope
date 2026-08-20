# PROGRESS

> 每完成 SPEC §13 的一步就更新此檔。這是跨 session 的記憶,不要省略。

---

## 目前狀態

**Step 4 已通過審查；進入 Step 5 前處理非阻擋建議。**

下一步:完成財報快取/PIT 日期前置修正後進入 SPEC §13 **Step 5 — 技術面因子 T01–T21**

DoD:輸出 §5.3 格式的漏斗;L0/L1 各關剩餘檔數合理。交付指令 `flowscope diagnose funnel --as-of 2026-08-20 --price-as-of 2026-08-19 --warnings-snapshot today` 可明示資料截止日、最近已完成交易日與 current warning snapshot。2026-08-20 實跑全市場:1,985 → L0 749 → L1 525。L1 逐關為 warnings 749→720、TTM Altman 720→639、跨會計年度 negative OCF streak 639→525；capital raise 明示 `skipped (no data)`。

---

## 已完成步驟

| Step | 內容 | 完成日 | DoD 達成 | Commit |
|---|---|---|---|---|
| 1 | 專案骨架、config schema、CLI 空殼 | 2026-08-18 | 是 | `step-1: initialize project skeleton` |
| 2 | 資料層:FinMind provider + Parquet 快取 + 交易日曆 + 除權息還原 | 2026-08-19 | 是 | `step-2: implement FinMind data layer`;`step-2: fix FinMind batching safeguards` |
| 3 | 集保 provider (FinMind) + 解析 + PIT 對齊 | 2026-08-19 | 是 | `step-3: implement FinMind holder distribution`;`step-3: tighten holder data safeguards` |
| 4 | Universe + L0/L1 Gate + 漏斗輸出 | 2026-08-20 | 是 | `step-4: implement universe gates and funnel`;`step-4: fix financial gates and industry split`;`step-4: correct quarterly financial gate semantics`;`step-4: fix funnel snapshot dates and OCF streak`;`step-4: harden cache and PIT date guards` |

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
| 3 | 集保官網爬蟲與原始 HTML/CSV 保存 | SPEC 已於 2026-08-18 修訂:Phase 1 集保來源改為 FinMind `TaiwanStockHoldingSharesPer`;集保官網爬蟲降級 Phase 2 備援 | 否，除非 Phase 2 啟用備援爬蟲 |
| 3 | C01–C17 籌碼因子計算 | Step 3 只做資料層、解析與 PIT 對齊；SPEC §13 將籌碼因子列為 Step 6 | 是，Step 6 補做 |
| 3 | 自動化對照集保官網近期頁面 | 本步已保留 FinMind 原始 JSON 並以真實 API 驗證級距解析與比例合計；官方網站人工抽查屬審查手動驗算項，尚未寫入自動測試 | 建議 Step 3 審查時由審查者抽查近 3 週 `big_holder_pct` |
| 4 | `data/processed/symbol_map.parquet` 尚未建立 | Step 4 已可用官方 TWSE/TPEx OpenAPI 建構 current-as-of universe；但 SPEC §4.2 #3 的代號變更/合併映射需要可驗證的官方事件來源。FinMind `TaiwanStockDelisting` 只有下市日與代號,不足以重建改名/合併映射；建立空 parquet 會造成假完成感 | 是，接歷史回測/manifest 前必須補官方 symbol event source 並寫入 parquet |
| 4 | 歷史 as_of 的完整 PIT universe 尚未完成 | TWSE/TPEx 官方上市櫃清單是目前快照；可支援 `as_of` 當日 active listing 篩選,但無法還原已下市且仍在歷史 as_of 活躍的股票之 listing_date/industry。`TaiwanStockDelisting` 可補下市日,但缺 listing_date/industry 歷史 | 是，Step 5 前若只跑 current-as-of 可接受；進入任何歷史回測或 forward log 驗證前必補 |
| 4 | L1 的會計師意見、財報延遲申報、董監質押比未實作 | 待決表 #10/#12 已裁定 Phase 1 不實作會計師意見與董監質押；#11 尚待接公開資訊觀測站來源。不得用預設值假裝通過 | 是，#11 在接來源後補；#10/#12 依 Phase 1 裁定維持揭露缺口 |
| 4 | Beneish M-score 只標記缺資料,尚未計算 | SPEC §5.2 說 Beneish 是 flag 非 exclusion；完整 M-score 需要跨期財報欄位與 Step 7 財務因子資料整理。目前缺輸入時輸出 `null` 並設 `beneish_m_unavailable` | 是，Step 7 財務因子補齊跨期輸入後實作 |
| 4 | `capital_raise` gate 暫停顯示為 active step | FinMind 三表目前未提供可直接驗證的「一年內現金增資規模」欄位；用股本或資本公積變化會混入非現金/股票股利等事件,不符合 SPEC 的現金增資語意 | 是，找到 MOPS/TWSE 可驗證現金增資來源後補；在此之前不得顯示成刷 0 檔的 gate |
| 4 | 「資料完整度 >= 門檻」階段目前是 pass-through | Step 8 才會有因子 raw/normalized 值與 missing ratio,Step 4 尚無資料完整度可計算 | 是，Step 8 scoring/missing 處理完成後接上 |
| 4 | L0 `security_type` / `exclude_markets` 兩關目前實測各刷 0 檔 | 官方 listing provider 未納入 ETF/ETN/REIT/特別股與興櫃；但 TWSE 產業代碼 91 的 10 檔 TDR 目前被錯標為 `COMMON_STOCK`。實測 TDR 均未通過成交金額 gate，故現行漏斗結果不受影響，但 `security_type` 語意仍不完整 | 是，接可驗證的證券類型來源後將 TDR 標為 `TDR`，由既有 `security_type` gate 排除 |
| 4 | 歷史 `as_of` 的注意股/處置股/全額交割股完整 PIT 名單 | TWSE/TPEx altered-trading 端點包含無日期的當前 snapshot，無法證明歷史狀態；目前 `as_of < today` 會中止並報錯，不再把今天名單回套歷史 | 是，進入歷史回測前需接官方歷史公告 archive；未接前僅允許 current-as-of warning gate |
| 4 | 移除 TWSE/TPEx OpenAPI SSL 失敗時的未驗證憑證 fallback | Windows 本機信任鏈實測無法驗過部分官方端點；stdlib 沒有可攜的指定 CA bundle，而新增 `certifi` 等依賴依 CLAUDE.md 必須先取得人類同意。本步只揭露風險，不靜默宣稱 TLS 已驗證 | 是，正式部署前由人類決定受信任 CA bundle/企業憑證來源，改用 `ssl.create_default_context(cafile=...)` 後移除 `_create_unverified_context()` |

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
| 17 | **G6** `securities_lending_balance` FinMind 無日末餘額(2026-08-19 實測確認) | **已決定** | `TaiwanStockSecuritiesLending` 欄位為 `transaction_type`/`volume`/`fee_rate`/`original_return_date`,是逐筆借券交易明細,非日末餘額;無期初餘額不得推導。**決定:另尋 TWSE 借券餘額來源**。在來源接上前 `get_margin` 的此欄位維持 `null` 並記錄,不得以明細淨額偽造 |

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
| 6 | 集保全市場回補需用逐資料日 bulk,不可逐檔 | Step 3 holder provider | 實測 `TaiwanStockHoldingSharesPer data_id=None` 只回 `start_date` 當日全市場。實作採單檔區間請求；多檔先用第一檔找出資料日,再逐資料日 bulk。2 年全市場約 100–110 個 holder data-date requests,Backer 1,600 req/hr 下約 4–5 分鐘,另加一次 seed request與重試/快取開銷 |
| 7 | `shares_outstanding` 交叉驗證容忍值原本固定 0.5% 並直接 raise | Step 2 price provider | 已修正:差異 ≤ 0.5% 時採 balance sheet 股本；差異 > 0.5% 時發出 `RuntimeWarning` 並改用同日 `TaiwanStockMarketValue / close` 的 PIT 推導值,避免季中資本變動被季報股本延遲誤殺 |
| 8 | 舊 cache 目錄 `data/raw/finmind/finmind/` | 本機資料目錄 | 已確認不存在(`Test-Path` 回傳 `False`)。這是舊版 cache root bug 產物,目前程式不會再產生 |
| 9 | TWSE OpenAPI 部分資料集回傳 mojibake 欄位名 | 官方上市櫃清單與財報 snapshot parser | 已處理:正常中文/英文 key 優先,若不存在則依官方欄位順序 fallback；測試覆蓋 mojibake/位置 fallback |
| 10 | 官方財報 OpenAPI 只提供目前 snapshot,不提供歷史季度查詢 | 歷史 `as_of` 的 Altman Z L1 gate | 已修正:Step 4 L1 財務來源改用 FinMind `get_financials()` long format pivot,沿用 Step 2 Q4 +75d / 其餘 +45d 的 `publish_date` 推導；TWSE/TPEx official provider 僅保留 listing/warnings |
| 11 | 非製造業分類原本只命中 `17` 金融保險 | Altman Z'' 分流 | 已修正:TWSE/TPEx 分別建立非製造業代碼表,涵蓋 14/15/16/17/18/20/23/29/30/32/34/36/37/38；`as_of=2026-08-19` current listing 命中 548/1,985 = 27.6% |
| 12 | 全市場預設 L1 改用 FinMind 財報後,首次無快取執行成本很高 | Step 4 全市場執行 | FinMind 三個財報 dataset 實測 `data_id=None` 皆回 0 筆,必須逐檔抓。每檔獨立落盤避免中途失敗歸零；快取 key 已由精確日期改成季度邊界，同一已結束財報期內相鄰 `as_of` 共用快取，回傳前仍依原始 `start/end` 與 `publish_date <= as_of` 過濾。首次建立新季度 key 仍約 2,247 requests，之後日常執行不再每日全量重抓 |
| 13 | FinMind 財報與官方 OpenAPI 財報單位不同 | Altman X4 | 已修正:Step 4 既已改用 FinMind 財報,市值與財報都用元級,不再將 `market_value` 除以 1,000。單檔 smoke 確認 2330 不再被 Altman 單位錯誤剔除 |
| 14 | FinMind 現金流量表是年初至今累計值 | L1 negative OCF | 已修正:同一會計年度內先差分成單季,Q1 採原值,Q2–Q4 減前季累計；差分完成後負季 streak 在完整季度序列上計算,可跨會計年度。全市場分布為 0/1/2/3/4/5/6/7 季 = 490/115/83/22/20/5/7/7；L1 negative OCF 639→525。真實 2399 最新單季 `-117,580 - (-122,108) = +4,528`,仍正確為 0 |
| 15 | FinMind 損益表是單季值,Altman X3/X5 要年度值 | L1 Altman Z | 已修正:EBIT 與 Revenue 使用最近連續四季 TTM 加總；不足四季回傳 null。真實 2439 TTM Z=`2.385808`,不再被單季 Z=`1.342` 誤剔除 |
| 16 | 官方 warning 無日期 snapshot 原本被標成查詢 `as_of` | 歷史 L1 warning gate | 已修正:dated endpoint 缺日期會報錯；無日期 snapshot 僅允許 current snapshot,歷史查詢仍中止。漏斗新增獨立 `price_as_of` / `warnings_snapshot`，交付指令明示 `as_of=2026-08-20`、價量 `2026-08-19`、warning snapshot `2026-08-20`，輸出同步標註三者，未將 current snapshot 偽裝成歷史 PIT |
| 17 | Official OpenAPI client 在 Windows 憑證鏈失敗時使用 `ssl._create_unverified_context()` | 官方 listing/warning 傳輸安全 | 已揭露於跳過表；未新增 SPEC 未列依賴。正式部署前必須由人類指定受信任 CA bundle/企業憑證來源並移除未驗證 fallback |
| 18 | 全市場 L1 剔除 224 檔，高於 SPEC §5.2 預期的 50–150 檔 | Universe 漏斗 | 不調整 gate 參數；warning 29、Altman 81、negative OCF 114 的資料語意已驗證。依禁止事項不得為湊區間改門檻，留到 Step 12 sensitivity 分析 |
| 19 | TWSE OpenAPI 大型 listing payload 曾發生 `IncompleteRead` | current universe/漏斗交付指令 | 已修正:截斷回應只重試一次；第二次仍截斷或請求失敗時轉成 `OfficialMarketDataError` 中止並報錯，不回傳部分資料或空 DataFrame |
| 20 | 財報快取原本綁定精確 `start/end`，相鄰 `as_of` 無法重用 | 每日漏斗、Step 11 回填、Step 12 敏感度 | 已修正:請求與 key 對齊季度邊界；季度推導公布期限前每日刷新、期限後視為固定資料。測試確認 8/19 與 8/20 共用同一份逐符號快取，且 PIT/查詢區間過濾仍套用 |
| 21 | `warnings_snapshot > as_of` 原本可由 stub provider 繞過 | builder PIT 邊界 | 已修正:builder 增加對稱守衛並拋 `UniverseGateError`；官方 provider 仍額外要求 snapshot 必須等於執行日 |
| 22 | listing snapshot 原用 `as_of`，L0 價量使用 `latest_trade_date` | 新上市股票的 L0 語意 | 已修正:listing 與 L0 均以實際 `latest_trade_date` 為基準，避免兩日期間新上市但尚無價量的股票混入初始 universe |
| 23 | TWSE 產業代碼 91 的 TDR 被標為 `COMMON_STOCK` | L0 security type | 已揭露:目前 10 檔實測均在成交金額 gate 被剔除，現行結果不變；尚未接可驗證的 security type source，不以產業代碼自行偽造完整類型映射 |

---

## 審查紀錄

| 日期 | Step | 判定 | 主要 blocking 項 |
|---|---|---|---|
| 2026-08-18 | 1 | CONDITIONAL | 需補跳過揭露、factor params 驗證、distribution warning 門檻驗證 |
| 2026-08-19 | 2 | CONDITIONAL | 需補多檔逐日期抓取、財報逐檔抓取、法人欄位改名防呆、借券餘額揭露、SPEC §4.2 矛盾揭露 |
| 2026-08-19 | 3 | 待審查 | 已補 FinMind 集保 provider、原始 JSON 保存、級距下界解析、比例合計標記、公布日交易日對齊與日頻 PIT forward fill；Non-blocking 建議已補 raw payload 去重、日頻對齊向量化、seed/bulk 日期網格防呆、重複抓價與 adjustment loop |
| 2026-08-19 | 4 | 待審查 | 已補 official market provider、L0/L1 gate、funnel CLI 與測試；已揭露 symbol_map、完整歷史 PIT universe 與部分 L1 資料源缺口 |
| 2026-08-19 | 4 | CONDITIONAL | 需補非製造業代碼表、L1 改用 FinMind 財報、negative OCF 真正接現金流量表、揭露 capital_raise/資料完整度/L0 零刷關卡 |
| 2026-08-20 | 4 | CONDITIONAL | 需補 cumulative OCF 單季差分、Altman X3/X5 TTM、歷史 warning snapshot 中止、no-data gate 明示 skipped、移除死常數與財報 pivot 向量化，並重跑全市場 L1 |
| 2026-08-20 | 4 | CONDITIONAL | 需拆分價量截止日與 current warning snapshot，讓單一 CLI 指令可重現且明示混合日期；negative OCF 差分後的 streak 必須跨會計年度；另揭露未驗證 SSL fallback |
| 2026-08-20 | 4 | PASS | funnel 單一指令與三日期標註、OCF 五個跨年/反向案例及全市場 0–7 季分布均由審查者獨立驗證通過；可進 Step 5 |
