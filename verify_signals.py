#!/usr/bin/env python3
"""
過去シグナルの答え合わせ
DBに蓄積したシグナルを実際の株価で検証し、勝率・損益を算出する。

使い方:
  python3 verify_signals.py                 # 全シグナル検証
  python3 verify_signals.py --signal BUY    # BUYのみ
  python3 verify_signals.py --max-hold 10   # 最大保有日数
"""
import sys, os, argparse, sqlite3
from datetime import datetime, timedelta
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv(override=True)

import yfinance as yf
import pandas as pd

DB = "data/trading.db"


def load_signals():
    """DBからシグナルを取得（同日・同銘柄の重複は最後の1件のみ）"""
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    cur.execute("""
        SELECT created_at, ticker, name, signal, confidence,
               entry_price, target_price, stop_loss,
               tech_score, news_score, final_score, market_status
        FROM signals
        ORDER BY created_at
    """)
    rows = [dict(r) for r in cur.fetchall()]
    con.close()

    # 同日・同銘柄は最新のものだけ残す
    dedup = {}
    for r in rows:
        d = r["created_at"][:10]
        dedup[(d, r["ticker"])] = r
    return sorted(dedup.values(), key=lambda x: x["created_at"])


def fetch_prices(tickers, start, end):
    """必要な銘柄の株価をまとめて取得"""
    data = {}
    for i, t in enumerate(sorted(tickers), 1):
        print(f"  [{i:02d}/{len(tickers)}] {t} 株価取得中...", end=" ", flush=True)
        try:
            df = yf.download(f"{t}.T", start=start, end=end,
                             interval="1d", progress=False, auto_adjust=True)
            if df is None or df.empty:
                print("データなし")
                continue
            df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
            df.index = pd.to_datetime(df.index).tz_localize(None)
            data[t] = df
            print(f"{len(df)}日分")
        except Exception as e:
            print(f"失敗: {e}")
    return data


def evaluate(sig, df, max_hold_days=10):
    """
    1シグナルの結果を判定
    エントリー: シグナル翌営業日の始値
    判定: 日中高値がtarget到達 → 利確 / 日中安値がstop到達 → 損切
          両方同日なら保守的に損切扱い
    """
    sig_date = pd.Timestamp(sig["created_at"][:10])
    future = df[df.index > sig_date]
    if len(future) == 0:
        return None

    entry_row  = future.iloc[0]
    entry_date = future.index[0]
    entry      = float(entry_row["Open"])
    if entry <= 0:
        return None

    # 元シグナルの目標/損切り幅を、実エントリー価格に対する比率で再設定
    sig_entry = sig["entry_price"] or entry
    target_pct = (sig["target_price"] - sig_entry) / sig_entry
    stop_pct   = (sig["stop_loss"]   - sig_entry) / sig_entry
    target = entry * (1 + target_pct)
    stop   = entry * (1 + stop_pct)

    window = future.iloc[:max_hold_days]
    for i in range(len(window)):
        row  = window.iloc[i]
        high = float(row["High"])
        low  = float(row["Low"])
        # 同日に両方タッチした場合は損切り優先（保守的評価）
        if low <= stop:
            return dict(exit_reason="stop", exit_price=stop,
                        exit_date=window.index[i], entry=entry,
                        entry_date=entry_date, holding=i + 1,
                        pnl_pct=(stop - entry) / entry * 100)
        if high >= target:
            return dict(exit_reason="target", exit_price=target,
                        exit_date=window.index[i], entry=entry,
                        entry_date=entry_date, holding=i + 1,
                        pnl_pct=(target - entry) / entry * 100)

    if len(window) == 0:
        return None
    last = window.iloc[-1]
    exit_price = float(last["Close"])
    return dict(exit_reason="timeout", exit_price=exit_price,
                exit_date=window.index[-1], entry=entry,
                entry_date=entry_date, holding=len(window),
                pnl_pct=(exit_price - entry) / entry * 100)


