# FlowScope — Implementation Review Protocol v1.0

> **用途:** Codex 完成任一階段後,把這份文件連同程式碼一起丟給 Claude,Claude 依此執行結構化審查。
> **配套文件:** `FlowScope_SPEC_v1.md`(以下簡稱 SPEC)
> **審查對象:** Codex 的實作成果
> **審查者:** Claude

---

## 0. 使用方式

### 0.1 給使用者(鵬睿)

每完成 SPEC §13 的一個步驟,開一個新對話,貼上:

```
請依 FlowScope_Review_Protocol.md 審查 Codex 完成的 Step N。
[附上這份文件 + SPEC + 下方「必附證據」清單的內容]
```

### 0.2 必附證據清單

**不要只貼程式碼。** 沒有下列證據的審查只是讀程式碼,抓不到真正的問題:

| 證據 | 取得方式 | 為何必要 |
|---|---|---|
| 目錄樹 | `tree /F src tests configs` | 看結構是否偏離 SPEC |
| 相關模組原始碼 | 直接貼 | — |
| 測試檔原始碼 | 直接貼 | **測試品質比實作品質更能反映真實狀況** |
| 測試執行結果 | `pytest -v --cov=src/flowscope --cov-report=term-missing` | 看實際通過與覆蓋率 |
| 型別檢查 | `mypy src --strict` | — |
| Lint | `ruff check src tests` | — |
| 一次真實執行的輸出 | `flowscope run --config configs/tw_swing.yaml` 完整終端輸出 | **最重要**。程式碼看起來對但跑起來錯是常態 |
| manifest.json | 該次執行產生的 | 檢查 PIT 與漏斗 |
| candidates.parquet 前 10 列 | `python -c "import polars as pl; print(pl.read_parquet(...).head(10))"` | 看真實數值是否合理 |
| Codex 的自述 | Codex 說它做了什麼、跳過了什麼 | 用來比對它說的與實際做的 |

### 0.3 審查者(Claude)的行為準則

1. **先跑對抗性檢查 (§2),再讀實作。** 順序反了會被漂亮的程式碼誤導。
2. **測試檔要當成主要審查對象,不是附屬品。** 一個假測試比沒有測試更危險。
3. **不接受「這部分之後會補」。** SPEC 的 DoD 是二元的。
4. **輸出必須使用 §7 的固定格式**,包含明確的 PASS / CONDITIONAL / FAIL 判定。
5. **不要為了鼓勵而放水。** 這個專案的核心風險是「看起來能跑但結果是錯的」,而使用者不會知道。
6. **看到數值輸出時,自己動手驗算至少 2 個。** 不要相信程式碼的自述。

---

## 1. 快速否決條件 (Instant FAIL)

任一條成立,直接判 FAIL,不需要繼續審查:

| # | 條件 | 檢查方式 |
|---|---|---|
| F1 | 存在任何 LLM / AI API 呼叫 | `grep -rniE "anthropic\|openai\|gemini\|langchain\|llm" src/` |
| F2 | 存在券商 API 或下單相關程式碼 | `grep -rniE "order\|broker\|shioaji\|fugle\|place_order\|下單" src/` |
| F3 | 從其他專案複製的程式碼 | 搜尋 `quantflow`, `swingradar`, `chokepoint` 等字串;檢查註解語氣是否與其餘不一致 |
| F4 | 缺失值以 0 或均值填補在因子層 | `grep -rnE "fill_null\(0\|fillna\(0\|fill_nan\(0\|\.mean\(\)\)" src/flowscope/factors/` |
| F5 | 因子直接使用固定門檻排序 | 見 §2.4 |
| F6 | `publish_date` 未實作或等於 `data_date`(集保資料) | 見 §2.1 |
| F7 | 測試存在但實質上什麼都沒斷言 | 見 §2.6 |
| F8 | 未寫 forward log 就宣稱某設定較好 | 檢查 README / commit message |

---

## 2. 對抗性檢查(**先做這一節**)

這些是 LLM 實作者最常見的失敗模式,而且**不會在測試中暴露**。逐條檢查。

### 2.1 PIT 洩漏(最高優先)

```bash
# 檢查 1: 所有資料存取是否都經過 as_of filter
grep -rn "publish_date" src/flowscope/ | wc -l
# 若少於因子數量,幾乎確定有直接繞過的路徑

# 檢查 2: 集保 publish_date 設定
grep -rn -A5 "publish_date" src/flowscope/data/providers/finmind.py   # (2026-08-18) 集保改由 FinMind 取得

# 檢查 3: 是否有讀 parquet 後未過濾就用
grep -rn "read_parquet\|scan_parquet" src/ 
```

