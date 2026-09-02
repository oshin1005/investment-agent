#!/usr/bin/env python3
"""
シグナル不振の原因診断
仮説: テクニカルスコアが高い＝既に上昇済み＝高値掴みになっている
"""
import sys, os, sqlite3
from datetime import datetime, timedelta
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))
from dotenv import load_dotenv
load_dotenv(override=True)

import yfinance as yf
import pandas as pd

from verify_signals import load_signals, fetch_prices, evaluate


def main():
    signals = load_signals()
    tickers = {s["ticker"] for s in signals}
    start = (datetime.strptime(signals[0]["created_at"][:10], "%Y-%m-%d") - timedelta(days=40)).strftime("%Y-%m-%d")
    end   = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    print(f"株価取得中（{len(tickers)}銘柄）...")
    prices = fetch_prices(tickers, start, end)

    rows = []
    for s in signals:
        df = prices.get(s["ticker"])
        if df is None:
            continue
        r = evaluate(s, df, 10)
        if r is None:
            continue
        sig_date = pd.Timestamp(s["created_at"][:10])
        past = df[df.index <= sig_date]
        if len(past) < 22:
            continue
        close = past["Close"]
        # シグナル前の値動き
        ret_5  = (close.iloc[-1] / close.iloc[-6]  - 1) * 100 if len(close) > 6  else None
        ret_20 = (close.iloc[-1] / close.iloc[-21] - 1) * 100 if len(close) > 21 else None
        # 直近20日の高値からの位置（100% = 高値圏）
        hi20 = past["High"].iloc[-20:].max()
        lo20 = past["Low"].iloc[-20:].min()
        pos = (close.iloc[-1] - lo20) / (hi20 - lo20) * 100 if hi20 > lo20 else 50
        rows.append(dict(**s, **r, ret_5=float(ret_5), ret_20=float(ret_20), pos20=float(pos)))

    print(f"\n{'='*92}")
    print(f"  原因診断: {len(rows)}件")
    print(f"{'='*92}\n")

    def show(bucket, label):
        if not bucket:
            print(f"  {label:24} 該当なし")
            return
        n = len(bucket)
        w = len([r for r in bucket if r["pnl_pct"] > 0])
        avg = sum(r["pnl_pct"] for r in bucket) / n
        gw = sum(r["pnl_pct"] for r in bucket if r["pnl_pct"] > 0)
        gl = abs(sum(r["pnl_pct"] for r in bucket if r["pnl_pct"] <= 0))
        pf = gw / gl if gl else float("inf")
        pfs = f"{pf:.2f}" if pf != float("inf") else "∞"
        print(f"  {label:24} n={n:3d} | 勝率 {w/n*100:5.1f}% | 平均 {avg:+6.2f}% | PF {pfs:>5}")

    print("【仮説1】シグナル前5日の上昇率 → その後のリターン")
    show([r for r in rows if r["ret_5"] >= 5],            "直前5日 +5%以上（過熱）")
    show([r for r in rows if 2 <= r["ret_5"] < 5],        "直前5日 +2〜5%")
    show([r for r in rows if 0 <= r["ret_5"] < 2],        "直前5日 0〜+2%")
    show([r for r in rows if -3 <= r["ret_5"] < 0],       "直前5日 -3〜0%（押し目）")
    show([r for r in rows if r["ret_5"] < -3],            "直前5日 -3%未満（急落）")

    print("\n【仮説2】20日レンジ内の位置（100=高値圏 / 0=安値圏）")
    show([r for r in rows if r["pos20"] >= 90],           "高値圏 90-100%")
    show([r for r in rows if 70 <= r["pos20"] < 90],      "やや高値 70-90%")
    show([r for r in rows if 40 <= r["pos20"] < 70],      "中位 40-70%")
    show([r for r in rows if r["pos20"] < 40],            "安値圏 0-40%")

    print("\n【仮説3】シグナル前20日の上昇率")
    show([r for r in rows if r["ret_20"] >= 10],          "直前20日 +10%以上")
    show([r for r in rows if 3 <= r["ret_20"] < 10],      "直前20日 +3〜10%")
    show([r for r in rows if -3 <= r["ret_20"] < 3],      "直前20日 -3〜+3%")
    show([r for r in rows if r["ret_20"] < -3],           "直前20日 -3%未満")

    print("\n【参考】シグナル種別と 直前の値動きの関係")
    for sig in ["STRONG_BUY", "BUY", "HOLD"]:
        b = [r for r in rows if r["signal"] == sig]
        if not b:
            continue
        print(f"  {sig:12} 直前5日 平均{sum(r['ret_5'] for r in b)/len(b):+5.2f}% | "
              f"直前20日 平均{sum(r['ret_20'] for r in b)/len(b):+6.2f}% | "
              f"20日レンジ位置 平均{sum(r['pos20'] for r in b)/len(b):5.1f}%")

    print(f"\n{'='*92}")
    print("  改善シミュレーション: 高値圏フィルターを入れた場合")
    print(f"{'='*92}\n")
    for th in [95, 90, 85, 80]:
        filt = [r for r in rows if r["pos20"] < th and r["signal"] in ("STRONG_BUY", "BUY")]
        show(filt, f"BUY系 かつ レンジ位置<{th}%")
    print()
    for th in [8, 5, 3]:
        filt = [r for r in rows if r["ret_5"] < th and r["signal"] in ("STRONG_BUY", "BUY")]
        show(filt, f"BUY系 かつ 直前5日<+{th}%")
    print()
    show([r for r in rows if r["signal"] in ("STRONG_BUY", "BUY")], "BUY系 フィルターなし（現状）")
    combo = [r for r in rows if r["signal"] in ("STRONG_BUY", "BUY")
             and r["pos20"] < 90 and r["ret_5"] < 5]
    show(combo, "BUY系 + 両フィルター適用")
    print()


if __name__ == "__main__":
    main()
