"""
バックテストエンジン
・2年分の日足データでテクニカルスコアをルールベースでシグナル生成
・エントリー/エグジットをシミュレーション
・パフォーマンス指標を計算
"""
import pandas as pd
import numpy as np
import ta
from dataclasses import dataclass, field
from datetime import date
from typing import Optional
from src import config


@dataclass
class Trade:
    ticker: str
    name: str
    sector: str
    entry_date: date
    entry_price: float
    target_price: float
    stop_loss: float
    exit_date: Optional[date] = None
    exit_price: Optional[float] = None
    exit_reason: str = ""   # target / stop / timeout
    pnl_pct: float = 0.0
    holding_days: int = 0


@dataclass
class BacktestResult:
    ticker: str
    name: str
    sector: str
    trades: list[Trade] = field(default_factory=list)

    @property
    def closed_trades(self) -> list[Trade]:
        return [t for t in self.trades if t.exit_date is not None]

    @property
    def win_trades(self) -> list[Trade]:
        return [t for t in self.closed_trades if t.pnl_pct > 0]

    @property
    def lose_trades(self) -> list[Trade]:
        return [t for t in self.closed_trades if t.pnl_pct <= 0]


def _calc_tech_score(df_slice: pd.DataFrame) -> float:
    """ある時点のテクニカルスコアを計算（バックテスト用・高速版）"""
    if len(df_slice) < 30:
        return 50.0

    score = 50.0
    close = df_slice["Close"]

    # SMAトレンド（±20点）
    sma5  = close.rolling(5).mean().iloc[-1]
    sma25 = close.rolling(25).mean().iloc[-1]
    if len(df_slice) >= 75:
        sma75 = close.rolling(75).mean().iloc[-1]
    else:
        sma75 = sma25

    if sma5 > sma25 > sma75:
        score += 20
    elif sma5 < sma25 < sma75:
        score -= 20

    # MACD（±10点）
    try:
        macd = ta.trend.MACD(close, window_slow=26, window_fast=12, window_sign=9)
        hist = macd.macd_diff().dropna()
        if len(hist) >= 2:
            if hist.iloc[-1] > 0 and hist.iloc[-2] <= 0:
                score += 10  # golden cross
            elif hist.iloc[-1] < 0 and hist.iloc[-2] >= 0:
                score -= 10  # dead cross
            elif hist.iloc[-1] > hist.iloc[-2] and hist.iloc[-1] > 0:
                score += 10  # bullish momentum
            elif hist.iloc[-1] < hist.iloc[-2] and hist.iloc[-1] < 0:
                score -= 10
    except Exception:
        pass

    # RSI（±8点）
    try:
        rsi = ta.momentum.RSIIndicator(close, window=14).rsi().iloc[-1]
        if 45 < rsi < 65:
            score += 8
        elif rsi >= 75:
            score -= 8
        elif rsi <= 25:
            score += 4
    except Exception:
        pass

    # ボリンジャーバンド（±5点）
    try:
        bb = ta.volatility.BollingerBands(close, window=20, window_dev=2)
        price = close.iloc[-1]
        if price > bb.bollinger_mavg().iloc[-1]:
            score += 5
        elif price < bb.bollinger_lband().iloc[-1]:
            score -= 5
    except Exception:
        pass

    # 出来高（±5点）
    try:
        vol_avg = df_slice["Volume"].rolling(20).mean().iloc[-1]
        vol_ratio = df_slice["Volume"].iloc[-1] / vol_avg if vol_avg > 0 else 1.0
        if vol_ratio >= 1.3:
            score += 5
        elif vol_ratio < 0.7:
            score -= 5
    except Exception:
        pass

    return max(0.0, min(100.0, score))


def _calc_atr(df_slice: pd.DataFrame, window: int = 14) -> float:
    try:
        atr = ta.volatility.AverageTrueRange(
            df_slice["High"], df_slice["Low"], df_slice["Close"],
            window=window
        ).average_true_range().dropna()
        return float(atr.iloc[-1]) if len(atr) > 0 else 0.0
    except Exception:
        return 0.0


def run_backtest_for_ticker(
    ticker: str,
    name: str,
    sector: str,
    df: pd.DataFrame,
    buy_threshold: float = 70.0,
    sell_threshold: float = 35.0,
    atr_target_mult: float = 3.0,
    atr_stop_mult: float = 1.5,
    max_hold_days: int = 10,
    position_size_pct: float = 0.10,
    nikkei_df=None,             # 相場フィルター用
    momentum_filter: bool = True,  # 実運用と同じモメンタムフィルターを適用
) -> BacktestResult:
    """1銘柄のバックテストを実行"""
    result = BacktestResult(ticker=ticker, name=name, sector=sector)
    df = df.copy().reset_index()
    df["Date"] = pd.to_datetime(df["Date"] if "Date" in df.columns else df.iloc[:, 0]).dt.date

    in_position = False
    current_trade: Optional[Trade] = None

    for i in range(30, len(df)):
        today = df.iloc[i]
        df_slice = df.iloc[:i + 1].copy()
        df_slice = df_slice.rename(columns={"Date": "date"}) if "Date" in df_slice.columns else df_slice

        close_price = float(today["Close"])
        today_date  = today["Date"] if "Date" in today.index else today.iloc[0]
        if not isinstance(today_date, date):
            today_date = pd.Timestamp(today_date).date()

        # ポジション保有中 → エグジット判定
        if in_position and current_trade:
            holding = (today_date - current_trade.entry_date).days
            exit_reason = ""

            if close_price >= current_trade.target_price:
                exit_reason = "target"
            elif close_price <= current_trade.stop_loss:
                exit_reason = "stop"
            elif holding >= max_hold_days:
                exit_reason = "timeout"

            if exit_reason:
                current_trade.exit_date  = today_date
                current_trade.exit_price = close_price
                current_trade.exit_reason = exit_reason
                current_trade.pnl_pct = (close_price - current_trade.entry_price) / current_trade.entry_price * 100
                current_trade.holding_days = holding
                result.trades.append(current_trade)
                in_position = False
                current_trade = None

        # ポジションなし → エントリー判定
        if not in_position:
            # 相場環境フィルター
            if nikkei_df is not None:
                from src.backtest.market_filter_bt import is_tradeable_on
                tradeable, _ = is_tradeable_on(nikkei_df, today_date)
                if not tradeable:
                    continue

            # モメンタムフィルター（実運用と同条件）
            # 直前20日で上がりすぎた銘柄＝高値掴み、下げ続けている銘柄＝落ちるナイフ
            if momentum_filter and len(df_slice) >= 21:
                c = df_slice["Close"]
                ret_20 = (c.iloc[-1] / c.iloc[-21] - 1) * 100
                if not (config.MOMENTUM_MIN_20D <= ret_20 < config.MOMENTUM_MAX_20D):
                    continue

            score = _calc_tech_score(df_slice)
            atr   = _calc_atr(df_slice)
            if atr <= 0:
                continue

            if score >= buy_threshold:
                target_price = close_price + atr * atr_target_mult
                stop_loss    = close_price - atr * atr_stop_mult
                current_trade = Trade(
                    ticker=ticker,
                    name=name,
                    sector=sector,
                    entry_date=today_date,
                    entry_price=close_price,
                    target_price=target_price,
                    stop_loss=stop_loss,
                )
                in_position = True

    return result
