import json
import anthropic
from src import config
from src.market_data.yahoo_fetcher import get_news, get_market_rss_news
from src.signal_engine.indicators import TechnicalSummary


SENTIMENT_PROMPT = """あなたは日本株の投資リサーチアナリストです。
以下の銘柄リストと各銘柄のニュース、マーケット全体ニュースを分析し、
各銘柄のニュース・情勢スコアをJSON配列で返してください。

スコア基準（0〜100）:
- 80〜100: 非常にポジティブ（好決算・増配・業績上方修正・業界追い風）
- 60〜79: やや ポジティブ（安定・特に悪材料なし）
- 40〜59: 中立（ポジネガ混在・情報不足）
- 20〜39: やや ネガティブ（業績懸念・競合激化）
- 0〜19: 非常にネガティブ（不祥事・業績下方修正・訴訟・規制リスク）

出力形式（JSONのみ・説明文不要）:
[
  {
    "ticker": "2802",
    "news_score": 65,
    "sentiment": "positive",
    "key_factors": "増収増益トレンド継続、海外展開好調",
    "risk_flags": []
  }
]

リスクフラグ例: ["業績下方修正", "訴訟リスク", "為替リスク大", "経営陣交代"]"""


from dataclasses import dataclass

@dataclass
class NewsScore:
    ticker: str
    news_score: float       # 0〜100
    sentiment: str          # positive / neutral / negative
    key_factors: str
    risk_flags: list[str]
    final_score: float = 0.0  # テクニカル60% + ニュース40%


class NewsAnalyzer:
    def __init__(self):
        self.client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    def analyze(self, summaries: list[TechnicalSummary]) -> list[NewsScore]:
        """銘柄リストのニュースをまとめてClaudeで分析（1回のAPI呼び出し）"""

        # マーケット全体ニュース
        market_news = get_market_rss_news()

        # 各銘柄のニュース収集
        stock_news_data = []
        for s in summaries:
            news_items = get_news(s.ticker)
            stock_news_data.append({
                "ticker": s.ticker,
                "name": s.name,
                "sector": s.sector,
                "news": news_items,
            })

        payload = {
            "market_context": market_news[:10],
            "stocks": stock_news_data,
        }

        message = self.client.messages.create(
            model=config.CLAUDE_MODEL,
            max_tokens=2048,
            system=SENTIMENT_PROMPT,
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
        scores = []
        for item in data:
            scores.append(NewsScore(
                ticker=item["ticker"],
                news_score=float(item["news_score"]),
                sentiment=item["sentiment"],
                key_factors=item.get("key_factors", ""),
                risk_flags=item.get("risk_flags", []),
            ))
        return scores

    def merge_scores(self,
                     summaries: list[TechnicalSummary],
                     news_scores: list[NewsScore]) -> list[NewsScore]:
        """テクニカル(60%) + ニュース(40%) で最終スコアを算出"""
        news_map = {n.ticker: n for n in news_scores}
        result = []
        for s in summaries:
            ns = news_map.get(s.ticker)
            if not ns:
                ns = NewsScore(
                    ticker=s.ticker,
                    news_score=50.0,
                    sentiment="neutral",
                    key_factors="情報なし",
                    risk_flags=[],
                )
            ns.final_score = s.tech_score * 0.6 + ns.news_score * 0.4
            result.append(ns)

        result.sort(key=lambda x: x.final_score, reverse=True)
        return result
