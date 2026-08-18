# FinMind API 對照表 — Phase 1

> **用途:** SPEC 的資料需求 → FinMind dataset 的完整對照。Step 2 起實作資料層時依此建 provider。
> **地位:** 本文件為**查證紀錄與實作對照**,不取代 SPEC。與 SPEC 衝突時,以 SPEC + `PROGRESS.md` 的人類裁定為準。
> **查證日:** 2026-08-18
> **來源:** FinMind 官方文件 <https://finmind.github.io/tutor/TaiwanMarket/DataList/>

---

## 0. 認證

| 項目 | 決定 |
|---|---|
| 憑證 | FinMind token,**僅**經環境變數 `FINMIND_TOKEN` 讀取 |
| 本機載入 | `.env`(已列入 `.gitignore`);版控只放 `.env.example` 範本 |
| 禁止 | **絕不寫入 YAML config**。SPEC §9.1 的 `config_snapshot` 會把整份 config 明文寫進每次執行的 `manifest.json` |
| 缺 token 行為 | 啟動即中止並報錯。不得降級為「無資料繼續跑」 |
| manifest 記錄 | 只記錄 token 是否存在,**不記錄值** |
| 方案層級 | Phase 1 需要 **Backer / Sponsor** 層(見 §2 標註)|

速率限制:免費層約 600 requests/hour。所有 provider 必須先查本地 Parquet 快取(SPEC §4.3),避免重複請求。

---

## 1. Phase 1 必用 API

| SPEC 需求 | Dataset | API function | 起始日 | 層級 |
|---|---|---|---|---|
| OHLCV 原始價 | `TaiwanStockPrice` | `taiwan_stock_daily()` | 1994-10-01 | 免費 |
| **還原股價** | `TaiwanStockPriceAdj` | `taiwan_stock_daily_adj()` | 1994-10-01 | **Sponsor** |
| 三大法人買賣超 | `TaiwanStockInstitutionalInvestorsBuySell` | `taiwan_stock_institutional_investors()` | 2005-01-01 | 免費 |
| 融資融券 | `TaiwanStockMarginPurchaseShortSale` | `taiwan_stock_margin_purchase_short_sale()` | 2001-01-01 | 免費 |
| 借券餘額 | `TaiwanStockSecuritiesLending` | `taiwan_stock_securities_lending()` | 2001-05-01 | 免費 |
| **集保股權分散表** | `TaiwanStockHoldingSharesPer` | `taiwan_stock_holding_shares_per()` | **2010-01-29** | **Backer/Sponsor** |
| 月營收 | `TaiwanStockMonthRevenue` | `taiwan_stock_month_revenue()` | 2002-02-01 | 免費 |
| 綜合損益表 | `TaiwanStockFinancialStatements` | `taiwan_stock_financial_statement()` | 1990-03-01 | 免費 |
| **資產負債表** | `TaiwanStockBalanceSheet` | `taiwan_stock_balance_sheet()` | **2011-12-01** | 免費 |
| 現金流量表 | `TaiwanStockCashFlowsStatement` | `taiwan_stock_cash_flows_statement()` | 2008-06-01 | 免費 |
| 股利政策 | `TaiwanStockDividend` | `taiwan_stock_dividend()` | 2005-05-01 | 免費 |
| 除權除息結果 | `TaiwanStockDividendResult` | `taiwan_stock_dividend_result()` | 2003-05-01 | 免費 |
| 市值(Altman X4) | `TaiwanStockMarketValue` | `taiwan_stock_market_value()` | 2004-01-01 | **Sponsor** |
| 下市櫃清單 | `TaiwanStockDelisting` | `taiwan_stock_delisting()` | 2001-01-01 | 免費 |
| 台股總覽 + 產業別 | `TaiwanStockInfo` | `taiwan_stock_info()` | 2021-10-05 | 免費 |
| 加權/櫃買報酬指數(T05 基準) | `TaiwanStockTotalReturnIndex` | `taiwan_stock_total_return_index()` | 2003-01-01 | 免費 |
| 交易日曆 | `TaiwanStockTradingDate` | — | — | 免費 |
| 處置有價證券 | `TaiwanStockDispositionSecuritiesPeriod` | — | — | **Backer/Sponsor** |
| 暫停交易公告 | `TaiwanStockSuspended` | `taiwan_stock_suspended()` | 2011-10-06 | **Backer/Sponsor** |
| 減資參考價(還原用) | `TaiwanStockCapitalReductionReferencePrice` | `taiwan_stock_capital_reduction_reference_price()` | 2011-01-01 | 免費 |
| 面額變更參考價(還原用) | `TaiwanStockParValueChange` | `taiwan_stock_par_value_change()` | 2020-01-01 | 免費 |

**交易日曆務必使用 `TaiwanStockTradingDate`,不得用「排除週末」推算。** 台股有補班日與颱風假,自行推算必然錯位(Review Protocol §6 明列此失效情境)。

---

## 2. ⚠️ SPEC 要求但 FinMind 未提供 — **需人類決定**

