"""FinMind token 權限與資料深度檢查(維運工具,不屬於 pipeline)。

只從環境變數或 .env 讀取 token,不接受命令列參數——避免 token 留在 shell 歷史。
不印出 token 的值,只印出遮蔽後的長度資訊。

用法:
    python scripts/check_finmind_access.py

判讀:
    [OK]   取得資料,權限正常
    [拒絕] 權限不足(HTTP 401/402/403,或 msg 提示 level/sponsor)
    [無資料] API 回 success 但 0 筆——認證正常,只是該範圍沒有資料
    [超限] 觸發速率限制,稍後重試
    [錯誤] 連線或其他非預期狀況
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://api.finmindtrade.com/api/v4/data"

# 每個 dataset 的頻率與鍵值都不同,不能共用同一組探測參數。
# (dataset, 用途, Phase 1 是否硬需求, data_id, start, end)
Probe = tuple[str, str, bool, str | None, str | None, str | None]

DATASETS: list[Probe] = [
    # 日頻,個股
    ("TaiwanStockPrice", "OHLCV 原始價", True, "2330", "2024-01-02", "2024-01-05"),
    ("TaiwanStockPriceAdj", "還原股價(付費)", True, "2330", "2024-01-02", "2024-01-05"),
    ("TaiwanStockMarketValue", "市值 / Altman X4(付費)", True, "2330", "2024-01-02", "2024-01-05"),
    (
        "TaiwanStockInstitutionalInvestorsBuySell",
        "三大法人", True, "2330", "2024-01-02", "2024-01-05",
    ),
    ("TaiwanStockMarginPurchaseShortSale", "融資融券", True, "2330", "2024-01-02", "2024-01-05"),
    ("TaiwanStockSecuritiesLending", "借券餘額", False, "2330", "2024-01-02", "2024-01-05"),
    # 週頻:集保需要整個月的視窗才抓得到
    ("TaiwanStockHoldingSharesPer", "集保股權分散(付費)", True, "2330", "2024-01-01", "2024-01-31"),
    # 月頻 / 季頻:需要跨季視窗
    ("TaiwanStockMonthRevenue", "月營收", True, "2330", "2023-01-01", "2024-06-30"),
    ("TaiwanStockFinancialStatements", "綜合損益表", True, "2330", "2023-01-01", "2024-06-30"),
    ("TaiwanStockBalanceSheet", "資產負債表", True, "2330", "2023-01-01", "2024-06-30"),
    ("TaiwanStockCashFlowsStatement", "現金流量表", True, "2330", "2023-01-01", "2024-06-30"),
    # 事件型:2330 不一定有,放寬到全年
    ("TaiwanStockDividendResult", "除權除息結果", True, "2330", "2023-01-01", "2024-12-31"),
    # 全市場清單:不可帶 data_id,否則必然 0 筆
    ("TaiwanStockDelisting", "下市櫃清單", True, None, "2020-01-01", "2024-12-31"),
    ("TaiwanStockInfo", "台股總覽 / 產業別", True, None, None, None),
    (
        "TaiwanStockDispositionSecuritiesPeriod",
        "處置股(付費)", True, None, "2024-01-01", "2024-03-31",
    ),
    ("TaiwanStockSuspended", "暫停交易(付費)", False, None, "2023-01-01", "2024-12-31"),
    # 指數:data_id 是 TAIEX,不是股票代號
    ("TaiwanStockTotalReturnIndex", "加權報酬指數", True, "TAIEX", "2024-01-02", "2024-01-05"),
]


def load_token() -> str:
    token = os.environ.get("FINMIND_TOKEN", "").strip()
    if token:
        return token
    for candidate in (Path(__file__).resolve().parent.parent / ".env", Path("C:/flowscope/.env")):
        if not candidate.is_file():
            continue
        for line in candidate.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("FINMIND_TOKEN="):
                value = line.split("=", 1)[1].strip()
                if value:
                    return value
    return ""


def request(
    dataset: str,
    token: str,
    data_id: str | None,
    start: str | None,
    end: str | None,
) -> tuple[str, str, list[dict[str, object]]]:
    """回傳 (狀態, 說明, 資料列)。"""
    params: dict[str, str] = {"dataset": dataset, "token": token}
    if data_id:
        params["data_id"] = data_id
    if start:
        params["start_date"] = start
    if end:
        params["end_date"] = end

    url = f"{API}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(url, timeout=60) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:160]
        if exc.code == 429:
            return "超限", "HTTP 429 速率限制", []
        if exc.code in (401, 402, 403):
            return "拒絕", f"HTTP {exc.code} 權限不足", []
        return "錯誤", f"HTTP {exc.code} {body}", []
    except urllib.error.URLError as exc:
        return "錯誤", f"連線失敗 {exc.reason}", []

    msg = str(payload.get("msg", ""))
    lowered = msg.lower()
    if "level" in lowered or "sponsor" in lowered or "upgrade" in lowered:
        return "拒絕", msg[:80], []
    if "limit" in lowered or "requests" in lowered:
        return "超限", msg[:80], []

    rows = payload.get("data") or []
    if not isinstance(rows, list) or not rows:
        # msg=success + 0 筆 = 認證正常,只是該範圍沒資料,不是權限問題
        return "無資料", f"msg={msg or 'unknown'},0 筆", []
    return "OK", f"{len(rows)} 筆", rows


def check_history_depth(token: str) -> None:
    """驗證集保資料是否真的回溯到 2010(文件宣稱值)。"""
    print("\n" + "=" * 92)
    print("集保歷史深度驗證(C05 需要 52 週,深度不足會讓整個籌碼維度失效)")
    print("=" * 92)
    for label, start, end in [
        ("2010 年初(文件宣稱起點)", "2010-01-01", "2010-03-31"),
        ("2015 年中", "2015-06-01", "2015-06-30"),
        ("2024 年初", "2024-01-01", "2024-01-31"),
    ]:
        status, detail, rows = request(
            "TaiwanStockHoldingSharesPer", token, "2330", start, end
        )
        first = str(rows[0].get("date")) if rows else "—"
        print(f"  {label:<28} {status:<8} {detail:<16} 最早日期={first}")
        time.sleep(0.5)


def check_financial_columns(token: str) -> None:
    """檢查財報是否帶「實際公布日」欄位。

    這是 FinMind vs TEJ 的決勝點:若 FinMind 已提供公布日,
    就不需要用 Q4 +75 天的保守推估,PIT 風險大幅下降。
    """
    print("\n" + "=" * 92)
    print("財報公布日檢查(PIT 關鍵。無公布日則須以 Q4 +75d 保守推估)")
    print("=" * 92)
    status, detail, rows = request(
        "TaiwanStockFinancialStatements", token, "2330", "2023-01-01", "2024-06-30"
    )
    if status != "OK":
        print(f"  取不到資料:{status} {detail}")
        return
    columns = sorted(rows[0].keys())
    print(f"  回傳欄位:{', '.join(columns)}")
    hints = [c for c in columns if any(k in c.lower() for k in ("publish", "announce", "release"))]
    if hints:
        print(f"  [OK] 疑似公布日欄位:{', '.join(hints)}")
    else:
        print("  [!] 沒有公布日欄位。`date` 是財報期別(季末),不是公布日。")
        print("      Step 2 必須自行推導 publish_date,Q4 用 +75 天而非 +45 天。")


def main() -> int:
    token = load_token()
    if not token:
        print("找不到 FINMIND_TOKEN。")
        print("請設定環境變數,或在 C:/flowscope/.env 填入 FINMIND_TOKEN=...")
        return 2

    print(f"token 已載入(長度 {len(token)},開頭 {token[:4]}***,不顯示完整值)\n")
    print(f"{'dataset':<42} {'狀態':<10} 說明")
    print("-" * 92)

    blocked: list[str] = []
    throttled = False
    for dataset, purpose, required, data_id, start, end in DATASETS:
        status, detail, _ = request(dataset, token, data_id, start, end)
        print(f"{dataset:<42} [{status}]{'':<{max(0, 8 - len(status))}} {purpose} — {detail}")
        if status == "拒絕" and required:
            blocked.append(f"{dataset}({purpose})")
        if status == "超限":
            throttled = True
        time.sleep(0.4)

    print("-" * 92)

    if throttled:
        print("\n[!] 觸發速率限制,部分結果不可信。等限制重置後重跑。")
        return 3

    if blocked:
        print(f"\n[!] {len(blocked)} 個 Phase 1 硬需求 dataset 權限不足:")
        for name in blocked:
            print(f"    - {name}")
        print("\n訂閱層級可能不足。詳見 docs/FinMind_API_Inventory.md")
        return 1

    check_history_depth(token)
    check_financial_columns(token)

    print("\n[OK] 權限檢查通過,Phase 1 所需 dataset 均可存取。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
