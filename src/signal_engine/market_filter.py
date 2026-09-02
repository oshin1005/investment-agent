"""
相場環境フィルター
・日経225トレンド確認
・急落検知（1日-3%、3日連続-5%、週間-7%）
・ニュースサプライズ検知（Claude）
・口座ドローダウン連動
"""
import yfinance as yf
import pandas as pd
import anthropic
from dataclasses import dataclass
from src import config


NIKKEI_TICKER = "^N225"


@dataclass
class MarketCondition:
    status: str          # NORMAL / CAUTION / STOP
    max_positions: int   # 最大保有可能銘柄数
    reason: str          # 停止・縮小理由
    nikkei_trend: str    # uptrend / downtrend / sideways
    daily_change: float  # 本日騰落率
    three_day_change: float
    weekly_change: float
    news_risk: str       # LOW / MEDIUM / HIGH


def get_nikkei_data() -> pd.DataFrame:
    df = yf.download(NIKKEI_TICKER, period="1mo", interval="1d",
                     progress=False, auto_adjust=True)
    df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
    return df.dropna()


def check_nikkei_trend(df: pd.DataFrame) -> str:
    """日経225のトレンド判定（SMA25基準）"""
    if len(df) < 25:
        return "unknown"
    close = df["Close"]
    sma25 = close.rolling(25).mean()
    current = float(close.iloc[-1])
    sma_now = float(sma25.iloc[-1])
    sma_prev = float(sma25.iloc[-3])  # 3日前と比較してSMAの向き判定

    if current > sma_now and sma_now > sma_prev:
        return "uptrend"
    if current < sma_now and sma_now < sma_prev:
        return "downtrend"
    return "sideways"


def check_price_changes(df: pd.DataFrame) -> tuple[float, float, float]:
    """1日・3日・週間の騰落率を返す"""
    close = df["Close"]
    daily   = float((close.iloc[-1] - close.iloc[-2]) / close.iloc[-2] * 100)
    three_d = float((close.iloc[-1] - close.iloc[-4]) / close.iloc[-4] * 100) if len(df) >= 4 else 0.0
    weekly  = float((close.iloc[-1] - close.iloc[-6]) / close.iloc[-6] * 100) if len(df) >= 6 else 0.0
    return daily, three_d, weekly


def check_consecutive_decline(df: pd.DataFrame) -> bool:
    """直近3日間連続で下落しているか"""
    if len(df) < 4:
        return False
    close = df["Close"]
    return (float(close.iloc[-1]) < float(close.iloc[-2]) and
            float(close.iloc[-2]) < float(close.iloc[-3]) and
            float(close.iloc[-3]) < float(close.iloc[-4]))


NEWS_RISK_PROMPT = """あなたは市場リスク分析の専門家です。
以下のマーケットニュースを読み、市場への影響リスクを評価してください。

リスクレベル:
- HIGH: 戦争勃発・金融危機・大規模テロ・パンデミック・主要国デフォルト等
         → 株式市場に-5%以上のインパクトが予想される事態
- MEDIUM: 重大な地政学リスク・予想外の金融政策変更・大企業破綻等
           → 株式市場に-2〜-5%のインパクトが予想される事態
- LOW: 通常のニュース・軽微なリスク

JSONのみ返してください:
{"risk_level": "LOW", "reason": "特記事項なし"}"""


def check_news_risk(headlines: list[str]) -> tuple[str, str]:
    """ClaudeでニュースリスクをHIGH/MEDIUM/LOWで判定"""
    if not headlines or not config.ANTHROPIC_API_KEY:
        return "LOW", "ニュース情報なし"
    try:
        client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        msg = client.messages.create(
            model=config.CLAUDE_MODEL,
            max_tokens=256,
            system=NEWS_RISK_PROMPT,
            messages=[{"role": "user", "content": "\n".join(headlines[:15])}],
        )
        import json
        raw = msg.content[0].text.strip()
        if "```" in raw:
            raw = raw.split("```")[1].lstrip("json")
        data = json.loads(raw)
        return data.get("risk_level", "LOW"), data.get("reason", "")
    except Exception as e:
        return "LOW", f"判定エラー: {e}"


def evaluate_market(drawdown_pct: float = 0.0,
                    headlines: list[str] = None) -> MarketCondition:
    """
    相場環境を総合評価して取引可否・最大銘柄数を返す
    drawdown_pct: 口座の現在のドローダウン率（%）
    headlines: マーケットニュース見出しリスト
    """
    reasons = []

    # 日経225データ取得
    try:
        df = get_nikkei_data()
        nikkei_trend = check_nikkei_trend(df)
        daily, three_d, weekly = check_price_changes(df)
        consecutive = check_consecutive_decline(df)
    except Exception as e:
        print(f"[WARN] 日経データ取得失敗: {e}")
        return MarketCondition(
            status="NORMAL", max_positions=5, reason="データ取得失敗・通常実行",
            nikkei_trend="unknown", daily_change=0, three_day_change=0,
            weekly_change=0, news_risk="LOW"
        )

    # ニュースリスク判定（Claude）
    news_risk, news_reason = check_news_risk(headlines or [])

    # ━━━ 取引停止判定 ━━━
    stop = False

    # 日経トレンド下落
    if nikkei_trend == "downtrend":
        stop = True
        reasons.append(f"日経225下落トレンド中（SMA25割れ）")

    # 1日で-3%以上
    if daily <= -3.0:
        stop = True
        reasons.append(f"本日急落: {daily:.1f}%")

    # 3日連続下落かつ合計-5%以上
    if consecutive and three_d <= -5.0:
        stop = True
        reasons.append(f"3日連続下落・合計: {three_d:.1f}%")

    # 週間-7%以上
    if weekly <= -7.0:
        stop = True
        reasons.append(f"週間下落: {weekly:.1f}%")

    # ニュースリスクHIGH
    if news_risk == "HIGH":
        stop = True
        reasons.append(f"重大ニュースリスク: {news_reason}")

    # 口座DD8%超
    if drawdown_pct >= 8.0:
        stop = True
        reasons.append(f"口座DD超過: {drawdown_pct:.1f}%")

    if stop:
        return MarketCondition(
            status="STOP", max_positions=0,
            reason=" / ".join(reasons),
            nikkei_trend=nikkei_trend,
            daily_change=daily, three_day_change=three_d, weekly_change=weekly,
            news_risk=news_risk,
        )

    # ━━━ 取引縮小判定 ━━━
    caution = False

    # 3日連続下落（合計-5%未満）
    if consecutive and three_d <= -3.0:
        caution = True
        reasons.append(f"3日連続下落: {three_d:.1f}%")

    # ニュースリスクMEDIUM
    if news_risk == "MEDIUM":
        caution = True
        reasons.append(f"中程度ニュースリスク: {news_reason}")

    # 口座DD5〜8%
    if 5.0 <= drawdown_pct < 8.0:
        caution = True
        reasons.append(f"口座DD注意: {drawdown_pct:.1f}%")

    if caution:
        return MarketCondition(
            status="CAUTION", max_positions=2,
            reason=" / ".join(reasons),
            nikkei_trend=nikkei_trend,
            daily_change=daily, three_day_change=three_d, weekly_change=weekly,
            news_risk=news_risk,
        )

    # 通常
    return MarketCondition(
        status="NORMAL", max_positions=5,
        reason="異常なし",
        nikkei_trend=nikkei_trend,
        daily_change=daily, three_day_change=three_d, weekly_change=weekly,
        news_risk=news_risk,
    )
