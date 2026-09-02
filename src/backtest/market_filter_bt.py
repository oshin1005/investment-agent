"""
バックテスト用の相場環境フィルター
※リアルタイムAPIは使わず、過去の日経225データで再現
"""
import pandas as pd
import yfinance as yf
from datetime import date


def load_nikkei_history(period: str = "2y") -> pd.DataFrame:
    df = yf.download("^N225", period=period, interval="1d",
                     progress=False, auto_adjust=True)
    df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
    df = df[["Close"]].dropna()
    df.index = pd.to_datetime(df.index).date
    return df


def is_tradeable_on(nikkei_df: pd.DataFrame, target_date: date) -> tuple[bool, str]:
    """
    指定日に取引可能かどうかをバックテスト上で判定
    Returns (tradeable, reason)
    """
    dates = [d for d in nikkei_df.index if d <= target_date]
    if len(dates) < 10:
        return True, "データ不足・通常"

    slice_df = nikkei_df.loc[dates[-10:]]
    close = slice_df["Close"]

    # 本日の騰落率
    daily = float((close.iloc[-1] - close.iloc[-2]) / close.iloc[-2] * 100)

    # 3日連続下落かつ合計-5%
    if len(close) >= 4:
        three_d = float((close.iloc[-1] - close.iloc[-4]) / close.iloc[-4] * 100)
        consecutive = (
            float(close.iloc[-1]) < float(close.iloc[-2]) and
            float(close.iloc[-2]) < float(close.iloc[-3]) and
            float(close.iloc[-3]) < float(close.iloc[-4])
        )
        if consecutive and three_d <= -5.0:
            return False, f"3日連続下落({three_d:.1f}%)"

    # 週間-7%
    if len(close) >= 6:
        weekly = float((close.iloc[-1] - close.iloc[-6]) / close.iloc[-6] * 100)
        if weekly <= -7.0:
            return False, f"週間急落({weekly:.1f}%)"

    # 1日-3%
    if daily <= -3.0:
        return False, f"本日急落({daily:.1f}%)"

    # SMA25トレンド
    if len(close) >= 8:
        sma_now  = float(close.rolling(min(len(close), 8)).mean().iloc[-1])
        sma_prev = float(close.rolling(min(len(close), 8)).mean().iloc[-3])
        if float(close.iloc[-1]) < sma_now and sma_now < sma_prev:
            return False, "日経下落トレンド"

    return True, "通常"
