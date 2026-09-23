#!/usr/bin/env python3
"""
集中投資する1〜2銘柄を選ぶための検証（ウォークフォワード方式）

これまでの失敗は「過去データを見て条件を決め、同じ過去データで良く見えた」こと。
それを避けるため、3年分を前半（1.5年）と後半（1.5年）に分け、
  ・前半で成績の良かった銘柄×戦略を選ぶ
  ・その組み合わせが、選定に使っていない後半でも勝てたかを見る
両方の期間で勝てたものだけを候補にする。

戦略（どちらもClaude不使用の単純ルール。ニュース判断は過去検証できないため）
  A 順張り   : 上昇トレンド中に高値を更新したら買う
  B 押し目買い: 上昇トレンド中に一時的に売られたら買う
決済は共通: ATR×2 で利確 / ATR×1.5 で損切 / 最大10営業日
"""
import sys, os, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
import numpy as np
import yfinance as yf

# 元金30万円で100株買える（株価1,200円以下）かつ売買が十分多い銘柄
CANDIDATES = [
    ("9432", "NTT"), ("9434", "ソフトバンク"), ("9501", "東京電力HD"),
    ("5401", "日本製鉄"), ("4005", "住友化学"), ("3861", "王子HD"),
    ("5202", "日本板硝子"), ("6471", "日本精工"), ("6472", "NTN"),
    ("7211", "三菱自動車"), ("4689", "LINEヤフー"), ("4902", "コニカミノルタ"),
    ("3092", "ZOZO"), ("7201", "日産自動車"), ("6753", "シャープ"),
    ("4755", "楽天G"), ("9008", "京王電鉄"),
]
MAX_HOLD, TGT, STP = 10, 2.0, 1.5
COST = 0.10   # 往復のスプレッド等を%で差し引く（CFDの手数料は無料だがスプレッドがある）


def indicators(df):
    c, h, l = df["Close"], df["High"], df["Low"]
    df["sma25"] = c.rolling(25).mean()
    df["sma75"] = c.rolling(75).mean()
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    df["atr"] = tr.rolling(14).mean()
    d = c.diff()
    up = d.clip(lower=0).rolling(3).mean()
    dn = (-d.clip(upper=0)).rolling(3).mean()
    df["rsi3"] = 100 - 100 / (1 + up / dn.replace(0, np.nan))
    df["hh20"] = h.rolling(20).max().shift(1)
    df["uptrend"] = (c > df["sma75"]) & (df["sma25"] > df["sma75"])
    return df


def entry_signal(row, kind):
    if not row["uptrend"] or pd.isna(row["atr"]):
        return False
    if kind == "A":   # 順張り: 20日高値を上抜け
        return row["Close"] > row["hh20"]
    if kind == "B":   # 押し目: 上昇トレンド中に短期RSIが売られすぎ
        return row["rsi3"] < 20
    return False


def backtest(df, kind):
    trades, i, n = [], 80, len(df)
    while i < n - 1:
        row = df.iloc[i]
        if not entry_signal(row, kind):
            i += 1
            continue
        entry = float(df.iloc[i + 1]["Open"])         # 翌日寄付きで買う
        atr = float(row["atr"])
        tgt, stp = entry + atr * TGT, entry - atr * STP
        exit_px, j = None, i + 1
        for j in range(i + 1, min(i + 1 + MAX_HOLD, n)):
            b = df.iloc[j]
            if b["Low"] <= stp:                           # 同日両方なら損切り優先
                exit_px = stp; break
            if b["High"] >= tgt:
                exit_px = tgt; break
        if exit_px is None:
            exit_px = float(df.iloc[j]["Close"])
        trades.append((exit_px / entry - 1) * 100 - COST)
        i = j + 1                                         # 保有中は次を買わない
    return trades


def stat(t):
    if not t:
        return dict(n=0, wr=0, avg=0, tot=0, pf=0)
    w = [x for x in t if x > 0]
    gl = abs(sum(x for x in t if x <= 0))
    return dict(n=len(t), wr=len(w) / len(t) * 100, avg=np.mean(t),
                tot=sum(t), pf=(sum(w) / gl) if gl else 9.99)


def main():
    rows = []
    print("3年分の株価を取得中...")
    for code, name in CANDIDATES:
        df = yf.download(f"{code}.T", period="3y", interval="1d",
                         progress=False, auto_adjust=True)
        if df is None or len(df) < 500:
            continue
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
        df = indicators(df.dropna(subset=["Close"]).copy())
        half = len(df) // 2
        first, second = df.iloc[:half].copy(), df.iloc[half - 80:].copy()  # 後半は指標計算用に80日重ねる
        for kind in ("A", "B"):
            s1, s2 = stat(backtest(first, kind)), stat(backtest(second, kind))
            rows.append(dict(code=code, name=name, kind=kind, s1=s1, s2=s2))
        period = (df.index[0].date(), df.index[half].date(), df.index[-1].date())

    print(f"\n前半 {period[0]}〜{period[1]} ／ 後半 {period[1]}〜{period[2]}")
    print(f"戦略 A=順張り(高値更新) B=押し目買い(短期売られすぎ)  ※往復コスト{COST}%控除済み\n")
    print(f"{'銘柄':<14}{'戦略':<4}│{'前半 件数':>8}{'勝率':>6}{'PF':>6}{'累計':>8} │{'後半 件数':>8}{'勝率':>6}{'PF':>6}{'累計':>8} │ 判定")
    print("─" * 100)

    def ok(s):
        return s["n"] >= 8 and s["pf"] >= 1.2 and s["tot"] > 0

    rows.sort(key=lambda r: (ok(r["s1"]) and ok(r["s2"]), r["s2"]["pf"]), reverse=True)
    for r in rows:
        a, b = r["s1"], r["s2"]
        mark = "◎ 両期間で勝ち" if ok(a) and ok(b) else ("△ 前半だけ" if ok(a) else ("△ 後半だけ" if ok(b) else ""))
        print(f"{r['name'][:7]:<9}{r['code']:<6}{r['kind']:<4}│"
              f"{a['n']:>7}件{a['wr']:>5.0f}%{a['pf']:>6.2f}{a['tot']:>+7.1f}% │"
              f"{b['n']:>7}件{b['wr']:>5.0f}%{b['pf']:>6.2f}{b['tot']:>+7.1f}% │ {mark}")

    good = [r for r in rows if ok(r["s1"]) and ok(r["s2"])]
    print("\n" + "=" * 100)
    print(f"  両期間で勝てた組み合わせ: {len(good)}件")
    for r in good:
        print(f"   ・{r['name']}({r['code']}) 戦略{r['kind']}  "
              f"後半(検証期間) {r['s2']['n']}件 勝率{r['s2']['wr']:.0f}% PF{r['s2']['pf']:.2f} 累計{r['s2']['tot']:+.1f}%")
    print("=" * 100)


if __name__ == "__main__":
    main()
