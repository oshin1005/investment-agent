import json
from dataclasses import dataclass
import anthropic
from src import config
from src.signal_engine.indicators import TechnicalSummary
from src.signal_engine.news_analyzer import NewsScore


@dataclass
class TradingSignal:
    ticker: str
    name: str
    sector: str
    signal: str          # STRONG_BUY / BUY / HOLD / SELL / STRONG_SELL
    confidence: int      # 0-100
    entry_price: float
    target_price: float
    stop_loss: float
    target_pct: float
    stop_loss_pct: float
    tech_score: float
    news_score: float
    final_score: float
    reasoning: str
    risk_flags: list


SYSTEM_PROMPT = """あなたは日本株のシニア投資アナリストです。
テクニカル指標とニュース・情勢スコアを統合分析し、日足ベースのスイングトレード（数日〜2週間）シグナルを生成してください。

方針:
- ローリスク・ローリターン優先（月次+3〜5%目標）
- 週足トレンドに逆らわない
- ネガティブニュース・リスクフラグがある銘柄はHOLDまたはSELL推奨
- 目標リターンはリスク（損切り幅）の2倍以上を確保
- ストップロスはATR×1.5（日足ベース）

重要な調整（実運用110件の検証で判明した傾向）:
- context.ret_20_pct（直前20日の上昇率）が+10%を超える銘柄は、
  テクニカルが良好に見えても高値掴みになりやすく実績が著しく悪い（勝率32%）。
  この水準の銘柄はconfidenceを大きく下げ、原則HOLDとすること。
- ret_20_pctが-3%未満（下落局面）の銘柄も反発を狙うと負けやすい（勝率46%）。
- ret_20_pctが-3%〜+10%の緩やかな上昇局面が最も勝率が高い（勝率64%）。
  この帯にある銘柄を積極的に評価すること。
- テクニカルスコアの高さだけで強気判断をしないこと。スコアが高い銘柄は
  すでに上昇し切っている場合が多い。

出力形式（JSON配列のみ・説明文不要）:
[
  {
    "ticker": "2802",
    "signal": "BUY",
    "confidence": 72,
    "entry_price": 5006.0,
    "target_price": 5260.0,
    "stop_loss": 4880.0,
    "target_pct": 5.1,
    "stop_loss_pct": -2.5,
    "reasoning": "日本語での根拠説明（3〜4文）"
  }
]

シグナル基準:
- STRONG_BUY: 最終スコア80以上 かつ リスクフラグなし
- BUY: 最終スコア65〜79 かつ リスクフラグ1件以下
- HOLD: 最終スコア45〜64
- SELL: 最終スコア30〜44
- STRONG_SELL: 最終スコア30未満 またはリスクフラグ複数"""


class SignalGenerator:
    def __init__(self):
        self.client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    def generate_signals(self,
                          summaries: list[TechnicalSummary],
                          news_scores: list[NewsScore],
                          top_n: int = 5) -> list[TradingSignal]:
        """最終スコア上位N銘柄を1回のAPI呼び出しでシグナル生成"""

        # 最終スコア順で上位N銘柄を選択
        score_map  = {n.ticker: n for n in news_scores}
        tech_map   = {s.ticker: s for s in summaries}
        ranked     = sorted(news_scores, key=lambda x: x.final_score, reverse=True)[:top_n]

        payload = []
        for ns in ranked:
            s = tech_map.get(ns.ticker)
            if not s:
                continue
            payload.append({
                **s.to_dict(),
                "news_score": ns.news_score,
                "final_score": round(ns.final_score, 1),
                "sentiment": ns.sentiment,
                "key_factors": ns.key_factors,
                "risk_flags": ns.risk_flags,
            })

        message = self.client.messages.create(
            model=config.CLAUDE_MODEL,
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": json.dumps(payload, ensure_ascii=False, indent=2)
            }],
        )

        raw = message.content[0].text.strip()
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]

        data = json.loads(raw)
        signals = []
        for item in data:
            ns = score_map.get(item["ticker"])
            s  = tech_map.get(item["ticker"])
            signals.append(TradingSignal(
                ticker=item["ticker"],
                name=s.name if s else item["ticker"],
                sector=s.sector if s else "",
                signal=item["signal"],
                confidence=int(item["confidence"]),
                entry_price=float(item["entry_price"]),
                target_price=float(item["target_price"]),
                stop_loss=float(item["stop_loss"]),
                target_pct=float(item["target_pct"]),
                stop_loss_pct=float(item["stop_loss_pct"]),
                tech_score=s.tech_score if s else 0,
                news_score=ns.news_score if ns else 50,
                final_score=ns.final_score if ns else 0,
                reasoning=item["reasoning"],
                risk_flags=ns.risk_flags if ns else [],
            ))
        return signals

    def filter_actionable(self, signals: list[TradingSignal]) -> list[TradingSignal]:
        return [s for s in signals
                if s.signal in ("STRONG_BUY", "BUY", "SELL", "STRONG_SELL")
                and s.confidence >= config.SIGNAL_THRESHOLD]