def summarize(results, label):
    """結果サマリーを出力"""
    if not results:
        print(f"  {label}: 対象なし")
        return None
    wins   = [r for r in results if r["pnl_pct"] > 0]
    losses = [r for r in results if r["pnl_pct"] <= 0]
    gross_win  = sum(r["pnl_pct"] for r in wins)
    gross_loss = abs(sum(r["pnl_pct"] for r in losses))
    pf = gross_win / gross_loss if gross_loss > 0 else float("inf")
    avg = sum(r["pnl_pct"] for r in results) / len(results)
    reasons = defaultdict(int)
    for r in results:
        reasons[r["exit_reason"]] += 1
    pf_str = f"{pf:.2f}" if pf != float("inf") else "∞"
    print(f"  {label:14} | {len(results):3d}件 | 勝率 {len(wins)/len(results)*100:5.1f}% | "
          f"平均 {avg:+6.2f}% | 累計 {sum(r['pnl_pct'] for r in results):+7.1f}% | PF {pf_str:>5} | "
          f"利確{reasons['target']}/損切{reasons['stop']}/期限{reasons['timeout']}")
    return dict(n=len(results), win_rate=len(wins)/len(results)*100, avg=avg,
                total=sum(r["pnl_pct"] for r in results), pf=pf)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-hold", type=int, default=10, help="最大保有営業日数")
    args = ap.parse_args()

    signals = load_signals()
    print(f"\n{'='*100}")
    print(f"  シグナル検証レポート | 対象: {len(signals)}件（同日重複除去後） | 最大保有: {args.max_hold}営業日")
    print(f"{'='*100}\n")

    tickers = {s["ticker"] for s in signals}
    start = (datetime.strptime(signals[0]["created_at"][:10], "%Y-%m-%d") - timedelta(days=5)).strftime("%Y-%m-%d")
    end   = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    print(f"株価データ取得中（{len(tickers)}銘柄 / {start}〜{end}）...")
    prices = fetch_prices(tickers, start, end)

    results = []
    for s in signals:
        df = prices.get(s["ticker"])
        if df is None:
            continue
        r = evaluate(s, df, args.max_hold)
        if r is None:
            continue
        r.update(s)
        results.append(r)

    print(f"\n{'='*100}")
    print(f"  検証結果: {len(results)}件が決済済み（未確定分は除外）")
    print(f"{'='*100}\n")

    print("【シグナル種別ごと】")
    for sig_type in ["STRONG_BUY", "BUY", "HOLD"]:
        summarize([r for r in results if r["signal"] == sig_type], sig_type)

    print("\n【信頼度ごと】")
    for lo, hi, label in [(80, 101, "信頼度 80+"), (70, 80, "信頼度 70-79"),
                          (60, 70, "信頼度 60-69"), (0, 60, "信頼度 60未満")]:
        summarize([r for r in results if lo <= (r["confidence"] or 0) < hi], label)

    print("\n【相場状態ごと】")
    for st in ["NORMAL", "CAUTION"]:
        summarize([r for r in results if r["market_status"] == st], st)
    unknown = [r for r in results if not r["market_status"]]
    if unknown:
        summarize(unknown, "記録なし(旧)")

    print("\n【全体】")
    overall = summarize(results, "ALL")

    # 実際に発注される STRONG_BUY のみ
    print("\n【実運用相当（STRONG_BUYのみ自動発注）】")
    sb = summarize([r for r in results if r["signal"] == "STRONG_BUY"], "STRONG_BUY")

    # 銘柄別
    by_ticker = defaultdict(list)
    for r in results:
        by_ticker[(r["ticker"], r["name"])].append(r)
    ranked = sorted(by_ticker.items(),
                    key=lambda kv: sum(x["pnl_pct"] for x in kv[1]), reverse=True)
    print(f"\n【銘柄別 上位5】")
    for (t, n), rs in ranked[:5]:
        tot = sum(x["pnl_pct"] for x in rs)
        w = len([x for x in rs if x["pnl_pct"] > 0])
        print(f"  {n}({t}): {len(rs)}件 勝率{w/len(rs)*100:.0f}% 累計{tot:+.1f}%")
    print(f"\n【銘柄別 下位5】")
    for (t, n), rs in ranked[-5:]:
        tot = sum(x["pnl_pct"] for x in rs)
        w = len([x for x in rs if x["pnl_pct"] > 0])
        print(f"  {n}({t}): {len(rs)}件 勝率{w/len(rs)*100:.0f}% 累計{tot:+.1f}%")

    # 個別明細
    print(f"\n{'='*100}")
    print("  個別明細（新しい順・上位30件）")
    print(f"{'='*100}")
    print(f"  {'日付':<11}{'銘柄':<20}{'種別':<12}{'信頼':<5}{'結果':<7}{'損益':>8}  保有")
    for r in sorted(results, key=lambda x: x["created_at"], reverse=True)[:30]:
        mark = "✅" if r["pnl_pct"] > 0 else "❌"
        print(f"  {r['created_at'][:10]:<11}{r['name'][:9]:<20}{r['signal']:<12}"
              f"{r['confidence'] or 0:<5}{r['exit_reason']:<7}{r['pnl_pct']:>+7.2f}% {mark} {r['holding']}日")

    # 判定
    print(f"\n{'='*100}")
    print("  本番移行の判定")
    print(f"{'='*100}")
    if sb and sb["n"] >= 10:
        ok_win = sb["win_rate"] >= 50
        ok_pf  = sb["pf"] >= 1.3
        ok_avg = sb["avg"] > 0
        print(f"  STRONG_BUY {sb['n']}件で評価:")
        print(f"    勝率 50%以上 : {'✅' if ok_win else '❌'} ({sb['win_rate']:.1f}%)")
        print(f"    PF 1.3以上   : {'✅' if ok_pf else '❌'} ({sb['pf']:.2f})")
        print(f"    平均リターン+ : {'✅' if ok_avg else '❌'} ({sb['avg']:+.2f}%)")
        if ok_win and ok_pf and ok_avg:
            print(f"\n  → 判定: ✅ GO（本番移行の基準を満たしています）")
        else:
            print(f"\n  → 判定: ⚠️ NO-GO（ロジック改善を推奨）")
    else:
        print(f"  STRONG_BUYのサンプル数が不足（{sb['n'] if sb else 0}件 / 最低10件必要）")
    print()


if __name__ == "__main__":
    main()