**必須確認:**

- [ ] `as_of_filter()` 或等效函式存在,且所有 provider 回傳前都經過它
- [ ] TDCC 的 `publish_date = data_date + 7d` 並向後對齊交易日,**不是** `= data_date`
- [ ] 財報 `publish_date` 用實際公布日,若用推估則 Q4 為 +75 天而非 +45 天
- [ ] `shares_outstanding` 取的是 `as_of` 當時的值,不是最新值
- [ ] 除權息還原是 backward adjustment,且**還原基準日不晚於 as_of**

**最陰險的一種洩漏:** 用最新價為基準做 backward adjustment,然後拿去算歷史因子。這會讓所有歷史價格隱含未來的除權息資訊。要求 Codex 說明還原基準點。

**要求 Codex 提供的證據:**
```python
# 挑一檔 2025 年有除權息的股票,同一個 as_of 用兩種方式取價:
# (a) as_of = 2025-06-01 時計算的還原價序列
# (b) as_of = 2026-08-18 時計算的 2025-06-01 之前的還原價序列
# 兩者的「報酬率序列」必須完全相同(價格絕對值可以不同)
```
若不同 → PIT 洩漏,FAIL。

### 2.2 橫斷面 vs 時間序列混淆

**這是評分層最容易錯的地方。** 百分位必須是「同一天、全部股票之間」的排名,不是「同一檔股票、跨時間」的排名。

```bash
grep -rn -B3 -A3 "rank\|percentile\|qcut" src/flowscope/scoring/
```

**必須確認:**
- [ ] rank 的 group by 是 `as_of`(或根本沒有時間維度,因為只跑單日)
- [ ] **不是** `group_by("symbol")`
- [ ] Winsorize 在 rank **之前**(rank 之後 winsorize 是 no-op,是明顯的邏輯錯誤)
- [ ] `direction == -1` 的處理是 `1 - value`,且只做一次(檢查是否在因子層和評分層各做一次,導致抵消)

**驗算方式:** 從 `candidates.parquet` 取任一因子的 `normalized_value` 欄位,確認:
- 值域在 [0, 1]
- 分布接近均勻(百分位排名的必然結果),若呈常態或集中在 0.5 附近 → 實作錯誤
- 全體平均應該 ≈ 0.5

### 2.3 min_periods 陷阱

```bash
grep -rn "rolling\|min_periods\|window_size" src/flowscope/factors/
```

**必須確認:**
- [ ] 所有 rolling 都有明確的 `min_periods = window`(polars 的 `min_periods` 預設行為要確認)
- [ ] **不得**出現 `min_periods=1`——那會讓上市第二天的股票也算得出 250 日均線
- [ ] 每個因子的 `min_history_days` 有被實際檢查,不只是宣告了屬性但沒用

**驗算:** 找一檔上市 300 天的股票,`pct_from_52w_high` 應該算得出來;找一檔上市 200 天的,應該回傳 `null` 而不是用 200 天的高點。

### 2.4 config 沒有真的被使用

**極常見:** Codex 寫了完整的 config schema,但函式內部仍用預設參數。

```bash
# 找出函式簽章中的硬編碼預設值
grep -rnE "def .*\(.*=(5|10|14|20|26|50|52|60|120|250|2\.0|1\.5|0\.7)" src/flowscope/factors/
```

**必須確認:**
- [ ] 因子的所有窗口參數都從 `params` dict 讀取
- [ ] 沒有 `window = params.get("window", 20)` 這種寫法(應該是 `params["window"]`,缺了就該報錯)
- [ ] Gate 門檻全部來自 config
- [ ] planner 的 ATR 倍數、量能倍數來自 config

**驗證方式:** 改一個 config 值(例如 `T02.window: 60 → 30`),重跑,確認 Top 30 名單有變化。**若名單完全沒變,config 沒接上。**

### 2.5 決定性破壞

```bash
grep -rn "set(\|dict(\|\.keys()\|\.items()\|random\|shuffle\|hash(" src/flowscope/
```

**必須確認:**
- [ ] 沒有對 `set` 迭代後直接影響輸出順序
- [ ] 排名遇到 tie 時有明確的次級排序鍵(建議 `symbol` 字典序),否則 tie 的順序不穩定
- [ ] 輸出前有 `.sort()`
- [ ] 沒有用 Python 內建 `hash()` 算 config_hash(每次執行 seed 不同)——必須是 `hashlib.sha256`

