import pandas as pd
import ta
from dataclasses import dataclass, field
from src import config


@dataclass
class TechnicalSummary:
    ticker: str
    name: str
    sector: str
    timestamp: str
    price: float
    # 日足指標
    rsi_14: float
    macd_signal: str
    bb_position: str
    sma_trend: str        # daily
    volume_ratio: float
    atr_14: float
    daily_change_pct: float
    month_high: float
    month_low: float
    # 週足トレンド
    weekly_trend: str     # uptrend / downtrend / sideways
    # モメンタム（高値掴み判定用）
    ret_5_pct: float = 0.0
    ret_20_pct: float = 0.0
    # テクニカルスコア（0〜100）
    tech_score: float = 0.0

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "name": self.name,
            "sector": self.sector,
            "timestamp": self.timestamp,
            "price": self.price,
            "tech_score": round(self.tech_score, 1),
            "indicators": {
                "rsi_14": round(self.rsi_14, 1),
                "macd_signal": self.macd_signal,
                "bb_position": self.bb_position,
                "sma_trend_daily": self.sma_trend,
                "weekly_trend": self.weekly_trend,
                "volume_ratio": round(self.volume_ratio, 2),
                "atr_14": round(self.atr_14, 1),
            },
            "context": {
                "daily_change_pct": round(self.daily_change_pct, 2),
                "ret_5_pct": round(self.ret_5_pct, 2),
                "ret_20_pct": round(self.ret_20_pct, 2),
                "month_high": self.month_high,
                "month_low": self.month_low,
            },
        }


def _macd_signal(df: pd.DataFrame) -> str:
    macd = ta.trend.MACD(df["Close"],
                         window_slow=config.MACD_SLOW,
                         window_fast=config.MACD_FAST,
                         window_sign=config.MACD_SIGNAL)
    hist = macd.macd_diff().dropna()
    if len(hist) < 2:
        return "unknown"
    if hist.iloc[-1] > 0 and hist.iloc[-2] <= 0:
        return "golden_cross"
    if hist.iloc[-1] < 0 and hist.iloc[-2] >= 0:
        return "dead_cross"
    if hist.iloc[-1] > hist.iloc[-2]:
        return "bullish_momentum"
    if hist.iloc[-1] < hist.iloc[-2]:
        return "bearish_momentum"
    return "neutral"


def _bb_position(df: pd.DataFrame) -> str:
    bb = ta.volatility.BollingerBands(df["Close"],
                                       window=config.BB_PERIOD,
                                       window_dev=config.BB_STD)
    price = df["Close"].iloc[-1]
    upper = bb.bollinger_hband().iloc[-1]
    lower = bb.bollinger_lband().iloc[-1]
    mid   = bb.bollinger_mavg().iloc[-1]
    if price >= upper:
        return "above_upper"
    if price <= lower:
        return "below_lower"
    if price > mid:
        return "middle_upper"
    return "middle_lower"


def _sma_trend(df: pd.DataFrame) -> str:
    s5  = ta.trend.SMAIndicator(df["Close"], window=5).sma_indicator().iloc[-1]
    s25 = ta.trend.SMAIndicator(df["Close"], window=25).sma_indicator().iloc[-1]
    s75 = ta.trend.SMAIndicator(df["Close"], window=75).sma_indicator().dropna()
    s75_val = s75.iloc[-1] if len(s75) > 0 else s25
    if s5 > s25 > s75_val:
        return "uptrend"
    if s5 < s25 < s75_val:
        return "downtrend"
    return "sideways"


def _weekly_trend(df_weekly: pd.DataFrame) -> str:
    """週足SMAでトレンド方向を判定"""
    if df_weekly is None or len(df_weekly) < 13:
        return "unknown"
    s4  = ta.trend.SMAIndicator(df_weekly["Close"], window=4).sma_indicator().iloc[-1]
    s13 = ta.trend.SMAIndicator(df_weekly["Close"], window=13).sma_indicator().iloc[-1]
    s26 = ta.trend.SMAIndicator(df_weekly["Close"], window=26).sma_indicator().dropna()
    s26_val = s26.iloc[-1] if len(s26) > 0 else s13
    if s4 > s13 > s26_val:
        return "uptrend"
    if s4 < s13 < s26_val:
        return "downtrend"
    return "sideways"


