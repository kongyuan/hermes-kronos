#!/usr/bin/env python3
"""
no_agent watchdog — 持仓止损实时监控
每分钟拉腾讯财经现价。平时静默，距止损 ≤1% 时强告警。
T+1 买入当日自动跳过。
静默时输出为空 → no_agent 模式不推消息。
"""
import json
import urllib.request
import sys

# ── 持仓定义 ──
# buy_date 格式 "YYYY-MM-DD"，用于 T+1 过滤（买入当日不触发止损告警）
from datetime import date as _date
_TODAY = _date.today().isoformat()

POSITIONS = [
    {"code": "sh603019", "name": "中科曙光", "cost": 54.003, "stop": 85.99, "target": 106.00, "shares": 100, "buy_date": "2026-05-08"},
    {"code": "sz300274", "name": "阳光电源", "cost": 141.48, "stop": 134.00, "target": 146.00, "shares": 100, "buy_date": "2026-05-13"},
    {"code": "sh603501", "name": "豪威集团", "cost": 100.536, "stop": 97.00, "target": 110.00, "shares": 200, "buy_date": "2026-05-13"},
    {"code": "sz300373", "name": "扬杰科技", "cost": 83.17, "stop": 75.00, "target": 92.00, "shares": 100, "buy_date": "2026-05-13"},
]

TENCENT_URL = "http://qt.gtimg.cn/q="
THRESHOLD_CRITICAL = 0.01   # 1% — 距止损 ≤1% 才告警，其他时间静默

def fetch_price(code: str) -> float | None:
    try:
        url = TENCENT_URL + code
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            raw = resp.read().decode("gbk", errors="replace")
        # 腾讯格式: v_sz603019="1~中科曙光~603019~96.30~..."
        for line in raw.strip().split("\n"):
            if '="' in line:
                fields = line.split('="', 1)[1].strip('";\n').split("~")
                if len(fields) > 3:
                    return float(fields[3])
        return None
    except Exception:
        return None

def main():
    alerts = []
    codes = [p["code"] for p in POSITIONS]
    url = TENCENT_URL + ",".join(codes)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode("gbk", errors="replace")
    except Exception as e:
        print(f"⚠️ 看门狗拉取行情失败: {e}", file=sys.stderr)
        sys.exit(1)

    prices = {}
    for line in raw.strip().split("\n"):
        if '="' in line:
            fields = line.split('="', 1)[1].strip('";\n').split("~")
            if len(fields) > 3:
                prices[fields[1]] = float(fields[3])  # name → price

    for pos in POSITIONS:
        price = prices.get(pos["name"])
        if price is None:
            continue

        # T+1 过滤：买入当日不能卖出，止损告警无意义
        buy_date = pos.get("buy_date", "")
        if buy_date == _TODAY:
            continue

        stop_dist = (price - pos["stop"]) / pos["stop"]
        pnl_pct = (price - pos["cost"]) / pos["cost"] * 100

        if stop_dist <= THRESHOLD_CRITICAL:
            alerts.append(f"🚨 {pos['name']}({pos['code'][2:]}) 现价{price:.2f} 距止损{stop_dist*100:.1f}% | 止损{pos['stop']} | 建议立即减仓")

        # 止盈已触发但未卖
        if pos["target"] and price >= pos["target"]:
            alerts.append(f"🎯 {pos['name']}({pos['code'][2:]}) 现价{price:.2f} 已触发止盈{pos['target']} | 浮盈{pnl_pct:+.1f}%")

    if alerts:
        print("🔭 持仓看门狗告警")
        for a in alerts:
            print(a)
    # 否则静默 — stdout 为空，no_agent 不推送

if __name__ == "__main__":
    main()
