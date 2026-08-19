# FlowScope — Production Spec v1.0

> **給實作者 (Codex) 的規格書。**
> 專案代號 `FlowScope`(可改名,但只在 `pyproject.toml` 與套件根目錄改一處)。

---

## 修訂紀錄

| 日期 | 節次 | 修訂內容 | 依據 |
|---|---|---|---|
| 2026-08-18 | §4.3、§4.4、§13 Step 3 | 集保股權分散表改由 FinMind `TaiwanStockHoldingSharesPer` 取得;集保官網爬蟲降級為 Phase 2 備援 | 使用者裁定(§14-2 選項 A)。FinMind 該 dataset 自 2010-01-29 起,集保官網僅保留約 1 年 |
| 2026-08-18 | §6.2 | 集保級距改以**股數下界**判定,不再依賴 tier 編號 | 原表 tier 編號與集保官方差 1,且與同節 `retail_pct = tier 1..3` 自相矛盾 |
| 2026-08-18 | §8.5 | 取消台股整張(1000 股)限制,允許零股 | 使用者裁定(§14-1) |
| 2026-08-19 | §3 | 目錄結構同步:`finmind.py` 涵蓋集保,`tdcc.py` 標註為 Phase 2 備援不建立 | 同上,補漏 |

詳細查證見 `docs/FinMind_API_Inventory.md`;人類裁定紀錄見 `PROGRESS.md`。

---

## 0. 專案身分與邊界

### 0.1 這是一個全新的獨立專案

**這個專案與使用者的其他任何專案無關。** 明確聲明:

- 不是 QuantFlow 的一部分,不共用任何程式碼、設定、資料庫或目錄
- 不是 SwingRadar 的延伸或改版
- 不匯入、不參考、不繼承任何既有 repo 的模組
- 全新 git repo,全新虛擬環境,從空目錄開始

若在既有工作區發現同名或相似模組,**不得重用**,一律新建。

### 0.2 這是什麼

一個**選股與交易計畫產生器**。輸入全市場個股資料,輸出:

1. 一份排名後的候選名單(Top N)
2. 每檔候選股的可執行交易計畫(進場條件、停損、部位、失效點)
3. 一份可稽核的執行紀錄(run manifest),供日後回填績效

### 0.3 這不是什麼

- 不是回測引擎(不模擬完整交易生命週期的損益曲線)
- 不是自動下單系統(**絕不接券商 API,絕不產生下單指令**)
- 不是即時系統(日頻批次,收盤後執行)
- 不是投資建議產品(輸出僅供使用者本人研究用)

### 0.4 核心設計原則

| # | 原則 |
|---|---|
| P1 | **Gate 與 Rank 分離**。財務面只用來排除,不用來排序 |
| P2 | **所有排序因子都必須轉成橫斷面百分位後才能加權** |
| P3 | **Point-in-Time 嚴格性**。任何在 `as_of` 當下尚未公開的資料一律不得使用 |
| P4 | **LLM 完全在篩選迴圈之外**。Phase 1 不含任何 LLM 呼叫 |
| P5 | **決定性 (determinism)**。同樣的 `as_of` + config 必須產生位元級相同的輸出 |
| P6 | **前進紀錄從第一天開始**。沒有 forward log 的執行視為失敗 |

---

## 1. 範圍與階段

### 1.1 Phase 1 範圍(本規格書涵蓋範圍)

| 項目 | 決定 |
|---|---|
| 市場 | **台股優先** (TWSE + TPEx) |
| 持有週期 | **僅 swing (2–8 週)** 一層 |
| 權重 | 寫在 YAML config,**不做 UI** |
| LLM | **不含** |
| 交易計畫 | 純規則引擎 |
| 輸出 | CLI + JSON/Parquet 檔案 |

**為何台股優先(給實作者的背景,不需你判斷):** 本系統最重視籌碼維度,而台股有分點、集保股權分散表、融資融券等美股沒有的資料。美股籌碼只能用代理變數,訊號品質低一個量級。先做台股才能驗證核心假設。

### 1.2 後續階段(**Phase 1 不實作,但架構須預留**)

- Phase 2:美股層(Sharadar + SEC EDGAR + FINRA)
- Phase 3:短線層 (3–10d) + 長線層 (3–12m) + 交叉視圖
- Phase 4:LLM 審閱層
- Phase 5:權重調整 UI

**架構要求:** 市場 (`market`) 與週期 (`horizon`) 從一開始就是一等公民參數,貫穿 config、因子計算、輸出檔名。Phase 1 只註冊 `("TW", "swing")` 一組,但不得寫死。

---

## 2. 技術堆疊

```
Python           3.11+
資料處理          polars (主要) ; pandas 僅在第三方 API 回傳時作為邊界轉換
數值             numpy, scipy
技術指標          自行實作(見 §6.1),不依賴 TA-Lib(C 依賴,Windows 安裝痛苦)
設定             pydantic v2 + YAML
儲存             Parquet (資料層) + SQLite (run manifest / forward log)
CLI              typer
測試             pytest, pytest-cov, hypothesis(用於因子性質測試)
Lint             ruff + mypy (strict)
```

**執行環境:Windows 11。** 所有路徑處理使用 `pathlib`,不得出現硬編碼的 `/` 路徑分隔符或 POSIX-only 呼叫。

---

## 3. 目錄結構

```
flowscope/
├── pyproject.toml
├── README.md
├── configs/
│   ├── base.yaml                  # 共用設定
│   ├── tw_swing.yaml              # (market=TW, horizon=swing) 的權重與門檻
│   └── logging.yaml
├── src/flowscope/
│   ├── __init__.py
│   ├── cli.py                     # typer entrypoint
│   ├── config/
│   │   ├── schema.py              # pydantic models
│   │   └── loader.py              # YAML -> model, 含 hash 計算
│   ├── data/
│   │   ├── protocols.py           # Protocol 介面定義
│   │   ├── cache.py               # Parquet 本地快取層
│   │   ├── calendar.py            # 交易日曆
│   │   ├── adjust.py              # 除權息還原
│   │   └── providers/
│   │       ├── finmind.py         # 主要來源(含集保股權分散表)
│   │       ├── tdcc.py            # (2026-08-18 修訂) 集保官網爬蟲,Phase 2 備援,Phase 1 不建立
│   │       └── twse.py            # 官方公開資料補充(注意股/全額交割等 FinMind 缺口)
│   ├── universe/
│   │   ├── builder.py             # 建構 point-in-time 股票池
│   │   └── gates.py               # L0 / L1 閘門
│   ├── factors/
│   │   ├── base.py                # Factor Protocol
│   │   ├── registry.py            # 因子註冊表
│   │   ├── technical.py           # §6.1
│   │   ├── chips_tw.py            # §6.2
│   │   ├── theme.py               # §6.4
│   │   └── financial.py           # §6.5 (僅供 gate 使用)
│   ├── scoring/
│   │   ├── normalize.py           # winsorize + 橫斷面百分位
│   │   ├── aggregate.py           # 維度分數 -> 總分
│   │   └── sensitivity.py         # 權重敏感度分析
│   ├── planner/
│   │   ├── state_machine.py       # 進場狀態判定
│   │   ├── levels.py              # 進場區/停損/目標計算
│   │   └── sizing.py              # 部位大小
│   ├── record/
│   │   ├── manifest.py            # run manifest 寫入
│   │   ├── forward.py             # 前進紀錄與回填
│   │   └── db.py                  # SQLite schema
│   └── report/
│       └── render.py              # CLI 表格 + JSON 輸出
├── tests/
│   ├── fixtures/                  # golden data
│   ├── test_factors_technical.py
│   ├── test_factors_chips.py
│   ├── test_pit.py                # PIT 違規偵測(關鍵)
│   ├── test_scoring.py
│   ├── test_planner.py
│   └── test_determinism.py
└── data/
    ├── raw/                       # 原始下載快取
    ├── processed/                 # 還原後的 parquet
    └── runs/                      # 每次執行的輸出
```

