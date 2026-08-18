"""FinMind token 權限檢查(一次性工具,不進 repo)。

只從環境變數或 .env 讀取 token,不接受命令列參數——避免 token 留在 shell 歷史。
不印出 token 的值,只印出遮蔽後的長度資訊。

用法:
    python check_finmind_access.py
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://api.finmindtrade.com/api/v4/data"

# (dataset, 用途, Phase 1 是否為硬需求)
DATASETS: list[tuple[str, str, bool]] = [
    ("TaiwanStockPrice", "OHLCV 原始價", True),
    ("TaiwanStockPriceAdj", "還原股價(付費)", True),
    ("TaiwanStockHoldingSharesPer", "集保股權分散(付費)", True),
    ("TaiwanStockMarketValue", "市值 / Altman X4(付費)", True),
    ("TaiwanStockInstitutionalInvestorsBuySell", "三大法人", True),
    ("TaiwanStockMarginPurchaseShortSale", "融資融券", True),
    ("TaiwanStockSecuritiesLending", "借券餘額", False),
    ("TaiwanStockMonthRevenue", "月營收", True),
    ("TaiwanStockFinancialStatements", "綜合損益表", True),
    ("TaiwanStockBalanceSheet", "資產負債表", True),
    ("TaiwanStockCashFlowsStatement", "現金流量表", True),
    ("TaiwanStockDividendResult", "除權除息結果", True),
    ("TaiwanStockDelisting", "下市櫃清單", True),
    ("TaiwanStockInfo", "台股總覽 / 產業別", True),
    ("TaiwanStockTotalReturnIndex", "加權報酬指數", True),
    ("TaiwanStockDispositionSecuritiesPeriod", "處置股(付費)", True),
    ("TaiwanStockSuspended", "暫停交易(付費)", False),
]


def load_token() -> str:
    token = os.environ.get("FINMIND_TOKEN", "").strip()
    if token:
        return token
    env_file = Path(__file__).resolve().parent / ".env"
    for candidate in (env_file, Path("C:/flowscope/.env")):
        if not candidate.is_file():
            continue
        for line in candidate.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("FINMIND_TOKEN="):
                return line.split("=", 1)[1].strip()
    return ""


def probe(dataset: str, token: str) -> tuple[str, str]:
    """回傳 (狀態, 說明)。狀態為 OK / DENIED / EMPTY / ERROR。"""
    params = {
        "dataset": dataset,
        "data_id": "2330",
        "start_date": "2024-01-02",
        "end_date": "2024-01-05",
        "token": token,
    }
    url = f"{API}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:200]
        if exc.code in (401, 402, 403):
            return "DENIED", f"HTTP {exc.code} 權限不足"
        return "ERROR", f"HTTP {exc.code} {body}"
    except urllib.error.URLError as exc:
        return "ERROR", f"連線失敗 {exc.reason}"

    msg = str(payload.get("msg", ""))
    if "level" in msg.lower() or "sponsor" in msg.lower():
        return "DENIED", msg[:80]
    rows = payload.get("data") or []
    if not rows:
        return "EMPTY", msg[:80] or "回傳 0 筆(可能是權限或日期範圍)"
    return "OK", f"{len(rows)} 筆"


def main() -> int:
    token = load_token()
    if not token:
        print("找不到 FINMIND_TOKEN。")
        print("請先設定環境變數,或在 C:/flowscope/.env 填入 FINMIND_TOKEN=...")
        return 2

    print(f"token 已載入(長度 {len(token)},開頭 {token[:4]}***,不顯示完整值)\n")
    print(f"{'dataset':<42} {'狀態':<8} 說明")
    print("-" * 92)

    blocked_required: list[str] = []
    for dataset, purpose, required in DATASETS:
        status, detail = probe(dataset, token)
        mark = {"OK": "[OK]", "DENIED": "[拒絕]", "EMPTY": "[空]", "ERROR": "[錯誤]"}[status]
        print(f"{dataset:<42} {mark:<8} {purpose} — {detail}")
        if status != "OK" and required:
            blocked_required.append(f"{dataset}({purpose})")

    print("-" * 92)
    if blocked_required:
        print(f"\n[!] {len(blocked_required)} 個 Phase 1 硬需求 dataset 取不到:")
        for name in blocked_required:
            print(f"    - {name}")
        print("\n訂閱層級可能不足。詳見 docs/FinMind_API_Inventory.md")
        return 1

    print("\n[OK] Phase 1 所需 dataset 全部可存取,可以讓 Codex 開 Step 2。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
