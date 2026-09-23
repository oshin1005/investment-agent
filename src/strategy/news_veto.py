"""
ニュースによる見送り判定（Claude）

押し目買いのシグナルが出た銘柄についてだけ呼ぶ。
銘柄を選ぶ・買いを勧める役はさせず、「今は買うべきでない明確な悪材料があるか」だけを判断させる。
Claudeの判断は過去データで検証できないため、影響範囲を「止める」方向だけに限定している。
"""
import json

import anthropic

from src import config
from src.market_data.yahoo_fetcher import get_news

PROMPT = """あなたは日本株のリスク管理担当です。
ある銘柄に、テクニカルな押し目買いのシグナルが出ています。
下のニュースを読み、「今この銘柄を買うのを見送るべき明確な悪材料」があるかだけを判断してください。

見送るべき例:
- 業績の下方修正・赤字転落・減配
- 不祥事・行政処分・訴訟・リコール
- 大規模な増資（株式の希薄化）
- 買収・上場廃止・TOBなど、株価が通常の値動きをしなくなる材料
- 直近数日以内に決算発表を控えている

見送らなくてよい例:
- 市場全体の地合いが悪いだけ（相場判定は別の仕組みで行っている）
- 目立ったニュースがない
- 一般的な業界動向や、すでに数週間前に出た材料

迷ったら見送らないでください（見送りすぎると取引機会を失うため）。
JSONのみで答えてください:
{"veto": true または false, "reason": "日本語で1〜2文"}"""


def check(ticker: str, name: str) -> dict:
    """{'veto': bool, 'reason': str, 'news_count': int}"""
    news = get_news(ticker, max_items=8)
    if not news:
        return {"veto": False, "reason": "直近のニュースなし", "news_count": 0}
    if not config.ANTHROPIC_API_KEY:
        return {"veto": False, "reason": "APIキー未設定のためニュース判定なし", "news_count": len(news)}

    body = f"銘柄: {name}（{ticker}）\n\nニュース:\n" + "\n".join(
        f"- {n['title']}：{n['summary'][:200]}" for n in news)
    try:
        msg = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY).messages.create(
            model=config.CLAUDE_MODEL, max_tokens=300, system=PROMPT,
            messages=[{"role": "user", "content": body}],
        )
        raw = msg.content[0].text.strip()
        if "```" in raw:
            raw = raw.split("```")[1].removeprefix("json").strip()
        data = json.loads(raw[raw.find("{"): raw.rfind("}") + 1])
        return {"veto": bool(data.get("veto")), "reason": str(data.get("reason", "")),
                "news_count": len(news)}
    except Exception as e:
        # 判定に失敗しても取引は止めない（テクニカルの検証済みルールを優先する）
        return {"veto": False, "reason": f"ニュース判定エラーのため判定なし（{type(e).__name__}）",
                "news_count": len(news)}