**驗證:** 連跑兩次同一個 `as_of`,比對 `candidates.parquet` 的檔案 hash:
```bash
flowscope run --config configs/tw_swing.yaml --as-of 2026-08-18
# 記下 run_id_A
flowscope run --config configs/tw_swing.yaml --as-of 2026-08-18
# 記下 run_id_B
certutil -hashfile data\runs\{A}\candidates.parquet SHA256
certutil -hashfile data\runs\{B}\candidates.parquet SHA256
```
不同 → FAIL。

### 2.6 假測試偵測(**測試品質審查**)

依序檢查,發現任一項就標記該測試無效:

| 症狀 | 範例 | 判定 |
|---|---|---|
| 只斷言不為空 | `assert result is not None` / `assert len(df) > 0` | 無效 |
| 斷言值等於程式自己算出來的 | `assert compute(x) == compute(x)` | 無效 |
| **Golden fixture 由被測程式產生** | 註解寫「用 v1 輸出當基準」 | **最危險,等於零測試** |
| 只測 happy path | 沒有 null / 資料不足 / 全同值的案例 | 不足 |
| mock 掉核心邏輯 | `mocker.patch("compute_slope", return_value=0.5)` 然後測 compute_slope | 無效 |
| 浮點用 `==` | `assert score == 0.7` | 脆弱 |
| try/except 包住斷言 | | 無效 |

**Golden fixture 的正確標準:**
> fixture 的期望值必須是**人工手算**或**由獨立的參考實作**產生,並在註解中寫明計算過程。

審查時對每個因子測試問一句:**「這個期望值是怎麼來的?」** Codex 答不出「手算」或「參考來源」,該測試就不算數。

### 2.7 例外吞噬

```bash
grep -rn -A2 "except" src/flowscope/ | grep -iE "pass$|continue$|return None$|return 0"
```

**必須確認:**
- [ ] 沒有 bare `except:` 或 `except Exception: pass`
- [ ] 資料抓取失敗會拋出或明確記錄,不是靜默回傳空 DataFrame
- [ ] **爬蟲失敗時不得回傳空結果讓流程繼續跑**——這會讓整個籌碼維度變成 0.5 填充值,而漏斗看起來一切正常

這一條對集保資料特別重要。*(2026-08-18 修訂:集保改由 FinMind `TaiwanStockHoldingSharesPer` 取得)* FinMind 回傳空集合、權限不足(`Your level is register`)或請求超限時,系統必須**中止並報錯**,不是安靜地產出一份沒有籌碼訊號的名單。

### 2.8 殘留的假資料

```bash
grep -rniE "mock\|dummy\|fake\|sample_data\|todo\|fixme\|hardcode\|for now\|temporar" src/flowscope/
```

任何在 `src/`(非 `tests/`)下的 mock 資料都是 FAIL。

---

## 3. 分步驟驗收

對照 SPEC §13。只審查 Codex 宣稱完成的步驟,但**必須回頭抽查前面步驟是否被後續改動破壞**。

### Step 2 — 資料層

- [ ] `PriceProvider` 回傳欄位與 SPEC §4.3 完全一致(欄名、單位)
- [ ] 快取 key 包含所有影響結果的參數;`--no-cache` 有效
- [ ] 交易日曆來自實際資料(TWSE 有交易的日期),不是「排除週末」
- [ ] 還原價的驗算:挑一檔已知除權息的股票,手動驗證除權日前後的還原價連續
- [ ] `test_pit.py` 有 200 組隨機抽樣,不是 3 組

**手動驗算(必做):** 選 2330 台積電,取 2025 年任一次除權息日,確認:
```
adj_close[除權日-1] / adj_close[除權日] ≈ 1 (誤差 < 1%)
raw_close[除權日-1] / raw_close[除權日] > 1 (有跳空)
```

### Step 3 — 集保資料層(**關鍵路徑**)

*(2026-08-18 修訂:資料來源由集保官網爬蟲改為 FinMind `TaiwanStockHoldingSharesPer`。PIT 要求完全不變。)*

