# FlowScope

台股選股與交易計畫產生器。**全新獨立專案,與任何其他 repo 無關。**

---

## 開始前必讀(每次 session 開始都要讀)

| 順序 | 檔案 | 用途 |
|---|---|---|
| 1 | `PROGRESS.md` | 目前進度、下一步、待決事項、已知問題 |
| 2 | `docs/FlowScope_SPEC_v1.md` | 完整規格,**唯一真實來源** |
| 3 | `docs/FlowScope_Review_Protocol.md` | 每步完成後會被依此審查(參考用,不是實作指引) |

規格與本檔衝突時,以 SPEC 為準。SPEC 有誤或不清楚時,**停下來問人**,不要自行修改 SPEC。

---

## 專案邊界

- 不是 QuantFlow 的一部分,不是 SwingRadar 的延伸或改版
- **不得**從任何其他專案匯入、複製或參考程式碼
- 若在工作區看到 `quantflow` / `swingradar` / `chokepoint` 等目錄,一律忽略

---

## 工作流程

1. 讀 `PROGRESS.md`,確認目前在 SPEC §13 的哪一步
2. **只做當前那一步**,依序推進,不得跳步
3. 該步的 DoD 未達成前不得進入下一步
4. 完成後更新 `PROGRESS.md`
5. Commit,訊息格式:`step-N: 簡短描述`

### 每步完成時必須回報

- 這一步做了什麼
- **跳過了什麼,以及為什麼**(必答,不得省略或含糊帶過)
- 遇到的問題與處理方式
- 需要人類決定的事項

### 回報誠實性要求

適用範圍:本節適用 Claude；Codex 的純文字 code block 回報格式另見 `AGENTS.md`。

- 不得把之前通過的測試或品質檢查寫成最新通過。
- 不得把未提交或未推送的內容寫成已交付。
- 不得省略已知缺口、未完成事項或刻意跳過的工作。

---

## 硬性規則

### 停下來問,不要自行假設

遇到 SPEC §14 列出的六項待決事項時,**停止實作並詢問**。不要用「合理預設值」帶過。

其他該停下來問的情況:
- 資料來源回傳的欄位與 SPEC §4.3 不符
- 某個因子的公式在實際資料上算不出來
- 需要新增 SPEC 未列出的依賴套件
- 發現 SPEC 本身有矛盾或錯誤

### 絕對禁止(完整清單見 SPEC §15)

1. 任何 LLM / AI API 呼叫
2. 任何券商 API 或下單相關程式碼
3. 用歷史資料最佳化權重
4. 用固定門檻取代橫斷面百分位
5. 以 0 或均值填補缺失的因子原始值
6. 略過 `publish_date` 檢查以「簡化」查詢
7. 在 `src/` 下留任何 mock / dummy / 假資料
8. 為了讓輸出「看起來合理」而調整 Gate 參數
9. 在沒有 forward log 的情況下宣稱某個設定「比較好」

### 三個最容易做錯的地方

| 主題 | 要求 | SPEC |
|---|---|---|
| **Point-in-Time** | 所有資料存取必須經過 `publish_date <= as_of` 過濾。集保資料的 `publish_date = data_date + 7 天`(向後對齊交易日),**不是** `= data_date` | §4.1 |
| **橫斷面正規化** | 百分位是「同一天、全部股票之間」的排名,不是同一檔股票跨時間的排名。Winsorize 必須在 rank **之前** | §7.1 |
| **缺失值** | 因子層資料不足一律回傳 `null`,絕不回傳 0 或均值。填補只在 §7.1 統一處理 | §6.0 |

### 例外處理

資料抓取或爬蟲失敗時**必須中止並報錯**,不得靜默回傳空結果讓流程繼續。

集保 (TDCC) 爬蟲特別重要:失敗而不報錯會導致整個籌碼維度變成 0.5 填充值,而漏斗與分數看起來一切正常——這是本專案最嚴重的失效模式。

不得使用 bare `except:` 或 `except Exception: pass`。

---

## 環境

```
OS            Windows 11        → 路徑一律用 pathlib,不得硬編碼 /
Python        3.11+
資料處理       polars 為主;pandas 僅在第三方 API 邊界轉換
技術指標       自行實作,不使用 TA-Lib(C 依賴,Windows 安裝困難)
設定          pydantic v2 + YAML
儲存          Parquet(資料)+ SQLite(manifest / forward log)
CLI           typer
測試          pytest, pytest-cov, hypothesis
品質          ruff + mypy --strict
```

每步完成前必須通過:

```bash
ruff check src tests
mypy src --strict
pytest -v --cov=src/flowscope --cov-report=term-missing
```

`factors/`、`scoring/`、`planner/` 覆蓋率門檻 85%。

---

## 測試要求

**Golden fixture 的期望值必須是人工手算,或來自獨立的參考實作,並在註解中寫明計算過程與來源。**

不得用被測程式自己的輸出當作基準——那等於零測試,但覆蓋率會顯示 100%。

每個因子測試至少涵蓋:
- 一組手算驗證的正常案例(註解寫出算式)
- 資料不足 → 回傳 `null`
- 全部相同值 → 不 crash

不接受這類斷言:`assert result is not None`、`assert len(df) > 0`。

---

## Config 必須真的被使用

常見失敗:寫了完整的 config schema,但函式內部仍用硬編碼預設值。

- 因子的所有窗口參數從 `params` dict 讀取
- 用 `params["window"]` 而非 `params.get("window", 20)`——缺了就該報錯
- 函式簽章不得出現 `window: int = 20` 這類魔術數字
- 驗證方式:改一個 config 值後重跑,Top N 名單必須有變化

---

## 決定性 (Determinism)

同樣的 `as_of` + config 必須產生位元級相同的輸出。

- 排名遇到 tie 時要有明確次級排序鍵(用 `symbol` 字典序)
- 輸出前必須 `.sort()`
- `config_hash` 用 `hashlib.sha256`,**不得**用 Python 內建 `hash()`
- 不得對 `set` 迭代後直接影響輸出順序

---

## 溝通

- **回覆使用繁體中文**
- 程式碼、識別符、commit message 使用英文
- 註解使用繁體中文
- 不確定時直接問,不要猜