def _calc_tech_score(summary: "TechnicalSummary") -> float:
    """テクニカルスコア（0〜100）を算出"""
    score = 50.0  # ベースライン

    # 週足トレンド（±20点）
    if summary.weekly_trend == "uptrend":
        score += 20
    elif summary.weekly_trend == "downtrend":
        score -= 20

    # 日足SMAトレンド（±10点）
    if summary.sma_trend == "uptrend":
        score += 10
    elif summary.sma_trend == "downtrend":
        score -= 10

    # MACD（±10点）
    if summary.macd_signal in ("golden_cross", "bullish_momentum"):
        score += 10
    elif summary.macd_signal in ("dead_cross", "bearish_momentum"):
        score -= 10

    # RSI（±8点）
    if 45 < summary.rsi_14 < 65:  # 健全な強気圏
        score += 8
    elif summary.rsi_14 >= 75:    # 過熱
        score -= 8
    elif summary.rsi_14 <= 25:    # 売られすぎ（逆張り余地）
        score += 4

    # ボリンジャーバンド（±5点）
    if summary.bb_position == "middle_upper":
        score += 5
    elif summary.bb_position == "above_upper":
        score -= 3  # 過熱注意
    elif summary.bb_position == "below_lower":
        score -= 5

    # 出来高（±5点）
    if summary.volume_ratio >= 1.3:
        score += 5
    elif summary.volume_ratio < 0.7:
        score -= 5

    return max(0.0, min(100.0, score))


def calculate_summary(df_daily: pd.DataFrame,
                       df_weekly: pd.DataFrame,
                       ticker: str,
                       name: str,
                       sector: str) -> TechnicalSummary:
    price = float(df_daily["Close"].iloc[-1])
    prev  = float(df_daily["Close"].iloc[-2]) if len(df_daily) > 1 else price
    daily_change_pct = (price - prev) / prev * 100

    rsi_val = float(ta.momentum.RSIIndicator(
        df_daily["Close"], window=config.RSI_PERIOD).rsi().iloc[-1])
    atr_val = float(ta.volatility.AverageTrueRange(
        df_daily["High"], df_daily["Low"], df_daily["Close"],
        window=config.ATR_PERIOD).average_true_range().iloc[-1])

    vol_avg   = df_daily["Volume"].rolling(20).mean().iloc[-1]
    vol_ratio = float(df_daily["Volume"].iloc[-1] / vol_avg) if vol_avg > 0 else 1.0

    month_slice = df_daily.tail(21)
    month_high  = float(month_slice["High"].max())
    month_low   = float(month_slice["Low"].min())

    close = df_daily["Close"]
    ret_5  = float((price / close.iloc[-6]  - 1) * 100) if len(close) > 6  else 0.0
    ret_20 = float((price / close.iloc[-21] - 1) * 100) if len(close) > 21 else 0.0

    summary = TechnicalSummary(
        ticker=ticker,
        name=name,
        sector=sector,
        timestamp=str(df_daily.index[-1].date()),
        price=price,
        rsi_14=rsi_val,
        macd_signal=_macd_signal(df_daily),
        bb_position=_bb_position(df_daily),
        sma_trend=_sma_trend(df_daily),
        volume_ratio=vol_ratio,
        atr_14=atr_val,
        daily_change_pct=daily_change_pct,
        month_high=month_high,
        month_low=month_low,
        weekly_trend=_weekly_trend(df_weekly),
        ret_5_pct=ret_5,
        ret_20_pct=ret_20,
    )
    summary.tech_score = _calc_tech_score(summary)
    return summary


def screen_by_technical(summaries: list[TechnicalSummary],
                         top_n: int = 10) -> list[TechnicalSummary]:
    """
    テクニカルスコアで上位N銘柄を選定
    ・週足downtrend は除外
    ・モメンタムフィルター（高値掴み・下落トレンドを除外）
    ・セクター分散（同一セクター最大MAX_PER_SECTOR銘柄）
    """
    from src.market_data.yahoo_fetcher import MAX_PER_SECTOR

    # 週足下降トレンドは除外
    candidates = [s for s in summaries if s.weekly_trend != "downtrend"]

    # モメンタムフィルター: 直前20日の上昇率が想定レンジ内のものだけ残す
    if config.MOMENTUM_FILTER_ENABLED:
        before = len(candidates)
        candidates = [
            s for s in candidates
            if config.MOMENTUM_MIN_20D <= s.ret_20_pct < config.MOMENTUM_MAX_20D
        ]
        excluded = before - len(candidates)
        if excluded:
            print(f"     モメンタムフィルター: {excluded}銘柄を除外 "
                  f"(20日上昇率 {config.MOMENTUM_MIN_20D:+.0f}〜{config.MOMENTUM_MAX_20D:+.0f}% の範囲外)")

    # テクニカルスコア降順
    candidates.sort(key=lambda s: s.tech_score, reverse=True)

    # セクター分散フィルタ
    sector_count: dict[str, int] = {}
    filtered = []
    for s in candidates:
        count = sector_count.get(s.sector, 0)
        if count < MAX_PER_SECTOR:
            filtered.append(s)
            sector_count[s.sector] = count + 1
        if len(filtered) >= top_n:
            break

    return filtered
