# PROGRESS

> 每完成 SPEC §13 的一步就更新此檔。這是跨 session 的記憶,不要省略。

---

## 目前狀態

**Step 1 完成。**

下一步:SPEC §13 **Step 2 — 資料層:FinMind provider + Parquet 快取 + 交易日曆 + 除權息還原**

DoD:`flowscope --help` 可執行;`mypy src --strict` 通過

---

## 已完成步驟

| Step | 內容 | 完成日 | DoD 達成 | Commit |
|---|---|---|---|---|
| 1 | 專案骨架、config schema、CLI 空殼 | 2026-08-18 | 是 | `step-1: initialize project skeleton` |

---

## 跳過或簡化的部分

> 誠實記錄。這一欄是審查時的第一個檢查點。

| Step | 跳過了什麼 | 原因 | 是否需補做 |
|---|---|---|---|
| 1 | 資料 provider、PIT 過濾、因子、評分、planner、manifest、forward log | Step 1 只要求骨架、config schema、CLI 空殼；不得跳到後續步驟 | 是，依 SPEC §13 後續步驟補做 |
| 1 | §14 的實際帳戶規模與 `top_n` 決策 | Step 1 只建 schema 與 SPEC §11 範例 config；實際策略決策尚未到相應實作步驟 | 是，進入 planner/評分實作前確認 |

---

## 待人類決定(對應 SPEC §14)

| # | 事項 | 狀態 | 決定 |
|---|---|---|---|
| 1 | 帳戶規模 `account.value` | 待決 | |
| 2 | 集保歷史深度(是否接受從現在開始累積) | 待決 | |
| 3 | 下市股票清單來源(FinMind 是否提供) | 待決 | |
| 4 | 產業分類(TWSE 官方 vs 自訂主題) | 待決 | |
| 5 | 是否納入興櫃 | 預設排除 | |
| 6 | `top_n` 是否為 30 | 預設 30 | |

---

## 已知問題

| # | 問題 | 影響範圍 | 狀態 |
|---|---|---|---|
| 1 | `flowscope.exe` 安裝於 user Scripts 目錄，但該目錄目前不在系統 `PATH` | 直接在新 shell 執行 `flowscope` 可能找不到命令；本次以臨時加入 `%APPDATA%\Python\Python313\Scripts` 驗證 entry point | 已記錄 |

---

## 審查紀錄

| 日期 | Step | 判定 | 主要 blocking 項 |
|---|---|---|---|
| — | — | — | — |