以下五項在 SPEC 中有明文要求,但 FinMind 沒有對應 dataset。**實作者不得自行以預設值或空值帶過。**

| # | SPEC 要求 | 出處 | 現況 | 可能作法 |
|---|---|---|---|---|
| G1 | `shares_outstanding`(流通在外股數) | §4.3 `PriceProvider` 回傳欄位;C06 的分母 | **無專門 dataset** | (a) `TaiwanStockBalanceSheet` 普通股股本 ÷ 面額 10 元;(b) `TaiwanStockMarketValue` ÷ 收盤價。兩者皆為推導,需驗證一致性 |
| G2 | 會計師意見(非無保留 → 排除) | §5.2 L1 | **無** | 另尋公開資訊觀測站,或明確記錄此條 L1 未實作 |
| G3 | 財報延遲申報(→ 排除) | §5.2 L1 | **無直接欄位** | 可由財報應公布日與實際到位日推導,屬間接判定 |
| G4 | 董監質押比(> 50% 標記) | §5.2 L1 | **無** | 另尋來源或記錄未實作 |
| G5 | 注意股 / 全額交割股 | §5.2 L1 | **僅有處置股** | 處置股可用 `TaiwanStockDispositionSecuritiesPeriod`;注意股與全額交割需另尋 TWSE/TPEx 來源 |

**G1 最急**,因為它是 `PriceProvider` protocol 的必填回傳欄位,Step 2 一開始就會撞到。

**G2 影響 L1 有效性。** Review Protocol §3 Step 4 明列紅旗:「若 L1 只刷掉個位數檔數,幾乎確定財務排雷沒有真的在跑」。少掉會計師意見與董監質押兩條,L1 的實際攔截率會下降,審查時須據此調整預期,不得反過來放寬其他門檻去湊數字。

---

## 3. Point-in-Time 注意事項

SPEC §4.1 要求所有資料經 `publish_date <= as_of` 過濾。FinMind 各 dataset 的 `date` 欄語意不同:

| 資料 | `date` 語意 | `publish_date` 推導 |
|---|---|---|
| 股價 / 法人 / 融資券 | 交易日 | = `data_date`(當日盤後即公開)|
| **集保股權分散** | 資料基準日(週五)| **= `data_date` + 7 天,再向後對齊交易日**(SPEC §4.1,不得等於 `data_date`)|
| 月營收 | 營收月份 | 次月 10 日前公告,須用實際公告日或保守推估 |
| **財報三表** | **財報期別(季末)**,**不是**公布日 | 須推導。Review Protocol §2.1:若用推估,**Q4 為 +75 天**而非 +45 天 |

**還原股價的 PIT 陷阱(Review Protocol §2.1 稱為「最陰險的一種洩漏」):** `TaiwanStockPriceAdj` 由 FinMind 以**最新**除權息資訊回算。若直接取用,歷史價格會隱含未來的除權息資訊。實作時必須確認還原基準日不晚於 `as_of`,或改以原始價 + `TaiwanStockDividendResult` 自行做 backward adjustment。**此點必須在 Step 2 以 SPEC 的兩次取價比對法驗證。**

---

## 4. 實際可用起始日

各資料源起始日不同,系統的完整可用起點由**最晚**者決定:

```
資產負債表  2011-12-01   ← 最晚,Altman Z 需要
集保分散表  2010-01-29
三大法人    2005-01-01
融資融券    2001-01-01
```

**結論:L0 + L1 + 完整籌碼因子皆可用的最早 `as_of` 約為 2012 年初。** 早於此日期的執行會有維度缺失,須由 §10.3 啟動自我檢查攔截,不得靜默以 `fill_value: 0.5` 帶過。

---

## 5. 與 SPEC 的差異(已由人類裁定,見 `PROGRESS.md`)

| SPEC 原文 | 裁定 |
|---|---|
| §4.4 集保資料來源 = 集保結算所公開網站爬蟲 | 改為 FinMind `TaiwanStockHoldingSharesPer`;爬蟲降級 Phase 2 備援 |
| §13 Step 3 = 集保爬蟲 + 解析 + PIT 對齊 | 改為 FinMind 集保 provider + PIT 對齊;`publish_date = data_date + 7d` 的要求**不變** |
| §8.5 `floor(.../1000)×1000` 整張限制 | 取消,允許零股 |
| §6.2 tier 11–14 = 400 張以上 | tier 編號與集保官方差 1。改以**股數下界**篩選(≥ 400,001 股),不依賴 tier 編號 |

`TaiwanStockHoldingSharesPer` 回傳的 `HoldingSharesLevel` 是**字串區間**(如 `"400001-600000"`),不是 tier 編號。解析時取區間下界比較,可完全繞開 SPEC 的編號問題。

欄位:`date`, `stock_id`, `HoldingSharesLevel`, `people`, `percent`, `unit`
→ 對應 SPEC §4.3 的 `data_date`, `symbol`, `tier`, `holder_count`, `share_pct`, `share_count`

---

*本文件為工程查證紀錄,不含投資建議。*