---

## 4. 資料層

### 4.1 Point-in-Time 契約(**最重要的一節**)

每一筆資料列**必須**同時具備兩個時間欄位:

| 欄位 | 意義 |
|---|---|
| `data_date` | 資料所描述的日期(例:2026-08-15 的收盤價) |
| `publish_date` | 這筆資料**公開可得**的日期 |

所有查詢一律經由:

```python
def as_of_filter(df: pl.DataFrame, as_of: date) -> pl.DataFrame:
    """任何資料存取都必須經過此函式。"""
    return df.filter(pl.col("publish_date") <= as_of)
```

**已知延遲(必須在 provider 層正確設定 `publish_date`):**

| 資料 | 延遲 |
|---|---|
| 日收盤價 / 成交量 | 當日盤後,`publish_date = data_date` |
| 三大法人買賣超 | 當日盤後,`publish_date = data_date` |
| 融資融券餘額 | 當日盤後,`publish_date = data_date` |
| **集保股權分散表** | **資料日為週五,公布日為次週五左右。`publish_date = data_date + 7 天`,並向後對齊到最近交易日** |
| 月營收 | 次月 10 日前 |
| 季報 | Q1/Q2/Q3 為期末後 45 天;Q4/年報為期末後 75 天。**若 provider 提供實際公布日則優先採用** |
| 董監持股 | 次月 15 日 |

**驗收測試 `tests/test_pit.py` 必須包含:** 對隨機抽樣的 200 個 `(stock, as_of)` 組合,斷言取回的所有資料列 `publish_date <= as_of`。任何違規即測試失敗。

### 4.2 台股特有的資料清理

1. **除權息還原**:價格因子一律使用還原價 (adjusted)。但**成交量與市值使用原始值**。還原方式採用向後調整 (backward adjustment),以最新價為基準。
2. **下市/暫停交易股票必須保留在歷史資料中**。建構 `as_of` 當日的股票池時,依 `listing_date <= as_of < delisting_date` 篩選。若 provider 不提供下市清單,必須在 README 中明確記錄此為已知的倖存者偏差來源。
3. **股票代號變更 / 合併**:維護 `data/processed/symbol_map.parquet`,欄位 `(old_id, new_id, effective_date)`。
4. **處置股 / 全額交割股 / 注意股**:必須抓取並在 Gate 排除(見 §5.2)。
5. **股本變動**:計算週轉率、籌碼比例時,分母須使用 `as_of` 當時的流通在外股數,不得使用最新值。

### 4.3 Provider Protocol

```python
from typing import Protocol
from datetime import date
import polars as pl

class PriceProvider(Protocol):
    def get_ohlcv(
        self, symbols: list[str], start: date, end: date, adjusted: bool
    ) -> pl.DataFrame:
        """回傳欄位: symbol, data_date, publish_date, open, high, low,
        close, volume, amount, shares_outstanding"""
        ...

class ChipProvider(Protocol):
    def get_institutional_flow(self, symbols, start, end) -> pl.DataFrame:
        """symbol, data_date, publish_date,
        foreign_net, trust_net, dealer_net (單位: 股)"""
        ...

    def get_margin(self, symbols, start, end) -> pl.DataFrame:
        """symbol, data_date, publish_date,
        margin_balance, short_balance, margin_quota_used_pct,
        securities_lending_balance"""
        ...

    def get_holder_distribution(self, symbols, start, end) -> pl.DataFrame:
        """集保股權分散表。
        symbol, data_date, publish_date, tier, holder_count,
        share_count, share_pct
        tier 為級距**股數下界**(如 400001 代表 400,001–600,000 股區間)。
        *(2026-08-18 修訂)* 不使用集保 tier 序號,理由見 §6.2"""
        ...

class FundamentalProvider(Protocol):
    def get_financials(self, symbols, start, end) -> pl.DataFrame: ...
    def get_monthly_revenue(self, symbols, start, end) -> pl.DataFrame: ...

class MetaProvider(Protocol):
    def get_listings(self, as_of: date) -> pl.DataFrame:
        """symbol, name, market, industry, listing_date, delisting_date"""
        ...
    def get_warnings(self, as_of: date) -> pl.DataFrame:
        """處置股/注意股/全額交割股清單"""
        ...
```

**快取策略:** 所有 provider 呼叫先查本地 Parquet 快取。快取 key 為 `(provider, method, symbol_hash, start, end)`。歷史資料(> 30 天前)永久快取;近期資料 TTL 為 1 個交易日。提供 `--no-cache` 旗標強制重抓。

### 4.4 資料來源(Phase 1)

| 資料 | 來源 | 備註 |
|---|---|---|
| OHLCV、三大法人、融資券、月營收、財報 | **FinMind 贊助方案** | 主要來源 |
| 集保股權分散表 | **FinMind `TaiwanStockHoldingSharesPer`** | *(2026-08-18 修訂)* 自 2010-01-29 起,需 Backer/Sponsor 層。集保官網僅保留約 1 年,爬蟲降級為 Phase 2 備援,Phase 1 不實作 |
| 處置股/注意股 | TWSE / TPEx 公告頁 | |
| 券商分點 | **Phase 1 不實作** | 成本高、處理複雜。介面預留,先驗證免費資料的有效性 |

**實作者注意:** 集保爬蟲必須加上 rate limit(每次請求間隔 ≥ 1 秒)與 retry with exponential backoff。爬到的原始 HTML/CSV 存入 `data/raw/tdcc/{data_date}/`,不要只存解析後結果。

---

## 5. 股票池與閘門

### 5.1 L0 流動性閘門

依序套用,並記錄每一關的剩餘檔數:

| 條件 | 預設值 | config key |
|---|---|---|
| 20 日平均成交金額 | ≥ NT$ 30,000,000 | `gates.l0.min_avg_dollar_volume` |
| 收盤價 | ≥ NT$ 10 | `gates.l0.min_price` |
| 上市滿 | ≥ 250 個交易日 | `gates.l0.min_listing_days` |
| 近 20 日有交易的天數比例 | ≥ 90% | `gates.l0.min_trading_day_ratio` |
| 排除類型 | ETF、ETN、REIT、TDR、特別股、存託憑證 | `gates.l0.exclude_types` |
| 排除市場 | 興櫃 | `gates.l0.exclude_markets` |

### 5.2 L1 排雷閘門(財務面只在這裡出現)

**布林判定,不參與加權。** 任一條成立即排除:

| 條件 | 預設 | 說明 |
|---|---|---|
| 處置股 / 全額交割 / 注意股 | 排除 | 交易受限 |
| Altman Z-Score (製造業版) | < 1.8 排除 | 見下方公式 |
| Beneish M-Score | > -1.78 標記 `high_risk`,**不直接排除**,但在報告中以旗標顯示 | |
| 連續營運現金流為負 | ≥ 2 季排除 | |
| 一年內現金增資規模 | > 市值 20% 排除 | |
| 會計師意見 | 非無保留 → 排除 | |
| 財報延遲申報 | 排除 | |
| 應收帳款成長 − 營收成長 | > 30 個百分點 → 標記 | |
| 存貨成長 − 營收成長 | > 30 個百分點 → 標記 | |
| 董監質押比 | > 50% 標記 | |
| 近 250 日出現單日跌幅 | < −9.5% 且無重大利空可解釋 | **不實作自動判定,僅記錄** |

**Altman Z-Score (製造業):**
```
Z = 1.2·X1 + 1.4·X2 + 3.3·X3 + 0.6·X4 + 1.0·X5
X1 = 營運資金 / 總資產
X2 = 保留盈餘 / 總資產
X3 = EBIT / 總資產
X4 = 股票市值 / 總負債
X5 = 營收 / 總資產
```
非製造業使用 Z'' 版本:`Z'' = 6.56·X1 + 3.26·X2 + 6.72·X3 + 1.05·X4`,門檻 1.1。依 `industry` 欄位切換。

**Beneish M-Score:** 標準八變數版本 (DSRI, GMI, AQI, SGI, DEPI, SGAI, LVGI, TATA)。若任一變數資料缺失,回傳 `None` 並標記 `mscore_unavailable`,不得以 0 填補。

### 5.3 漏斗記錄

每次執行必須輸出:

```
Universe funnel (as_of=2026-08-18, market=TW)
  全市場上市櫃                1,812
  L0 流動性                     △ -1,140  →   672
  L1 排雷                       △   -83  →   589
  資料完整度 ≥ 門檻              △   -41  →   548
  評分後 Top N                              →    30
```

若最終候選數 < 10 或 > 資料完整池的 30%,發出警告(參數可能設定不當)。

---

## 6. 因子庫

### 6.0 共同規範

```python
class Factor(Protocol):
    name: str
    dimension: Literal["technical", "chips", "theme", "financial"]
    horizons: list[str]          # 此因子適用的週期
    direction: Literal[1, -1]    # 1 = 越大越好, -1 = 越小越好
    min_history_days: int        # 計算所需最少歷史長度

    def compute(
        self, panel: pl.DataFrame, as_of: date, params: dict
    ) -> pl.DataFrame:
        """回傳 (symbol, factor_name, raw_value)。
        資料不足時該 symbol 回傳 null,不得回傳 0。"""
        ...
```

**硬性要求:**
- 所有因子的回看窗都必須從 config 讀取,不得寫死
- 資料不足一律回傳 `null`,絕不以 0 或均值填補(填補交給 §7 統一處理)
- 每個因子都必須有對應的 golden fixture 單元測試

---

### 6.1 技術面因子 (`technical.py`)

Swing (2–8 週) 使用的參數列於下表。所有指標**自行實作**。

#### 趨勢族群

**T01 `ma_alignment_score`**
```
評分 5 條均線 (5, 10, 20, 60, 120) 的排列狀態:
score = Σ 1[MA_i > MA_j] for all i<j  , 共 10 組
再除以 10 正規化到 [0, 1]
額外要求: close > MA20 才給滿分,否則 ×0.8
```

**T02 `linreg_slope_r2`** — *此因子優於單純 MA*
```
對 log(close) 的最近 N=60 日做 OLS 線性迴歸
slope_annualized = slope × 252
value = slope_annualized × R²
```
用 R² 加權的理由:斜率相同時,走勢乾淨(R² 高)的股票優於鋸齒狀。

**T03 `adx`**
```
標準 Wilder ADX, period=14
direction=1, 但須搭配 +DI > -DI 作為條件
若 +DI < -DI,value = -adx (下降趨勢視為負分)
```

**T04 `supertrend_state`**
```
ATR period=10, multiplier=3.0
value = 1 if 多方, -1 if 空方
另輸出 supertrend_days: 目前方向持續天數
```

#### 動能族群

**T05 `relative_strength_pct`** — **本族群最重要的因子**
```
r_stock = close[t] / close[t-N] - 1     N = 60 (swing)
r_bench = 加權指數同期報酬
rs_raw  = (1 + r_stock) / (1 + r_bench) - 1
```
另計算多窗口版本並取加權:
```
rs_composite = 0.4 × RS(20d) + 0.4 × RS(60d) + 0.2 × RS(120d)
```

**T06 `mansfield_rsi`**
```
RS_line = close / benchmark_close
MRS = (RS_line / SMA(RS_line, 52週) - 1) × 100
```
Mansfield RSI > 0 表示長期跑贏大盤。

**T07 `macd_histogram_slope`**
```
MACD(12, 26, 9)
value = 柱狀體最近 5 日的 OLS 斜率 / ATR
(除以 ATR 是為了跨標的可比)
```

**T08 `roc_rank_composite`**
```
ROC(20), ROC(60), ROC(120) 各自做橫斷面百分位後
加權: 0.3 / 0.4 / 0.3
```

> **注意:T05 / T06 / T08 高度相關。** 實作後必須跑相關係數矩陣(見 §6.6),若 |ρ| > 0.7 則只保留其一。預期 T05 與 T08 會衝突,優先保留 T05。

#### 波動 / 壓縮族群

**T09 `atr_percent`**
```
value = ATR(14) / close × 100
direction = 0 (不排序,作為部位計算與過濾用)
Gate: swing 層要求 2.0 ≤ atr_pct ≤ 12.0
```

**T10 `bb_width_percentile`**
```
bb_width = (upper - lower) / middle    , BB(20, 2)
value = bb_width 在最近 250 日中的百分位
direction = -1  (越窄越好,代表能量壓縮)
```

**T11 `ttm_squeeze`**
```
Bollinger(20, 2) 完全位於 Keltner(20, 1.5×ATR) 內部 → squeeze_on
value = 目前 squeeze 已持續天數 (若未在 squeeze 則為 0)
另輸出 squeeze_released: bool  (前一日 on, 今日 off → 剛釋放,最佳訊號)
```

**T12 `volatility_contraction`** (VCP 概念)
```
把最近 60 日切成 3 段各 20 日
計算每段的 (high-low)/close 波幅
value = 1 if 波幅逐段遞減 (w1 > w2 > w3) else 0
另輸出 contraction_ratio = w3 / w1
```

#### 量能族群

**T13 `obv_divergence`**
```
price_slope = OLS slope of close, N=20  (標準化: / close.mean())
obv_slope   = OLS slope of OBV,   N=20  (標準化: / |OBV|.mean())
value = obv_slope - price_slope
正值 = 量能領先價格 (吸籌)
```

**T14 `cmf`**
```
標準 Chaikin Money Flow, period=20
```

**T15 `volume_dryup_ratio`**
```
value = MA(volume, 5) / MA(volume, 20)
direction = -1
用途: 回檔期間量縮 (< 0.7) 是健康換手的訊號
```