- [ ] 原始 API 回應有存到 `data/raw/tdcc/{data_date}/`(保留原始回應,不可只存解析結果)
- [ ] **級距以股數下界判定,不得寫死 tier 序號**(SPEC §6.2 修訂版)。`big_holder_pct` 取 `lower >= 400_001`,`retail_pct` 取 `lower <= 5_001`
- [ ] 「合計」列有明確排除,未混入任何加總
- [ ] FinMind 權限不足或超限時中止並報錯,不得回傳空集合
- [ ] `share_pct` 各級距加總 ≈ 100%(容忍 0.5% 誤差);不符者應標記
- [ ] 有 rate limit 與 retry with backoff(FinMind 免費層約 600 req/hr,贊助層較高)
- [ ] **`publish_date` 正確**(見 §2.1)
- [ ] 週頻資料對齊到日頻時,用的是 forward fill 且不跨越 `publish_date`

**手動驗算:** 取任一檔股票近 3 週的 `big_holder_pct`,對照集保官網原始頁面確認數字一致(集保官網保留約 1 年,近期資料仍可對照)。

### Step 4 — Universe & Gate

- [ ] 漏斗輸出格式符合 SPEC §5.3
- [ ] L0 後剩餘檔數在 500–900 之間(台股合理範圍)。若剩 1,500 或剩 100 → 門檻或計算有問題
- [ ] Altman Z 的製造業/非製造業分流有實作
- [ ] Beneish M 缺資料時回傳 `None` 且標記,**不是**填 0
- [ ] 處置股/注意股清單有實際抓取,不是空清單

**紅旗:** 若 L1 只刷掉個位數檔數,幾乎確定財務排雷沒有真的在跑。台股正常應該刷掉 50–150 檔。

### Step 5 — 技術面因子

逐一驗證下列 5 個(其餘抽查):

| 因子 | 驗算方式 |
|---|---|
| T02 `linreg_slope_r2` | 用 numpy `polyfit` 對同一段 log price 獨立算一次,比對 |
| T05 `relative_strength_pct` | 手算 `(1+r_stock)/(1+r_bench)-1`,確認基準用的是加權指數而非 0050 |
| T11 `ttm_squeeze` | 確認是 BB 完全在 KC **內部**(upper_bb < upper_kc AND lower_bb > lower_kc),常見錯誤是只比一邊 |
| T19 `base_breakout` | **必須輸出 `base_high` / `base_low` / `base_start_date`**,planner 依賴這些欄位。缺了就是 FAIL |
| T20 `distance_to_ma20_atr` | 手算 `(close - MA20) / ATR14` |

- [ ] ATR 用 Wilder smoothing 而非 SMA(常見錯誤)
- [ ] `diagnose collinearity` 可執行並輸出矩陣
- [ ] 啟用的因子中,同維度任兩者 |ρ| ≤ 0.7

### Step 6 — 籌碼面因子(**核心,最嚴格**)

| 因子 | 檢查重點 |
|---|---|
| C05 `chip_concentration_composite` | 子因子的 z-score 是橫斷面還是時間序列?SPEC 意圖是**個股自身歷史的 z-score**(C02),但 composite 的加總必須在橫斷面正規化前保持一致單位。要求 Codex 說明 |
| C05 | 少於 6 個週資料點必須回傳 null |
| C06 | 分母是 `shares_outstanding` 而非成交量 |
| C07 `trust_continuity` | 三個子項的權重 0.4/0.3/0.3 有實作;`max_streak` 是連續買超,不是買超天數 |
| C11 `margin_divergence` | `price_change - margin_change`,符號方向正確(正值 = 健康) |
| C15 `accumulation_pattern` | 三條件 AND 邏輯正確;有正負樣本 fixture 各 3 組 |
| C16 `distribution_warning` | **必須是排除層,不是負分因子**。檢查它是否出現在 `scoring/aggregate.py`(不該出現)而應在 post-scoring |

- [ ] C16 的實作位置:應在 §7.4 post-scoring 排除層。**若被寫成一個負權重因子,判 CONDITIONAL 並要求改**
- [ ] 集保週資料與日頻價量對齊時,無未來洩漏
- [ ] 融資餘額的單位(張 vs 股)全程一致

**手動驗算:** 挑 3 檔近期明顯上漲的股票,人工看它們的 `big_holder_pct` 近 8 週走勢,判斷 `C05` 分數方向是否符合直覺。若一檔大戶比例明顯上升的股票拿到低分 → 符號或單位錯誤。

### Step 8 — 評分

