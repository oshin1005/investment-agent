"""
押し目買い戦略（集中2銘柄）

ルール
  買い: 上昇トレンド中（終値 > 75日線 かつ 25日線 > 75日線）に、
        3日RSIが20未満まで売られた日の翌営業日寄付きで買う
  売り: ATR×2 上で利確 / ATR×1.5 下で損切 / 最大10営業日で手仕舞い

銘柄とルールは select_focus.py のウォークフォワード検証で決めた。
3年分を前後半に分け、どちらの期間でも PF1.2 以上だった組み合わせで、
かつ条件を前後にずらしても成績が崩れないものだけを採用している。

毎朝の判定（signal_today）とバックテスト（backtest）は同じ関数で指標を計算するので、
検証と実運用でロジックがずれない。
"""
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

# 集中投資する銘柄（コード, 名前, セクター）
FOCUS_TICKERS = [
    ("4902", "コニカミノルタ", "tech"),
    ("5401", "日本製鉄",       "material"),
]

RSI_ENTRY  = 20     # 3日RSIがこれ未満で「売られすぎ」
TARGET_ATR = 2.0    # 利確 = 買値 + ATR×2
STOP_ATR   = 1.5    # 損切 = 買値 − ATR×1.5
MAX_HOLD   = 10     # 最大保有営業日数
COST_PCT   = 0.10   # 往復コスト（スプレッド）の見込み。バックテストでのみ控除


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    c, h, l = df["Close"], df["High"], df["Low"]
    df["sma25"] = c.rolling(25).mean()
    df["sma75"] = c.rolling(75).mean()
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    df["atr"] = tr.rolling(14).mean()
    d = c.diff()
    up = d.clip(lower=0).rolling(3).mean()
    dn = (-d.clip(upper=0)).rolling(3).mean()
    df["rsi3"] = 100 - 100 / (1 + up / dn.replace(0, np.nan))
    df["uptrend"] = (c > df["sma75"]) & (df["sma25"] > df["sma75"])
    return df


def is_entry(row) -> bool:
    return bool(row["uptrend"]) and pd.notna(row["atr"]) and pd.notna(row["rsi3"]) \
        and row["rsi3"] < RSI_ENTRY


@dataclass
class DailyCheck:
    ticker: str
    name: str
    sector: str
    date: str
    close: float
    rsi3: float
    uptrend: bool
    atr: float
    entry: bool
    target: float
    stop: float
    reason: str


def signal_today(ticker: str, name: str, sector: str, df: pd.DataFrame) -> Optional[DailyCheck]:
    """直近の確定足で、翌営業日に買うべきかを判定する"""
    if df is None or len(df) < 80:
        return None
    df = add_indicators(df)
    row = df.iloc[-1]
    close, atr = float(row["Close"]), float(row["atr"])
    rsi = float(row["rsi3"]) if pd.notna(row["rsi3"]) else 50.0
    up = bool(row["uptrend"])
    entry = is_entry(row)

    if entry:
        reason = (f"上昇トレンド中（終値が75日線を上回り、25日線>75日線）に"
                  f"3日RSIが{rsi:.0f}まで下がった押し目。翌営業日の寄付きで買い。")
    elif not up:
        reason = f"上昇トレンドではないため見送り（終値{close:,.0f} / 75日線{row['sma75']:,.0f}）。"
    else:
        reason = f"上昇トレンド中だが押し目ではない（3日RSI {rsi:.0f}、基準は{RSI_ENTRY}未満）。"

    return DailyCheck(
        ticker=ticker, name=name, sector=sector,
        date=str(df.index[-1].date()), close=close, rsi3=rsi, uptrend=up, atr=atr,
        entry=entry,
        target=close + atr * TARGET_ATR, stop=close - atr * STOP_ATR,
        reason=reason,
    )


def backtest(df: pd.DataFrame, entry_mode: str = "open") -> list:
    """
    押し目買いの過去成績。返り値は取引ごとの dict のリスト

    entry_mode
      "open"  : シグナル翌営業日の寄付きで成行買い（従来）
      "limit" : シグナル日の終値で指値。翌営業日に安値がそこまで来たら約定、来なければ見送り。
                寄付きが指値以下なら寄付きで約定する。
    """
    df = add_indicators(df)
    trades, i, n = [], 80, len(df)
    while i < n - 1:
        row = df.iloc[i]
        if not is_entry(row):
            i += 1
            continue
        nxt = df.iloc[i + 1]
        intraday_fill = False
        if entry_mode == "limit":
            limit = float(row["Close"])
            if float(nxt["Open"]) <= limit:
                entry = float(nxt["Open"])
            elif float(nxt["Low"]) <= limit:
                entry, intraday_fill = limit, True
            else:
                i += 1               # 一度も指値まで下がらなかった → 見送り
                continue
        else:
            entry = float(nxt["Open"])
        atr = float(row["atr"])
        tgt, stp = entry + atr * TARGET_ATR, entry - atr * STOP_ATR
        exit_px, reason, j = None, "timeout", i + 1
        for j in range(i + 1, min(i + 1 + MAX_HOLD, n)):
            b = df.iloc[j]
            if b["Low"] <= stp:          # 同日に両方触れたら損切り優先（保守的）
                exit_px, reason = stp, "stop"
                break
            # 場中に指値で約定した日は、高値が約定の前だった可能性があるので利確は数えない（保守的）
            if b["High"] >= tgt and not (intraday_fill and j == i + 1):
                exit_px, reason = tgt, "target"
                break
        if exit_px is None:
            exit_px = float(df.iloc[j]["Close"])
        trades.append(dict(
            entry_date=df.index[i + 1], exit_date=df.index[j],
            entry=entry, exit=exit_px, reason=reason,
            pnl_pct=(exit_px / entry - 1) * 100 - COST_PCT,
        ))
        i = j + 1
    return trades
