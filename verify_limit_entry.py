#!/usr/bin/env python3
"""
買い方の比較：翌朝の寄付き成行（従来） vs シグナル日の終値で指値

過去に合わせすぎるのを避けるため、次の3つで確かめる。
  1. 採用中の2銘柄で、3年を前半・後半に分けても改善するか
  2. 採用していない候補15銘柄でも改善するか（2銘柄だけの偶然でないか）
  3. 実運用の21件に当てはめるとどうなったか
"""
import sys, os, sqlite3, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import pandas as pd
import yfinance as yf

from src.strategy import pullback as pb

OTHERS = [("9432", "NTT"), ("9434", "ソフトバンク"), ("9501", "東京電力HD"),
          ("4005", "住友化学"), ("3861", "王子HD"), ("5202", "日本板硝子"),
          ("6471", "日本精工"), ("6472", "NTN"), ("7211", "三菱自動車"),
          ("4689", "LINEヤフー"), ("3092", "ZOZO"), ("7201", "日産自動車"),
          ("6753", "シャープ"), ("4755", "楽天G"), ("9008", "京王電鉄")]


def load(code, period="3y"):
    df = yf.download(f"{code}.T", period=period, interval="1d", progress=False, auto_adjust=True)
    df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
    return df.dropna(subset=["Open", "High", "Low", "Close"])


def st(t):
    p = [x["pnl_pct"] for x in t]
    if not p:
        return dict(n=0, wr=0, pf=0, tot=0, avg=0)
    w = [x for x in p if x > 0]
    l = abs(sum(x for x in p if x <= 0))
    return dict(n=len(p), wr=len(w) / len(p) * 100, pf=(sum(w) / l) if l else 9.99,
                tot=sum(p), avg=np.mean(p))


def fmt(s):
    return f"{s['n']:>3}件 勝率{s['wr']:>3.0f}% PF{s['pf']:>5.2f} 平均{s['avg']:>+5.2f}% 累計{s['tot']:>+6.1f}%"


def main():
    print("=" * 96)
    print("  1. 採用中の2銘柄（3年・前半/後半）")
    print("=" * 96)
    for code, name, _ in pb.FOCUS_TICKERS:
        df = load(code)
        cut = df.index[len(df) // 2]
        print(f"\n{name}({code})")
        for mode, label in (("open", "寄付き成行（従来）"), ("limit", "前日終値で指値")):
            t = pb.backtest(df, entry_mode=mode)
            print(f"  {label:<14} 全期間 {fmt(st(t))}")
            print(f"  {'':<14} 前半   {fmt(st([x for x in t if x['entry_date'] < cut]))}")
            print(f"  {'':<14} 後半   {fmt(st([x for x in t if x['entry_date'] >= cut]))}")

    print("\n" + "=" * 96)
    print("  2. 採用していない15銘柄（同じルールを当てはめた場合）")
    print("=" * 96)
    better = worse = 0
    agg = {"open": [], "limit": []}
    for code, name in OTHERS:
        df = load(code)
        if len(df) < 300:
            continue
        a, b = pb.backtest(df, "open"), pb.backtest(df, "limit")
        agg["open"] += a
        agg["limit"] += b
        sa, sb = st(a), st(b)
        mark = "↑改善" if sb["avg"] > sa["avg"] else "↓悪化"
        better += sb["avg"] > sa["avg"]
        worse += sb["avg"] <= sa["avg"]
        print(f"  {name:<10} 成行 平均{sa['avg']:>+5.2f}%({sa['n']:>2}件) → 指値 平均{sb['avg']:>+5.2f}%({sb['n']:>2}件)  {mark}")
    print(f"\n  1回あたりの平均損益が改善 {better}銘柄 / 悪化 {worse}銘柄")
    print(f"  15銘柄合計  成行: {fmt(st(agg['open']))}")
    print(f"              指値: {fmt(st(agg['limit']))}")

    print("\n" + "=" * 96)
    print("  3. 実運用21件に当てはめた場合")
    print("=" * 96)
    con = sqlite3.connect("data/trading.db")
    con.row_factory = sqlite3.Row
    T = [dict(r) for r in con.execute(
        "SELECT * FROM trades WHERE status='CLOSED' AND saxo_order_id='PAPER' ORDER BY entry_date")]
    cache, rows = {}, []
    for r in T:
        df = cache.setdefault(r["ticker"], load(r["ticker"], "1y"))
        d = pd.Timestamp(str(r["entry_date"])[:10])
        i = df.index.searchsorted(d)
        if i <= 0 or i >= len(df):
            continue
        sig_close, day = float(df["Close"].iloc[i - 1]), df.iloc[i]
        tp = r["target_price"] / r["entry_price"] - 1     # 元の取引の利確・損切り幅（%）をそのまま使う
        sp = r["stop_loss"] / r["entry_price"] - 1
        if float(day["Open"]) <= sig_close:
            entry, intraday = float(day["Open"]), False
        elif float(day["Low"]) <= sig_close:
            entry, intraday = sig_close, True
        else:
            rows.append((r, None, "買えず"))
            continue
        tgt, stp = entry * (1 + tp), entry * (1 + sp)
        res, j = None, i
        for j in range(i, min(i + pb.MAX_HOLD, len(df))):
            b = df.iloc[j]
            if b["Low"] <= stp:
                res = (stp / entry - 1) * 100
                break
            if b["High"] >= tgt and not (intraday and j == i):
                res = (tgt / entry - 1) * 100
                break
        if res is None:
            res = (float(df["Close"].iloc[j]) / entry - 1) * 100
        rows.append((r, res, "約定"))

    for r, res, s in rows:
        new = f"{res:+6.2f}%" if res is not None else "  見送り"
        print(f"  {str(r['entry_date'])[:10]} {r['name'][:9]:<10} 実際 {r['pnl_pct']:+6.2f}% → 指値なら {new}")
    filled = [x for _, x, _ in rows if x is not None]
    skipped = [r for r, x, _ in rows if x is None]
    print(f"\n  実際:   {len(rows)}件 {sum(r['pnl_pct'] > 0 for r, _, _ in rows)}勝 損益率計 {sum(r['pnl_pct'] for r, _, _ in rows):+.1f}%")
    print(f"  指値なら: {len(filled)}件約定（{len(skipped)}件は買えず） "
          f"{sum(x > 0 for x in filled)}勝 損益率計 {sum(filled):+.1f}%")
    print(f"  買えなかった{len(skipped)}件の実際の結果: 損益率計 {sum(r['pnl_pct'] for r in skipped):+.1f}%"
          f"（{sum(r['pnl_pct'] > 0 for r in skipped)}勝{sum(r['pnl_pct'] <= 0 for r in skipped)}敗）")


if __name__ == "__main__":
    main()