**T16 `volume_surge`**
```
value = volume[t] / MA(volume, 20)
搭配 close 漲幅使用: 只在 close 上漲時計分
```

**T17 `up_down_volume_ratio`**
```
最近 50 日中,上漲日成交量總和 / 下跌日成交量總和
> 1.5 為強勢
```

#### 結構族群

**T18 `pct_from_52w_high`**
```
value = close / max(high, 250d) - 1     (負值或 0)
direction = 1  (越接近高點越好)
經驗門檻: > -0.15 為強勢股
```

**T19 `base_breakout`**
```
偵測盤整基底:
  1. 找出最近 N=60 日內的 pivot high (左右各 5 日皆較低)
  2. 基底寬度 ≥ 15 個交易日
  3. 基底期間振幅 ≤ 25%
value = (close - base_high) / atr
  > 0  : 已突破,值 = 突破幅度 (以 ATR 計)
  ≤ 0  : 尚未突破,值 = 距離 (負值)
另輸出: base_high, base_low, base_start_date, base_length
```
`base_high` 會被交易計畫層 (§8) 用作突破觸發價,**必須輸出**。

**T20 `distance_to_ma20_atr`**
```
value = (close - MA20) / ATR(14)
direction = 0 (不排序)
用途: > 1.5 判定為過度延伸 → WAIT_PULLBACK
```

**T21 `pivot_structure`**
```
最近 90 日的 swing high / swing low (ZigZag, threshold = 1.5 × ATR%)
value = 1 if 高點與低點皆抬升 (HH + HL)
        0.5 if 僅高點抬升
        0 otherwise
另輸出: last_swing_low (交易計畫的停損參考)
```

---

### 6.2 籌碼面因子 (`chips_tw.py`) — **本系統核心**

這是與其他選股系統的主要差異來源,實作品質最為關鍵。

#### 集保股權分散表衍生因子

集保級距對照 *(2026-08-18 修訂)*:

**本節一律以「級距的股數下界」判定,不使用集保 tier 序號。** 原規格表列的 tier 編號與集保官方編號相差 1(官方 tier 12 才是 400,001–600,000 股),且與本節 `retail_pct = tier 1..3` 的用法自相矛盾。FinMind `TaiwanStockHoldingSharesPer` 的 `HoldingSharesLevel` 本就是字串區間(如 `"400001-600000"`),解析下界比較即可,不需依賴任何編號。

集保官方級距(供對照,**實作不得寫死序號**):

| 官方 tier | 級距(股) | | 官方 tier | 級距(股) |
|---|---|---|---|---|
| 1 | 1–999 | | 9 | 50,001–100,000 |
| 2 | 1,000–5,000 | | 10 | 100,001–200,000 |
| 3 | 5,001–10,000 | | 11 | 200,001–400,000 |
| 4 | 10,001–15,000 | | 12 | 400,001–600,000 |
| 5 | 15,001–20,000 | | 13 | 600,001–800,000 |
| 6 | 20,001–30,000 | | 14 | 800,001–1,000,000 |
| 7 | 30,001–40,000 | | 15 | 1,000,001 以上 |
| 8 | 40,001–50,000 | | 合計 | (須排除,不得計入加總) |

定義(以股數下界 `lower` 判定):
```
big_holder_pct   = Σ share_pct where lower >= 400_001      (400 張以上)
mega_holder_pct  = Σ share_pct where lower >= 1_000_001    (1000 張以上)
retail_pct       = Σ share_pct where lower <= 5_001        (10 張以下)
retail_count     = Σ holder_count where lower <= 5_001
avg_shares_held  = 總股數 / 總股東人數
```

**實作要求:**
- 「合計」列必須明確排除,不得混入任何加總
- 各級距 `share_pct` 加總應 ≈ 100%(容忍 0.5%),不符者標記
- 集保若新增或調整級距,以股數下界判定的邏輯不受影響——這正是不寫死序號的理由

**C01 `big_holder_slope`** — **最重要的單一籌碼因子**
```
取最近 N=8 週的 big_holder_pct 時間序列
value = OLS slope (單位: 百分點 / 週)
另輸出 r2: 斜率的解釋力

判讀: 持續為正 = 大戶建倉中
```
要求:少於 6 個資料點則回傳 `null`。

**C02 `big_holder_zscore`**
```
value = (big_holder_pct[t] - mean(big_holder_pct, 52週))
        / std(big_holder_pct, 52週)
```

**C03 `retail_exit_slope`**
```
取最近 N=8 週的 retail_count 時間序列
value = -1 × OLS slope(標準化: 除以期初 retail_count)
direction = 1  (散戶人數減少為正分)
```

**C04 `avg_holding_growth`**
```
value = avg_shares_held[t] / avg_shares_held[t-8週] - 1
平均每人持股增加 = 籌碼集中
```

**C05 `chip_concentration_composite`**
```
綜合 C01..C04 的 z-score 平均。
此因子與 C01-C04 高度相關,
實作為「可替代 C01-C04 的單一欄位」,由 config 決定使用哪種模式:
  chips.holder_mode: "composite" | "individual"
預設 "composite"(降低子因子共線性問題)
```

#### 三大法人因子

**C06 `institutional_net_intensity`**
```
net = Σ(foreign_net + trust_net + dealer_net) over N=20 日
value = net / shares_outstanding × 100    (單位: %)
```
使用流通在外股數作分母而非成交量,因為前者不受換手率影響。

**C07 `trust_continuity`** — **台股實證上最有效的短中期籌碼訊號**
```
計算投信 (trust_net) 最近 N=20 日:
  buy_days      = 買超天數
  max_streak    = 最長連續買超天數
  net_total     = 淨買超股數
value = (buy_days / 20) × 0.4
      + min(max_streak / 10, 1.0) × 0.3
      + percentile(net_total / shares_outstanding) × 0.3
```
投信有作帳與績效壓力,連續買超的持續性遠高於自營商。

**C08 `foreign_persistence`**
```
最近 N=60 日外資買超天數比例
value = buy_days / 60
```

**C09 `dealer_noise_penalty`**
```
自營商買賣超的波動度(避險部位造成的雜訊)
value = -1 × std(dealer_net, 20) / mean(|dealer_net|, 20)
權重應設得很低,或直接不啟用。預設 enabled: false
```

**C10 `institutional_price_efficiency`**
```
最近 20 日:
  法人淨買超佔成交量比例 vs 同期漲幅
value = 漲幅(%) / (法人淨買超 / 期間總成交量 × 100)
direction = -1
低值表示「法人買很多但價格還沒反應」→ 尚有空間
資料不足或分母趨近 0 時回傳 null
```

#### 融資融券因子

**C11 `margin_divergence`** — **健康換手的核心判準**
```
price_change  = close[t] / close[t-20] - 1
margin_change = margin_balance[t] / margin_balance[t-20] - 1
value = price_change - margin_change

正值大 = 股價漲但融資減 = 籌碼由散戶轉向法人/大戶 (健康)
負值大 = 股價漲但融資暴增 = 散戶追高 (危險)
```

**C12 `margin_ratio_level`**
```
value = margin_balance / shares_outstanding × 100
direction = -1  (融資使用率低為佳)
```