- [ ] 見 §2.2 全部檢查項
- [ ] 缺失處理:`max_missing_ratio_per_dimension` 觸發時,權重重分配有記錄 `weight_redistributed`
- [ ] `financial` 維度權重 0.20 有被自動重分配,manifest 有記錄實際權重
- [ ] `test_scoring.py` 涵蓋:全同值、只有一檔、全 null 三個邊界

**驗算:** 從 `candidates.parquet` 取第 1 名,手動用其 normalized 因子值 × config 權重算出 `total_score`,比對。差異 > 1e-6 → FAIL。

### Step 9 — Manifest & Forward Log

- [ ] `config_hash` 用 sha256,且是對正規化後的 config(key 排序、浮點格式統一)
- [ ] 改動 config 任一值,hash 必須改變;調整 YAML 縮排或 key 順序,hash 不得改變
- [ ] SQLite schema 與 SPEC §9.3 完全一致
- [ ] `candidates.parquet` 包含每個因子的 **raw_value 與 normalized_value 兩欄**
- [ ] `data_versions` 有記錄 `tdcc_latest_publish_date`

### Step 10 — Planner

- [ ] 五種狀態的判定**依序**執行,第一個符合者勝出(不是全部評估後取最高)
- [ ] `WAIT_PULLBACK` 的 entry_condition 包含量縮條件 `MA(vol,5)/MA(vol,20) < 0.7`。**這條被省略是常見偷懶,必查**
- [ ] `initial_stop < entry_zone_low` 恆成立,有 assert 攔截
- [ ] `risk_per_share / close > 0.10` 時轉為 `NO_TRADE`
- [ ] 部位向下取整到 1000 股(整張)
- [ ] `expires_on` 用交易日曆推算,不是 `as_of + timedelta(days=10)`
- [ ] target 用 R 倍數推導,不是固定百分比

**驗算:** 取一份 `plans.json`,對 3 個計畫手算 `risk_per_share`、`position_shares`、`target_2r`。

### Step 11 — 回填

- [ ] `return_pct` 與 `return_pct_naive` 兩者都有寫入
- [ ] 未觸發的計畫標記為 `expired_untriggered`,且**不會被當成 0 報酬混入已觸發的統計**
- [ ] 觸發判定用的是後續日線的 high/low 是否進入 entry_zone,不是收盤價
- [ ] 停損與目標的先後判定:同一天同時觸及時,**保守假設先觸及停損**
- [ ] MFE / MAE 有計算

### Step 12 — 診斷與基準

- [ ] `diagnose sensitivity` 輸出符合 SPEC §7.5 格式,含 Spearman 相關
- [ ] 蠢基準 `configs/naive_baseline.yaml` 存在且可執行
- [ ] 蠢基準確實只用那四條規則,沒有偷偷加籌碼因子
- [ ] `report performance` 可同時輸出系統與基準的對照

---

## 4. 整體健康度檢查

跑完一次真實執行後,檢查輸出是否「看起來像真的」:

| 指標 | 合理範圍 | 異常代表 |
|---|---|---|
| L0 後檔數 | 500–900 | 過多 = 門檻沒生效;過少 = 成交金額單位錯(元 vs 千元) |
| L1 刷掉檔數 | 50–150 | 過少 = 財務排雷沒跑 |
| 最終候選 | = top_n | — |
| `total_score` 分布 | 第 1 名約 0.75–0.90 | > 0.95 = 因子共線嚴重;< 0.65 = 因子互相抵消 |
| 各維度分數相關性 | technical vs chips 應 < 0.5 | 過高 = 兩個維度在測同一件事 |
| `missing_count` 中位數 | ≤ 2 | 過高 = 資料層有缺口 |
| plan_state 分布 | 不應有單一狀態 > 70% | 全是 `WAIT_TRIGGER` = 基底偵測 T19 沒作用 |
| 產業分布 | Top 30 不應有單一產業 > 40% | 過度集中 = 題材因子權重過高或族群輪動 |
| 執行時間 | < 5 分鐘(有快取) | 過久 = 快取沒生效 |

**特別注意 plan_state 分布。** 如果 30 檔裡有 25 檔是 `WAIT_TRIGGER`,代表 `base_breakout` 沒有真的在偵測基底——這是 planner 最容易失效卻不報錯的地方。

---

## 5. 針對 Codex 的追問清單

審查時直接要求 Codex 回答,答不上來即視為未完成:

