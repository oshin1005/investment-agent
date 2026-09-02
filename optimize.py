#!/usr/bin/env python3
"""
モメンタムフィルターの最適化
診断結果: 直前20日で+10%以上上昇した銘柄を買うと大負けする（PF 0.36）
        緩やかな上昇（-3〜+10%）が最も勝てる（PF 1.6〜2.7）
"""
import sys, os
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))
from dotenv import load_dotenv
load_dotenv(override=True)

import pandas as pd
from verify_signals import load_signals, fetch_prices, evaluate


def build():
    signals = load_signals()
    tickers = {s["ticker"] for s in signals}
    start = (datetime.strptime(signals[0]["created_at"][:10], "%Y-%m-%d") - timedelta(days=40)).strftime("%Y-%m-%d")
    end   = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    prices = fetch_prices(tickers, start, end)
    rows = []
    for s in signals:
        df = prices.get(s["ticker"])
        if df is None:
            continue
        r = evaluate(s, df, 10)
        if r is None:
            continue
        past = df[df.index <= pd.Timestamp(s["created_at"][:10])]
        if len(past) < 22:
            continue
        c = past["Close"]
        rows.append(dict(**s, **r,
                         ret_5=float((c.iloc[-1]/c.iloc[-6]-1)*100),
                         ret_20=float((c.iloc[-1]/c.iloc[-21]-1)*100)))
    return rows


def stat(b):
    if not b:
        return None
    n = len(b)
    w = len([r for r in b if r["pnl_pct"] > 0])
    gw = sum(r["pnl_pct"] for r in b if r["pnl_pct"] > 0)
    gl = abs(sum(r["pnl_pct"] for r in b if r["pnl_pct"] <= 0))
    pf = gw/gl if gl else 99.0
    return dict(n=n, wr=w/n*100, avg=sum(r["pnl_pct"] for r in b)/n,
                total=sum(r["pnl_pct"] for r in b), pf=pf)


def show(b, label):
    s = stat(b)
    if not s:
        print(f"  {label:38} 該当なし")
        return
    print(f"  {label:38} n={s['n']:3d} | 勝率 {s['wr']:5.1f}% | 平均 {s['avg']:+6.2f}% | "
          f"累計 {s['total']:+7.1f}% | PF {s['pf']:5.2f}")


def main():
    print("データ構築中...")
    rows = build()
    print(f"\n{'='*104}")
    print(f"  モメンタムフィルター最適化 | 対象 {len(rows)}件")
    print(f"{'='*104}\n")

    print("【現状（フィルターなし）】")
    show(rows, "全シグナル")
    show([r for r in rows if r["signal"] in ("STRONG_BUY","BUY")], "BUY系のみ")
    show([r for r in rows if r["signal"] == "STRONG_BUY"], "STRONG_BUYのみ（現在の発注条件）")

    print("\n【モメンタム上限フィルター: 直前20日の上昇率 < X%】")
    for th in [15, 12, 10, 8, 6]:
        show([r for r in rows if r["ret_20"] < th], f"全シグナル & 20日上昇 <{th}%")

    print("\n【モメンタム帯フィルター: 下限 〜 上限】")
    for lo, hi in [(-5,10),(-3,10),(-3,12),(0,10),(-3,8),(0,8),(-5,12)]:
        show([r for r in rows if lo <= r["ret_20"] < hi], f"全シグナル & 20日上昇 {lo:+d}〜{hi:+d}%")

    print("\n【BUY系 × モメンタム帯】")
    for lo, hi in [(-5,10),(-3,10),(-3,12),(0,10),(-3,8)]:
        show([r for r in rows if r["signal"] in ("STRONG_BUY","BUY") and lo <= r["ret_20"] < hi],
             f"BUY系 & 20日上昇 {lo:+d}〜{hi:+d}%")

    print("\n【信頼度フィルターとの組合せ（20日上昇 -3〜+10%）】")
    base = [r for r in rows if -3 <= r["ret_20"] < 10]
    for lo in [0, 60, 65, 70]:
        show([r for r in base if (r["confidence"] or 0) >= lo], f"モメンタム帯 & 信頼度 {lo}+")

    print("\n【シグナル種別 × モメンタム帯（-3〜+10%）】")
    for sig in ["STRONG_BUY", "BUY", "HOLD"]:
        show([r for r in base if r["signal"] == sig], f"モメンタム帯 & {sig}")
    show([r for r in base if r["signal"] in ("STRONG_BUY","BUY")], "モメンタム帯 & BUY系")

    print("\n【直前5日フィルターの追加効果】")
    for th in [5, 4, 3]:
        show([r for r in base if r["signal"] in ("STRONG_BUY","BUY") and r["ret_5"] < th],
             f"モメンタム帯 & BUY系 & 5日<+{th}%")

    print(f"\n{'='*104}")
    print("  推奨設定の比較")
    print(f"{'='*104}\n")
    cands = {
        "現状: STRONG_BUYのみ発注":
            [r for r in rows if r["signal"] == "STRONG_BUY"],
        "案A: BUY系 + 20日上昇-3〜+10%":
            [r for r in rows if r["signal"] in ("STRONG_BUY","BUY") and -3 <= r["ret_20"] < 10],
        "案B: 全シグナル + 20日上昇-3〜+10%":
            [r for r in rows if -3 <= r["ret_20"] < 10],
        "案C: BUY系 + 20日上昇<+10%":
            [r for r in rows if r["signal"] in ("STRONG_BUY","BUY") and r["ret_20"] < 10],
        "案D: 案A + 5日上昇<+5%":
            [r for r in rows if r["signal"] in ("STRONG_BUY","BUY")
             and -3 <= r["ret_20"] < 10 and r["ret_5"] < 5],
    }
    for label, b in cands.items():
        show(b, label)

    print(f"\n{'='*104}")
    print("  除外候補銘柄（累計マイナスが大きい）")
    print(f"{'='*104}\n")
    from collections import defaultdict
    bt = defaultdict(list)
    for r in rows:
        bt[(r["ticker"], r["name"])].append(r)
    for (t, n), rs in sorted(bt.items(), key=lambda kv: sum(x["pnl_pct"] for x in kv[1])):
        s = stat(rs)
        flag = "  ← 除外推奨" if s["total"] < -10 and s["n"] >= 5 else ""
        print(f"  {n[:12]:14}({t}) n={s['n']:2d} 勝率{s['wr']:5.1f}% 累計{s['total']:+7.1f}% PF{s['pf']:5.2f}{flag}")

    print(f"\n【案A + 負け銘柄除外】")
    losers = {t for (t, n), rs in bt.items()
              if stat(rs)["total"] < -10 and stat(rs)["n"] >= 5}
    show([r for r in rows if r["signal"] in ("STRONG_BUY","BUY")
          and -3 <= r["ret_20"] < 10 and r["ticker"] not in losers],
         f"案A & 除外{len(losers)}銘柄")
    print(f"  除外対象: {losers}")
    print()


if __name__ == "__main__":
    main()