**C13 `short_pressure`**
```
value = (short_balance + securities_lending_balance)
        / MA(volume, 20)
單位: 天 (回補所需天數)
direction = 0 → 作為軋空潛力的補充資訊,不直接排序
> 3 天且同時 big_holder_slope > 0 → 標記 squeeze_candidate
```

**C14 `margin_short_ratio_change`**
```
券資比 = short_balance / margin_balance
value = 券資比[t] - 券資比[t-20]
上升代表空方增溫
```

#### 型態複合因子

**C15 `accumulation_pattern`** — 洗籌碼完成的經典組合
```
三個條件全部滿足才給分:
  A. 價格橫盤: 最近 20 日振幅 (max_high - min_low) / close < 0.15
  B. 量能萎縮: MA(volume, 20) / MA(volume, 60) < 0.85
  C. 大戶增加: big_holder_slope > 0

value = 1.0 if A and B and C
      = 0.6 if (A and C) or (B and C)
      = 0.0 otherwise
```

**C16 `distribution_warning`** — **這是排除訊號,不是排序訊號**
```
以下條件計數:
  1. close 創 60 日新高
  2. big_holder_slope < 0
  3. margin_balance 20 日增幅 > 15%
  4. 外資或投信近 5 日轉為賣超
  5. 成交量創 60 日新高但收黑 K

warning_count ≥ 3 → 該股標記 distribution_risk 並從候選名單移除
warning_count = 2 → 標記但保留,報告中以 ⚠ 顯示
```
此因子的處理在 §7.4 說明:它是 post-scoring 的排除層,不進入加權。

**C17 `chip_stability`**
```
value = -1 × std(big_holder_pct, 12週)
大戶比例穩定緩升 優於 劇烈進出
```

#### 預留(Phase 1 不實作)

```python
# C18 broker_concentration  — 需券商分點資料
# C19 broker_smart_money    — 需分點 + 主力券商辨識
# 介面預留於 ChipProvider.get_broker_flow(),Phase 1 raise NotImplementedError
```

---

### 6.3 美股籌碼因子 — **Phase 2,不實作**

僅記錄設計意圖,供架構預留:Form 4 集群買進、13D/G 舉牌、FINRA off-exchange volume ratio、short interest 變化、OBV/CMF 代理。
**實作者不需為此撰寫任何程式碼**,只需確保 `factors/` 下的註冊機制支援依 `market` 切換因子集合。

---

### 6.4 題材面因子 (`theme.py`)

**設計決定:不使用新聞熱度。** 理由:新聞落後於價格,且爬取與去重成本高。改用族群相對強度,純價量資料即可計算。

**M01 `industry_rs_percentile`**
```
1. 依 TWSE 產業別分類 (約 30 類) 分組
2. 計算每組的 20 日報酬中位數
3. value = 該股所屬產業組的中位數報酬在全部產業中的百分位
```

**M02 `industry_breadth`**
```
該股所屬產業中,股價站上 MA60 的個股比例
族群普漲優於單股獨強
```

**M03 `stock_vs_industry_rs`**
```
value = 個股 60 日報酬 - 所屬產業 60 日報酬中位數
族群內的相對強弱
```

**M04 `revenue_momentum`**
```
月營收 YoY 的 3 個月移動平均
(此因子放在 theme 而非 financial,因為月營收是台股最即時的基本面訊號,
 公布延遲僅 10 天,適合作為題材驗證)
value = mean(YoY[m], YoY[m-1], YoY[m-2])
另要求: 最近一月 MoM > 0 才給滿分
```

**M05 `revenue_acceleration`**
```
value = YoY[m] - YoY[m-3]
營收成長率是否在加速
```

---

### 6.5 財務面 (`financial.py`) — **僅供 Gate 使用**

Phase 1 中,財務面**不產生任何排序分數**。此模組只實作 §5.2 所需的計算:Altman Z、Beneish M、現金流檢查、增資檢查、成長率背離檢查。

Piotroski F-Score 可實作但預設 `enabled: false`,留待 Phase 3 長線層啟用。

---

### 6.6 因子共線性檢查(**必須實作為 CLI 指令**)

```bash
flowscope diagnose collinearity --market TW --horizon swing --lookback 250
```

輸出:
1. 全因子的 Spearman 相關係數矩陣(CSV + 終端熱圖)
2. 所有 |ρ| > 0.7 的配對清單,附建議保留者(依 `factor_priority` config)
3. 每個維度的有效自由度估計:`n_eff = (Σλ)² / Σλ²`(λ 為相關矩陣特徵值)

**驗收條件:** 最終啟用的因子集合中,任兩個同維度因子的 |ρ| ≤ 0.7。若違反,啟動時發出警告。

---

## 7. 評分

### 7.1 正規化流程

對每個因子,在**同一個 (market, horizon, as_of) 的股票池內**執行:

```
1. 若 raw_value 為 null → 標記 missing,暫不參與
2. Winsorize: 裁切到 [1%, 99%] 分位
3. 橫斷面百分位: rank(method="average") / n  → [0, 1]
4. 若 direction == -1 → value = 1 - value
5. missing 者填入 0.5,並累計該股的 missing_count
```

**絕對不得**使用固定門檻(如「RSI > 70」)或全樣本 z-score。所有排序都是相對於當日股票池的。

### 7.2 缺失資料政策

```yaml
scoring:
  missing:
    fill_value: 0.5
    max_missing_ratio_per_dimension: 0.4   # 超過則該維度視為不可用
    max_missing_ratio_total: 0.25          # 超過則該股從候選中移除
    redistribute_weight: true              # 維度不可用時,權重按比例分配給其他維度
```

若某維度不可用而重新分配權重,**必須在該股的輸出中記錄 `weight_redistributed: true` 與實際使用的權重**。這是可稽核性的要求。

### 7.3 分數聚合

```
dimension_score = Σ (sub_weight_i × normalized_factor_i) / Σ sub_weight_i
total_score     = Σ (dimension_weight_d × dimension_score_d)
```

Phase 1 子權重全部等權(`sub_weight = 1.0`)。config 結構須支援個別設定,但預設不啟用。

### 7.4 Post-scoring 排除層

在計算完 `total_score` **之後**、產生名單**之前**:

1. `C16 distribution_warning ≥ 3` → 移除
2. `T09 atr_percent` 超出 [2.0, 12.0] → 移除
3. 未來 5 個交易日內有財報公布 → 標記 `earnings_soon`(不移除,交由交易計畫層處理)
4. 近 20 日曾有處置措施 → 移除

### 7.5 敏感度分析(**必須實作**)

```bash
flowscope diagnose sensitivity --as-of 2026-08-18 --top-n 30
```

對每個維度權重做 ±5% 與 ±10% 的擾動(其餘維度按比例調整以維持總和 1.0),輸出:

```
維度         擾動      Top30 名單變動檔數    Spearman 相關 (vs 基準排名)
technical    +10%              4                    0.94
technical    -10%              5                    0.92
chips        +10%              7                    0.88
...
```

**判讀規則(寫在 README):** 若任一 ±10% 擾動造成 Top 30 變動 > 10 檔,或 Spearman < 0.8,代表排名不穩健,不應信任。此時應減少因子數量或放寬 Top N。

