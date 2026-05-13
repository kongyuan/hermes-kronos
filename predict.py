#!/usr/bin/env python3
"""Kronos A 股自动预测 — GitHub Actions 版

每天 8:00 CST (0:00 UTC) 由 GitHub Actions 自动触发。
CPU 运行 Kronos-small → 生成 latest.json → 写回仓库。

零人工，全自动。
"""

import json
import os
import sys
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

# ── 配置 ──
def load_watchlist():
    """从 stopwatch.py 动态读取持仓列表"""
    watchlist_path = Path(__file__).parent / "stopwatch.py"
    if watchlist_path.exists():
        import importlib.util
        spec = importlib.util.spec_from_file_location("stopwatch", watchlist_path)
        stopwatch = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(stopwatch)
        return [(p["code"], p["name"]) for p in stopwatch.POSITIONS]
    # 兜底
    return [
        ("sh603019", "中科曙光"),
        ("sh603989", "艾华集团"),
        ("sz300124", "汇川技术"),
    ]

WATCHLIST = load_watchlist()
PRED_LEN = 5       # 预测未来 5 根 K 线
LOOKBACK = 250      # 用最近 250 天
MIN_KLINE = 120     # 最少需要 120 天数据才能预测
OUTPUT_DIR = Path(__file__).parent
OUTPUT_FILE = OUTPUT_DIR / "latest.json"

# ── K 线拉取 ──
def _safe_float(v):
    """腾讯字段可能是 str/int/float/list/dict，只取可转 float 的值"""
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v)
        except ValueError:
            return 0.0
    return 0.0

def fetch_kline(code, count=250):
    """拉腾讯财经日线"""
    url = f"http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={code},day,,,{count},qfq"
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "http://gu.qq.com/",
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"  ⚠️ 拉取失败: {e}")
        return None, None

    stock_key = code
    kline_data = data.get("data", {}).get(stock_key, {})

    if isinstance(kline_data, list):
        kline_data = kline_data[0] if kline_data else {}
    if not isinstance(kline_data, dict):
        return None, None

    klines = kline_data.get("qfqday", []) or kline_data.get("day", [])
    if not klines:
        return None, None

    timestamps, ohlcv = [], []
    for k in klines:
        timestamps.append(k[0])
        ohlcv.append([
            _safe_float(k[1]) if len(k) > 1 else 0.0,  # open
            _safe_float(k[2]) if len(k) > 2 else 0.0,  # close
            _safe_float(k[3]) if len(k) > 3 else 0.0,  # high
            _safe_float(k[4]) if len(k) > 4 else 0.0,  # low
            _safe_float(k[5]) if len(k) > 5 else 0.0,  # volume
            _safe_float(k[6]) if len(k) > 6 else 0.0,  # amount
        ])

    return timestamps, ohlcv, float(ohlcv[-1][1])  # last close

# ── 日期生成 ──
def next_trading_days(last_date_str, count):
    """从最后一个交易日往后生成 count 个交易日"""
    last_date = datetime.strptime(last_date_str, "%Y-%m-%d")
    result = []
    d = last_date
    while len(result) < count:
        d += timedelta(days=1)
        if d.weekday() < 5:
            result.append(d)
    return [x.strftime("%Y-%m-%d") for x in result]

# ── 主流程 ──
def main():
    print("=" * 60)
    print(f"📈 Kronos A 股预测 — GitHub Actions 自动版")
    print(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print(f"🖥️  CPU-only | 模型: Kronos-small (24.7M)")
    print("=" * 60)

    # 1. 导入模型
    print("\n📦 加载 Kronos ...")
    import torch
    sys.path.insert(0, str(Path(__file__).parent / "Kronos"))
    from model import Kronos, KronosTokenizer, KronosPredictor

    tokenizer = KronosTokenizer.from_pretrained("NeoQuasar/Kronos-Tokenizer-base")
    model = Kronos.from_pretrained("NeoQuasar/Kronos-small")
    predictor = KronosPredictor(model, tokenizer, device="cpu", max_context=512)
    print(f"  ✅ 加载完成 (PyTorch {torch.__version__})")

    # 2. 逐只预测
    all_results = {
        "generated_at": datetime.now().isoformat(),
        "model": "Kronos-small",
        "runtime": "GitHub Actions (CPU)",
        "pred_len": PRED_LEN,
        "predictions": {},
    }
    ok = fail = 0

    import pandas as pd

    for code, name in WATCHLIST:
        print(f"\n🔍 {code} {name} ...")
        timestamps, ohlcv, last_close = fetch_kline(code, LOOKBACK + 10)

        if ohlcv is None or len(ohlcv) < MIN_KLINE:
            print(f"  ❌ 数据不足 ({len(ohlcv) if ohlcv else 0} 条)")
            fail += 1
            continue

        print(f"  📊 {len(ohlcv)} 条日线 ({timestamps[0]} ~ {timestamps[-1]}) | 现价 {last_close}")

        # 准备输入
        lookback = min(LOOKBACK, len(ohlcv))
        x_ohlcv = ohlcv[-lookback:]
        x_ts = timestamps[-lookback:]
        x_df = pd.DataFrame(x_ohlcv, columns=["open", "close", "high", "low", "volume", "amount"])
        x_df = x_df[["open", "high", "low", "close", "volume", "amount"]]  # Kronos 期望列序
        x_timestamp = pd.Series(pd.to_datetime(x_ts))

        y_dates = next_trading_days(timestamps[-1], PRED_LEN)
        y_timestamp = pd.Series(pd.to_datetime(y_dates))

        # 预测
        try:
            pred_df = predictor.predict(
                df=x_df, x_timestamp=x_timestamp, y_timestamp=y_timestamp,
                pred_len=PRED_LEN, T=1.0, top_p=0.9, sample_count=5,
            )
        except Exception as e:
            print(f"  ❌ 预测失败: {e}")
            fail += 1
            continue

        # 提取
        forecast = []
        for _, row in pred_df.iterrows():
            forecast.append({
                "date": str(row.name.date()) if hasattr(row.name, 'date') else str(row.name),
                "open": round(float(row["open"]), 2),
                "high": round(float(row["high"]), 2),
                "low": round(float(row["low"]), 2),
                "close": round(float(row["close"]), 2),
            })

        p_high = max(f["high"] for f in forecast)
        p_low = min(f["low"] for f in forecast)
        p_close = forecast[-1]["close"]
        chg = (p_close - last_close) / last_close * 100
        direction = "🟢看涨" if chg > 0 else "🔴看跌"

        all_results["predictions"][code] = {
            "name": name,
            "last_close": round(last_close, 2),
            "latest_date": timestamps[-1],
            "kline_count": len(ohlcv),
            "forecast": forecast,
            "summary": {
                "pred_close": p_close,
                "pred_high": p_high,
                "pred_low": p_low,
                "change_pct": round(chg, 2),
                "direction": direction,
                "volatility": round((p_high - p_low) / p_close * 100, 2),
            },
        }

        print(f"  {direction} | {last_close} → {p_close} ({chg:+.2f}%) | 区间 {p_low}~{p_high}")
        ok += 1

    # 3. 保存
    with open(OUTPUT_FILE, "w") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2, default=str)

    # 同时存一份带日期的
    dated = OUTPUT_DIR / f"kronos_{datetime.now().strftime('%Y%m%d')}.json"
    with open(dated, "w") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2, default=str)

    print(f"\n{'=' * 60}")
    print(f"✅ 完成！成功 {ok}/{len(WATCHLIST)}，失败 {fail}")
    print(f"📁 {OUTPUT_FILE}")
    print("=" * 60)

    return ok > 0

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