1. 集保資料的 `publish_date` 你設成什麼?為什麼?
2. 除權息還原的基準日是哪一天?這會不會造成 PIT 洩漏?
3. `test_factors_chips.py` 裡的期望值是怎麼算出來的?
4. 橫斷面百分位的 group by 是什麼欄位?
5. 若我把 `T02.window` 從 60 改成 30,Top 30 名單會變嗎?你驗證過嗎?
6. 集保資料抓取失敗(FinMind 權限不足/超限/回空)時系統會怎樣?會中止還是繼續?
7. C16 `distribution_warning` 實作在哪一層?
8. 兩次執行同一個 as_of,輸出檔案 hash 相同嗎?
9. 你有跳過 SPEC 的哪些部分?為什麼?
10. 系統目前跑不過蠢基準的話,你會怎麼判斷是實作 bug 還是策略無效?

**第 9 題必問。** Codex 通常會誠實回答,而它跳過的部分往往正是最難也最重要的部分。

---

## 6. 常見「表面完成」情境

這些情況會通過 pytest,但系統實際上是壞的:

| 情境 | 偵測方式 |
|---|---|
| 籌碼因子全部回傳 null,被填成 0.5,系統退化成純技術選股 | 檢查 `candidates.parquet` 的 chips 因子 raw_value 有幾成是 null |
| 集保只取到最近 1 週,`big_holder_slope` 全部 null | 檢查 `data/raw/tdcc/` 有幾個日期目錄;FinMind 應可回溯至 2010-01-29 |
| 財務排雷用了 mock 資料 | 檢查 L1 刷掉的檔數與名單合理性 |
| 產業分類全部是 "Unknown" | 檢查 M01–M03 的分母 |
| 交易日曆用「排除週末」,遇到台股補班日/颱風假就錯位 | 檢查是否有台灣國定假日資料來源 |
| 停損永遠等於 `close - 2×ATR`,結構性停損沒實作 | 檢查 `plans.json` 的 `stop_basis` 欄位分布,若全是 `"atr"` → 未實作 |
| 所有計畫的 `time_stop_days` 都一樣但 `expires_on` 算錯 | 手算兩個 |

---

## 7. 審查輸出格式(Claude 必須遵守)

```markdown
# FlowScope Review — Step N — YYYY-MM-DD

## 判定
**PASS / CONDITIONAL / FAIL**

## 一句話結論
(≤ 40 字)

## 快速否決檢查
| # | 項目 | 結果 |
(§1 全部八項)

## 對抗性檢查結果
| 檢查 | 結果 | 證據 |
(§2 各節,附具體行號或輸出片段)

## DoD 對照
| SPEC 要求 | 狀態 | 說明 |
(對應步驟的所有 checkbox)

## 我實際驗算的項目
| 項目 | 我算的 | 程式輸出 | 一致? |
(至少 3 項)

## 必須修正 (Blocking)
1. [檔案:行號] 問題描述 → 具體修法

## 建議修正 (Non-blocking)
1. ...

## 需要 Codex 回答
1. ...

## 給 Codex 的下一步指令
(可直接複製貼給 Codex 的一段文字)
```

**判定標準:**

| 判定 | 條件 |
|---|---|
| PASS | 無 Blocking;§2 對抗性檢查全過;至少 3 項手動驗算一致 |
| CONDITIONAL | 有 Blocking 但都是局部可修;核心邏輯正確 |
| FAIL | 觸發 §1 任一條,或 PIT 洩漏,或測試實質無效,或手動驗算不一致 |

---

## 8. 審查者的自我提醒

寫給未來執行審查的 Claude:

- **不要因為程式碼寫得漂亮就降低標準。** Codex 的程式碼幾乎總是漂亮的。問題出在 PIT、單位、符號方向、config 未接通——這些從程式碼外觀完全看不出來。
- **最有價值的動作是自己算一次。** 拿 `candidates.parquet` 的原始數值手算兩三個因子,比讀 500 行程式碼更能發現問題。
- **測試通過不代表正確。** 先審測試,再審實作。
- **使用者不是專職 quant,他有全職工作和夜間課程。** 他沒有時間自己抓這些細節,所以審查必須替他抓完。同時,要求他改的東西必須具體到可以直接貼給 Codex 執行,不要給抽象建議。
- **系統輸出錯誤的代價是真金白銀。** 一個符號方向反了的籌碼因子,會讓他系統性地買進正在出貨的股票,而且要好幾個月才會從績效上看出來。這是本專案最嚴重的失效模式,審查的第一優先就是防止它。

---

*本文件為工程審查協定,不含投資建議。*