---

## 8. 交易計畫產生器

### 8.1 定位

輸入:通過篩選的個股 + 其技術結構欄位
輸出:**一個可被證偽的完整計畫**。**純規則,無 LLM。**

### 8.2 狀態機

依序判定,第一個符合者勝出:

| 順序 | 狀態 | 條件 |
|---|---|---|
| 1 | `NO_TRADE` | `distribution_warning = 2` 或 `earnings_soon` 且 horizon=swing 或 `atr_percent > 12` |
| 2 | `ENTRY_NOW` | `T19 base_breakout > 0`(已突破) 且 `T20 distance_to_ma20_atr ≤ 1.5` 且 `T16 volume_surge ≥ 1.5` |
| 3 | `WAIT_BREAKOUT` | `-1.0 ≤ T19 base_breakout ≤ 0`(在基底上緣附近) |
| 4 | `WAIT_PULLBACK` | `T20 distance_to_ma20_atr > 1.5`(過度延伸) |
| 5 | `WAIT_TRIGGER` | 分數高但無明確基底結構 |

### 8.3 計畫欄位(全部必填)

```python
@dataclass(frozen=True)
class TradePlan:
    symbol: str
    as_of: date
    state: PlanState
    horizon: str

    # 進場
    entry_condition: str        # 可程式化的條件字串,見 §8.4
    entry_zone_low: float
    entry_zone_high: float

    # 風險
    invalidation: float         # 低於此價,「論點」已錯誤,取消計畫
    initial_stop: float         # 實際停損價
    risk_per_share: float       # entry_mid - initial_stop
    stop_basis: str             # "atr" | "structure" | "base_low"

    # 部位
    position_shares: int
    position_value: float
    position_pct_of_account: float

    # 目標(以 R 倍數表示)
    target_1r: float
    target_2r: float
    target_3r: float

    # 時間
    time_stop_days: int         # swing 預設 10
    expires_on: date

    # 事件
    next_earnings_date: date | None
    ex_dividend_date: date | None
    event_within_horizon: bool

    # 可稽核
    triggered_by: list[str]     # 觸發此狀態的因子名稱
    score_snapshot: dict[str, float]
```

### 8.4 價位計算規則

```
ENTRY_NOW:
    entry_zone = [close × 0.995, close × 1.02]
    initial_stop:
        candidates = [base_low, last_swing_low, close - 2.0 × ATR]
        取三者中「最接近但低於 close」者
        再檢查: risk_per_share / close ≤ 0.10,否則 state → NO_TRADE (風險過大)
    invalidation = base_low × 0.98

WAIT_BREAKOUT:
    entry_condition = f"close > {base_high} AND volume > 1.5 × MA(volume,20)"
    entry_zone = [base_high, base_high × 1.03]
    initial_stop = max(base_low, base_high - 2.0 × ATR)
    invalidation = base_low

WAIT_PULLBACK:
    entry_zone = [MA20 - 0.5 × ATR, MA20 + 0.5 × ATR]
    entry_condition = f"low touches zone AND MA(volume,5)/MA(volume,20) < 0.7 AND close > open"
      ↑ 量縮是關鍵條件,不可省略。量縮回檔=換手,量增回檔=出貨
    initial_stop = MA20 - 2.0 × ATR
    invalidation = last_swing_low

WAIT_TRIGGER:
    entry_condition = "T11 squeeze_released == True AND close > MA20"
    entry_zone = [close × 0.98, close × 1.05]
    initial_stop = close - 2.0 × ATR
    invalidation = close - 3.0 × ATR
```

**目標價:**
```
target_1r = entry_mid + 1.0 × risk_per_share
target_2r = entry_mid + 2.0 × risk_per_share
target_3r = entry_mid + 3.0 × risk_per_share
```
**不使用絕對價格目標,一律以 R 倍數表示。**

### 8.5 部位大小

```
account_value        從 config 讀取
risk_per_trade_pct   預設 1.0%
max_position_pct     預設 15%

risk_amount    = account_value × risk_per_trade_pct / 100
shares_by_risk = risk_amount / risk_per_share
shares_by_cap  = account_value × max_position_pct / 100 / entry_mid
position_shares = floor(min(shares_by_risk, shares_by_cap))   # (2026-08-18 修訂) 允許零股
若 position_shares == 0 → 記錄 "position_too_small",保留計畫但標記
```

### 8.6 Time stop

```
swing:  10 個交易日
short:   3 個交易日   (Phase 3)
long:   20 個交易日   (Phase 3)

expires_on = as_of + N 個交易日(使用交易日曆,非日曆日)
```

到期未觸發的計畫在 forward log 中標記 `expired_untriggered`,**必須與「觸發後虧損」分開統計**。

---

## 9. 輸出與紀錄

### 9.1 Run Manifest

每次執行產生 `data/runs/{run_id}/manifest.json`:

```json
{
  "run_id": "20260818T163000Z-a3f9c1",
  "as_of": "2026-08-18",
  "market": "TW",
  "horizon": "swing",
  "created_at": "2026-08-18T16:30:00Z",
  "flowscope_version": "1.0.0",
  "git_commit": "a3f9c1e",
  "config_hash": "sha256:...",
  "config_snapshot": { "...完整 config 內容..." },
  "data_versions": {
    "price_latest_date": "2026-08-18",
    "chip_latest_date": "2026-08-18",
    "tdcc_latest_data_date": "2026-08-08",
    "tdcc_latest_publish_date": "2026-08-15"
  },
  "funnel": {
    "total": 1812, "after_l0": 672, "after_l1": 589,
    "after_completeness": 548, "final": 30
  },
  "warnings": ["..."],
  "runtime_seconds": 84.2
}
```

`config_hash` 是整份 config 正規化後的 SHA-256。**沒有這個欄位,前進紀錄毫無意義**——無法區分績效差異來自策略還是參數變動。

### 9.2 輸出檔案

```
data/runs/{run_id}/
├── manifest.json
├── candidates.parquet      # Top N + 全部分數與因子原始值
├── plans.json              # TradePlan 列表
├── funnel.json
├── sensitivity.json        # 若有執行
└── report.md               # 人類可讀摘要
```

`candidates.parquet` 必須包含**每一個因子的 raw_value 與 normalized_value**,不能只存最終分數。日後做因子歸因分析時會需要。

### 9.3 SQLite Schema(前進紀錄)

```sql
CREATE TABLE runs (
    run_id TEXT PRIMARY KEY,
    as_of DATE NOT NULL,
    market TEXT NOT NULL,
    horizon TEXT NOT NULL,
    config_hash TEXT NOT NULL,
    git_commit TEXT,
    created_at TIMESTAMP NOT NULL
);

CREATE TABLE candidates (
    run_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    rank INTEGER NOT NULL,
    total_score REAL NOT NULL,
    score_technical REAL,
    score_chips REAL,
    score_theme REAL,
    missing_count INTEGER,
    weight_redistributed BOOLEAN,
    plan_state TEXT,
    entry_zone_low REAL,
    entry_zone_high REAL,
    initial_stop REAL,
    invalidation REAL,
    time_stop_days INTEGER,
    expires_on DATE,
    PRIMARY KEY (run_id, symbol)
);

CREATE TABLE forward_returns (
    run_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    horizon_days INTEGER NOT NULL,      -- 5, 20, 60
    entry_triggered BOOLEAN,
    trigger_date DATE,
    trigger_price REAL,
    exit_reason TEXT,                   -- 'target'|'stop'|'time'|'untriggered'|'open'
    return_pct REAL,                    -- 相對於實際觸發價
    return_pct_naive REAL,              -- 相對於 as_of 收盤(基準比較用)
    benchmark_return_pct REAL,
    max_favorable_excursion REAL,
    max_adverse_excursion REAL,
    r_multiple REAL,
    filled_at TIMESTAMP,
    PRIMARY KEY (run_id, symbol, horizon_days)
);
```

`return_pct` 與 `return_pct_naive` **必須同時記錄**。前者是實際計畫的績效,後者是「不管進場規則,隔日就買」的基準。兩者比較才能回答「進場規則到底有沒有加分」。

### 9.4 回填指令

```bash
flowscope backfill --horizon-days 20
```

掃描所有 `expires_on <= today` 且 `filled_at IS NULL` 的紀錄,抓取後續價格,依 §8 的計畫規則模擬:是否觸發、觸發後是否觸及停損或目標、最終 R 倍數。

**必須設為排程(Windows 工作排程器),每個交易日執行一次。** README 需附設定步驟。

### 9.5 績效報表

```bash
flowscope report performance --since 2026-09-01 --group-by config_hash
```

輸出:
- 樣本數、觸發率、平均 R、勝率、期望值
- **含未觸發的期望值**(未觸發者以 0 計入)vs 僅計已觸發
- 對比大盤同期
- 對比蠢基準(見 §10.2)
- 名單週間重疊率

---

## 10. 驗證要求

### 10.1 必要測試

| 檔案 | 內容 |
|---|---|
| `test_pit.py` | 200 組隨機 `(symbol, as_of)`,斷言無未來資料。**優先級最高** |
| `test_factors_technical.py` | 每個因子的 golden fixture(手算驗證的小樣本) |
| `test_factors_chips.py` | 同上,特別測試集保資料的週頻對齊與缺值處理 |
| `test_scoring.py` | 正規化的邊界:全部相同值、只有一檔、全部 null |
| `test_planner.py` | 五種狀態各至少一組 fixture;測試 stop > entry 等不合理輸出被攔截 |
| `test_determinism.py` | 同樣輸入跑兩次,輸出 parquet 的 hash 必須相同 |

覆蓋率門檻:`factors/`、`scoring/`、`planner/` ≥ 85%。

### 10.2 蠢基準(**必須實作,用於對照**)

```bash
flowscope run --config configs/naive_baseline.yaml
```

基準規則:
```
1. 20 日均額 > 30M
2. close 距 250 日高點 < 15%
3. volume[t] > 1.5 × MA(volume, 20)
4. close > MA60
依 60 日報酬排序取 Top 30
```

**這是整個專案最重要的驗收條件之一:** 如果完整系統在前進紀錄上贏不過這四行規則,那所有籌碼因子與加權機制都只是自我娛樂。README 必須明確寫下這一點。

### 10.3 啟動時自我檢查

每次 `run` 開始前執行並在失敗時中止:

1. 交易日曆涵蓋 `as_of`
2. 集保資料的 `publish_date` 落後不超過 14 天(超過表示爬蟲壞了)
3. 股票池大小在合理區間 (1,000–2,500)
4. 沒有任何因子回傳 100% null
5. config 的維度權重加總 = 1.0 (±1e-6)

---

## 11. Config 範例

`configs/tw_swing.yaml`:

```yaml
market: TW
horizon: swing

account:
  value: 1000000            # NT$
  risk_per_trade_pct: 1.0
  max_position_pct: 15.0

universe:
  top_n: 30

gates:
  l0:
    min_avg_dollar_volume: 30_000_000
    min_price: 10.0
    min_listing_days: 250
    min_trading_day_ratio: 0.90
    exclude_types: [ETF, ETN, REIT, TDR, PREFERRED]
    exclude_markets: [EMERGING]
  l1:
    altman_z_min: 1.8
    altman_z_min_nonmfg: 1.1
    beneish_m_flag: -1.78
    max_negative_ocf_quarters: 1
    max_capital_raise_pct: 20.0
    require_clean_audit: true
    ar_growth_spread_flag: 30.0
    inventory_growth_spread_flag: 30.0
  post_score:
    atr_pct_range: [2.0, 12.0]
    distribution_warning_reject: 3
    distribution_warning_flag: 2

weights:
  dimensions:
    technical: 0.30
    chips: 0.30
    theme: 0.20
    financial: 0.20      # Phase 1 財務不排序 → 此權重會被重新分配
  # Phase 1 實際使用(financial 停用後正規化):
  # technical 0.375 / chips 0.375 / theme 0.25

factors:
  technical:
    enabled: [T01, T02, T03, T05, T10, T11, T13, T15, T18, T19, T21]
    params:
      T02: { window: 60 }
      T05: { windows: [20, 60, 120], weights: [0.4, 0.4, 0.2] }
      T10: { bb_period: 20, bb_std: 2.0, percentile_window: 250 }
      T19: { pivot_lookback: 60, min_base_days: 15, max_base_range: 0.25 }
  chips:
    holder_mode: composite
    enabled: [C05, C06, C07, C08, C11, C12, C15, C17]
    params:
      C05: { slope_weeks: 8, zscore_weeks: 52 }
      C06: { window: 20 }
      C07: { window: 20 }
      C11: { window: 20 }
  theme:
    enabled: [M01, M02, M03, M04]
    params:
      M01: { window: 20 }
      M04: { ma_months: 3 }

scoring:
  winsorize: [0.01, 0.99]
  missing:
    fill_value: 0.5
    max_missing_ratio_per_dimension: 0.4
    max_missing_ratio_total: 0.25
    redistribute_weight: true

planner:
  time_stop_days: 10
  extended_atr_threshold: 1.5
  breakout_volume_multiple: 1.5
  pullback_volume_dryup: 0.7
  stop_atr_multiple: 2.0
  max_risk_per_share_pct: 10.0

output:
  formats: [parquet, json, markdown]
  include_raw_factor_values: true
```

**注意 `weights.dimensions.financial: 0.20` 的處理:** Phase 1 財務維度沒有排序因子,啟動時應偵測到並自動把該權重按比例分配給其餘三者,同時在 manifest 記錄。這樣 Phase 3 加入財務排序因子時,config 不需要改。

---

## 12. CLI 介面

```bash
# 主要執行
flowscope run --config configs/tw_swing.yaml [--as-of 2026-08-18] [--no-cache]

# 資料維護
flowscope data sync --source finmind --start 2020-01-01
flowscope data sync --source tdcc --weekly        # 排程每週執行
flowscope data validate                            # 檢查缺漏與 PIT 一致性

# 診斷
flowscope diagnose collinearity --market TW --horizon swing
flowscope diagnose sensitivity --as-of 2026-08-18
flowscope diagnose funnel --as-of 2026-08-18

# 紀錄
flowscope backfill [--horizon-days 20]
flowscope report performance --since 2026-09-01 [--group-by config_hash]
flowscope report run --run-id 20260818T163000Z-a3f9c1
```

---

## 13. 實作順序與完成定義

**嚴格依序,每一步的 DoD 未達成不得進入下一步。**

| # | 內容 | DoD |
|---|---|---|
| 1 | 專案骨架、config schema、CLI 空殼 | `flowscope --help` 可執行;mypy strict 通過 |
| 2 | 資料層:FinMind provider + Parquet 快取 + 交易日曆 + 除權息還原 | 可取得任一股票 3 年還原日線;`test_pit.py` 通過 |
| 3 | **集保 provider (FinMind) + 解析 + PIT 對齊** | *(2026-08-18 修訂)* 可取得任一股票 2 年週頻股權分散;`publish_date` 正確設定為 `data_date + 7d` 並對齊交易日。**PIT 要求不變**,僅資料來源由爬蟲改為 FinMind |
| 4 | Universe + L0/L1 Gate + 漏斗輸出 | 輸出 §5.3 格式的漏斗;各關剩餘檔數合理 |
| 5 | 技術面因子 T01–T21 | 每個因子有 golden fixture 測試;共線性報告可產出 |
| 6 | **籌碼面因子 C01–C17** | 同上;C15/C16 型態因子有正負樣本各 3 組 fixture |
| 7 | 題材面因子 M01–M05 | 同上 |
| 8 | 正規化 + 聚合 + 缺失處理 | `test_scoring.py` 通過;可產出第一份 Top 30 |
| 9 | **Run manifest + SQLite + 前進紀錄寫入** | 執行後 DB 有完整紀錄;config_hash 可重現 |
| 10 | 交易計畫產生器 | 五種狀態各有 fixture;不合理輸出(stop>entry)被攔截 |
| 11 | 回填指令 + Windows 排程設定文件 | 可對歷史 run 回填 20 日報酬 |
| 12 | 敏感度分析 + 蠢基準 + 績效報表 | 可產出 §7.5 與 §10.2 的對照表 |
| 13 | README + 執行手冊 | 他人可依文件從零建置並跑出結果 |

**步驟 3、6、9 是本專案的關鍵路徑。** 若時間有限,寧可減少技術面因子數量,也不要縮減籌碼資料的品質與前進紀錄的完整性。

---

## 14. 需要人類決定的事項(實作者不要自行假設)

實作到相應步驟時停下來詢問:

1. **帳戶規模**:`account.value` 的實際數字(影響部位計算與 `position_too_small` 的觸發頻率)
2. **集保歷史深度**:集保網站只提供近期資料。是否接受先從現在開始累積(前進紀錄要等 3–6 個月才有意義),或另尋歷史來源
3. **下市股票清單**:FinMind 是否提供?若否,是否接受 Phase 1 帶有倖存者偏差並明確記錄
4. **產業分類**:採用 TWSE 官方分類(較粗)或自訂主題分類(較貼近題材但需人工維護)
5. **是否納入興櫃**:預設排除
6. **`top_n = 30` 是否合適**:取決於使用者實際能人工檢視的數量

---

## 15. 明確的禁止事項

實作者**不得**做以下事情,即使看起來有幫助:

1. ❌ 加入任何 LLM / AI API 呼叫(Phase 1 完全不需要)
2. ❌ 連接任何券商 API 或產生下單指令
3. ❌ 用歷史資料最佳化權重(這是過擬合,且本專案年交易次數太少,不具統計意義)
4. ❌ 用固定門檻取代橫斷面百分位
5. ❌ 以 0 或均值填補缺失的因子原始值
6. ❌ 略過 `publish_date` 檢查以「簡化」查詢
7. ❌ 從其他專案複製程式碼
8. ❌ 為了讓候選數看起來合理而調整 Gate 參數
9. ❌ 在沒有 forward log 的情況下宣稱某個設定「比較好」

---

## 附錄 A:因子快速索引

| ID | 名稱 | 維度 | 族群 | Phase 1 啟用 |
|---|---|---|---|---|
| T01 | ma_alignment_score | technical | 趨勢 | ✅ |
| T02 | linreg_slope_r2 | technical | 趨勢 | ✅ |
| T03 | adx | technical | 趨勢 | ✅ |
| T04 | supertrend_state | technical | 趨勢 | ⬜ |
| T05 | relative_strength_pct | technical | 動能 | ✅ |
| T06 | mansfield_rsi | technical | 動能 | ⬜ (與 T05 共線) |
| T07 | macd_histogram_slope | technical | 動能 | ⬜ |
| T08 | roc_rank_composite | technical | 動能 | ⬜ (與 T05 共線) |
| T09 | atr_percent | technical | 波動 | ✅ (gate/sizing) |
| T10 | bb_width_percentile | technical | 波動 | ✅ |
| T11 | ttm_squeeze | technical | 波動 | ✅ |
| T12 | volatility_contraction | technical | 波動 | ⬜ |
| T13 | obv_divergence | technical | 量能 | ✅ |
| T14 | cmf | technical | 量能 | ⬜ |
| T15 | volume_dryup_ratio | technical | 量能 | ✅ |
| T16 | volume_surge | technical | 量能 | ✅ (planner) |
| T17 | up_down_volume_ratio | technical | 量能 | ⬜ |
| T18 | pct_from_52w_high | technical | 結構 | ✅ |
| T19 | base_breakout | technical | 結構 | ✅ |
| T20 | distance_to_ma20_atr | technical | 結構 | ✅ (planner) |
| T21 | pivot_structure | technical | 結構 | ✅ |
| C01 | big_holder_slope | chips | 集保 | (併入 C05) |
| C02 | big_holder_zscore | chips | 集保 | (併入 C05) |
| C03 | retail_exit_slope | chips | 集保 | (併入 C05) |
| C04 | avg_holding_growth | chips | 集保 | (併入 C05) |
| C05 | chip_concentration_composite | chips | 集保 | ✅ |
| C06 | institutional_net_intensity | chips | 法人 | ✅ |
| C07 | trust_continuity | chips | 法人 | ✅ |
| C08 | foreign_persistence | chips | 法人 | ✅ |
| C09 | dealer_noise_penalty | chips | 法人 | ⬜ |
| C10 | institutional_price_efficiency | chips | 法人 | ⬜ |
| C11 | margin_divergence | chips | 融資券 | ✅ |
| C12 | margin_ratio_level | chips | 融資券 | ✅ |
| C13 | short_pressure | chips | 融資券 | ⬜ (資訊用) |
| C14 | margin_short_ratio_change | chips | 融資券 | ⬜ |
| C15 | accumulation_pattern | chips | 型態 | ✅ |
| C16 | distribution_warning | chips | 型態 | ✅ (排除層) |
| C17 | chip_stability | chips | 型態 | ✅ |
| M01 | industry_rs_percentile | theme | — | ✅ |
| M02 | industry_breadth | theme | — | ✅ |
| M03 | stock_vs_industry_rs | theme | — | ✅ |
| M04 | revenue_momentum | theme | — | ✅ |
| M05 | revenue_acceleration | theme | — | ⬜ |

---

*本文件為系統規格,非投資建議。系統輸出僅供縮小研究範圍之用,所有交易決策由使用者自行判斷與承擔。*
