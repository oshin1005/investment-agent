import yfinance as yf
import feedparser
import pandas as pd
from typing import Optional

# ─────────────────────────────────────────────────────────────
# 低位株ユニバース（元金30万円運用向け）
#
# 日本株は100株単位でしか買えないため、株価が高い銘柄は1単元の金額が
# 大きくなりすぎ、1回の損切りで元金の数割を失う。
# 元金30万円・1トレードのリスク上限2%（=6,000円）・平均損切り幅-5% とすると
# 適正な建玉は12万円 → 株価1,200円以下の銘柄しか使えない。
#
# 日経225全229銘柄を実勢株価でスクリーニングし、流動性（日平均売買代金）が
# 十分にあるものだけを選定した（2026-09-02時点）。
# セクター: infra/finance/material/industrial/tech/retail/service/consumer
# ─────────────────────────────────────────────────────────────
LOW_PRICE_TICKERS = [
    # 通信・インフラ（ディフェンシブ）
    ("9432", "NTT",                   "infra"),      # 175円 / 1単元1.8万
    ("9434", "ソフトバンク",           "infra"),      # 241円 / 1単元2.4万
    ("9501", "東京電力ホールディングス", "infra"),      # 564円 / 1単元5.6万
    ("9008", "京王電鉄",               "infra"),      # 786円 / 1単元7.9万
    # 素材・化学
    ("5401", "日本製鉄",               "material"),   # 692円 / 1単元6.9万
    ("4005", "住友化学",               "material"),   # 617円 / 1単元6.2万
    ("3861", "王子ホールディングス",    "material"),   # 873円 / 1単元8.7万
    ("5202", "日本板硝子",             "material"),   # 491円 / 1単元4.9万
    # 自動車・機械
    ("7201", "日産自動車",             "industrial"), # 318円 / 1単元3.2万
    ("7211", "三菱自動車工業",         "industrial"), # 374円 / 1単元3.7万
    ("6471", "日本精工",               "industrial"), # 1,099円 / 1単元11.0万
    ("6472", "NTN",                   "industrial"), # 373円 / 1単元3.7万
    # テック・電機
    ("4755", "楽天グループ",           "tech"),       # 727円 / 1単元7.3万
    ("4689", "LINEヤフー",             "tech"),       # 534円 / 1単元5.3万
    ("4902", "コニカミノルタ",         "tech"),       # 667円 / 1単元6.7万
    ("6753", "シャープ",               "tech"),       # 636円 / 1単元6.4万
    # 小売・サービス
    ("3092", "ZOZO",                  "retail"),     # 1,130円 / 1単元11.3万
]

# 旧ユニバース（高位株中心）。元金が100万円以上になったら復帰を検討する。
# セクター: food/pharma/infra/finance/industrial/tech/retail/energy/other
HIGH_PRICE_TICKERS = [
    # ディフェンシブ・内需（優先）
    ("2802", "味の素",               "food"),
    ("2914", "日本たばこ産業",        "food"),
    ("2269", "明治ホールディングス",   "food"),
    ("2282", "日本ハム",              "food"),
    ("4502", "武田薬品工業",          "pharma"),
    ("4519", "中外製薬",             "pharma"),
    ("4568", "第一三共",             "pharma"),
    ("4543", "テルモ",               "pharma"),
    ("9432", "日本電信電話",          "infra"),
    ("9433", "KDDI",                "infra"),
    ("9020", "東日本旅客鉄道",        "infra"),
    ("9022", "東海旅客鉄道",          "infra"),
    ("8306", "三菱UFJフィナンシャル", "finance"),
    ("8316", "三井住友フィナンシャル", "finance"),
    ("8411", "みずほフィナンシャル",   "finance"),
    ("8766", "東京海上ホールディングス","finance"),
    ("8058", "三菱商事",             "trading"),
    ("8031", "三井物産",             "trading"),
    ("8001", "伊藤忠商事",           "trading"),
    ("8802", "三菱地所",             "realestate"),
    # 工業・素材
    ("7203", "トヨタ自動車",          "industrial"),
    ("7267", "本田技研工業",          "industrial"),
    ("7270", "SUBARU",              "industrial"),
    ("6367", "ダイキン工業",          "industrial"),
    ("6326", "クボタ",               "industrial"),
    ("7011", "三菱重工業",            "industrial"),
    ("5401", "日本製鉄",             "material"),
    ("5108", "ブリヂストン",          "material"),
    ("4063", "信越化学工業",          "material"),
    # テック（ボラ高め・初期は絞る）
    ("6501", "日立製作所",            "tech"),
    ("6702", "富士通",               "tech"),
    ("6954", "ファナック",            "tech"),
    ("6902", "デンソー",             "tech"),
    ("6762", "TDK",                 "tech"),
    ("6971", "京セラ",               "tech"),
    # 半導体（ハイリスク・除外候補）
    ("8035", "東京エレクトロン",       "semiconductor"),
    ("6861", "キーエンス",            "semiconductor"),
    ("6723", "ルネサスエレクトロニクス","semiconductor"),
    # その他
    ("3382", "セブン&アイ",           "retail"),
    ("4661", "オリエンタルランド",     "leisure"),
    ("6098", "リクルート",            "service"),
    ("4911", "資生堂",               "consumer"),
    ("7751", "キヤノン",              "tech"),
    ("7832", "バンダイナムコ",         "leisure"),
    ("2413", "エムスリー",            "service"),
    ("4307", "野村総合研究所",         "service"),
    ("7741", "HOYA",                "tech"),
    ("9984", "ソフトバンクグループ",   "tech"),
    ("6758", "ソニーグループ",         "tech"),
]

# 実際に使うユニバース（元金30万円のため低位株を採用）
NIKKEI225_TICKERS = LOW_PRICE_TICKERS

# 初期フェーズで除外するハイリスクセクター
HIGH_RISK_SECTORS = {"semiconductor"}

# 除外銘柄
# 低位株ユニバースを過去2年でバックテスト（モメンタムフィルター適用済み）した結果、
# PF0.7未満かつ10取引以上の銘柄を除外する。
# いずれも「業績不振で株価が下がり続けた結果として低位株になった」タイプで、
# 一時的な反発を狙っても下降トレンドに飲まれる。
# 同じ低位株でもNTT・ソフトバンクのように株式分割で低位になった銘柄とは性質が異なる。
EXCLUDED_TICKERS = {
    "7201",  # 日産自動車     PF0.43 勝率30% 累計-40.7%
    "6753",  # シャープ       PF0.16 勝率21% 累計-35.8%
    "4755",  # 楽天グループ   PF0.59 勝率43% 累計-20.6%
    "9008",  # 京王電鉄       PF0.61 勝率46% 累計-17.1%
}

_LEGACY_EXCLUDED = {
    "2282",  # 日本ハム        PF0.74
    "4519",  # 中外製薬        PF0.60
    "4568",  # 第一三共        PF0.40
    "4543",  # テルモ          PF0.86
    "9432",  # NTT            PF0.52
    "9433",  # KDDI           PF0.86
    "8766",  # 東京海上HD      PF0.72
    "7203",  # トヨタ自動車    PF0.66
    "7267",  # 本田技研        PF0.50
    "7270",  # SUBARU         PF0.43
    "6326",  # クボタ          PF0.92
    "7011",  # 三菱重工業      PF0.92
    "5401",  # 日本製鉄        PF0.98
    "6501",  # 日立製作所      PF0.82
    "6902",  # デンソー        PF0.49
    "4661",  # オリエンタルランド PF0.63
    "6098",  # リクルート      PF0.77
    "4911",  # 資生堂          PF0.84
    "7751",  # キヤノン        PF0.55
    "2413",  # エムスリー      PF0.57
    "6758",  # ソニー          PF0.99
    "4307",  # 野村総合研究所  PF0.51
    "6971",  # 京セラ          PF0.84
}

# セクター別最大銘柄数（分散管理）
MAX_PER_SECTOR = 2


def get_ohlcv_daily(ticker_code: str, period: str = "3mo") -> Optional[pd.DataFrame]:
    """日足OHLCVを取得（過去3ヶ月）"""
    ticker = f"{ticker_code}.T"
    df = yf.download(ticker, period=period, interval="1d", progress=False, auto_adjust=True)
    if df is None or df.empty:
        return None
    df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
    return df[["Open", "High", "Low", "Close", "Volume"]].dropna()


def get_ohlcv_weekly(ticker_code: str, period: str = "1y") -> Optional[pd.DataFrame]:
    """週足OHLCVを取得（過去1年・週足トレンド確認用）"""
    ticker = f"{ticker_code}.T"
    df = yf.download(ticker, period=period, interval="1wk", progress=False, auto_adjust=True)
    if df is None or df.empty:
        return None
    df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
    return df[["Open", "High", "Low", "Close", "Volume"]].dropna()


def get_news(ticker_code: str, max_items: int = 5) -> list[dict]:
    """yfinanceから英語ニュースを取得"""
    try:
        ticker = yf.Ticker(f"{ticker_code}.T")
        news = ticker.news or []
        results = []
        for item in news[:max_items]:
            content = item.get("content", {})
            results.append({
                "title": content.get("title", ""),
                "summary": content.get("summary", ""),
                "source": content.get("provider", {}).get("displayName", ""),
            })
        return results
    except Exception:
        return []


def get_market_rss_news() -> list[str]:
    """Yahoo Finance Japan RSSから日本語マーケットニュースを取得"""
    rss_urls = [
        "https://news.yahoo.co.jp/rss/topics/business.xml",
        "https://www.nikkei.com/news/category/markets/rss.xml",
    ]
    headlines = []
    for url in rss_urls:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:5]:
                headlines.append(entry.get("title", ""))
        except Exception:
            continue
    return headlines


def get_all_tickers_with_data() -> list[dict]:
    """全銘柄の日足・週足データを取得してリスト返却"""
    results = []
    for code, name, sector in NIKKEI225_TICKERS:
        # ハイリスクセクター・ワースト銘柄は除外
        if sector in HIGH_RISK_SECTORS or code in EXCLUDED_TICKERS:
            continue
        df_daily = get_ohlcv_daily(code)
        df_weekly = get_ohlcv_weekly(code)
        if df_daily is not None and len(df_daily) >= 30:
            results.append({
                "ticker": code,
                "name": name,
                "sector": sector,
                "df_daily": df_daily,
                "df_weekly": df_weekly,
            })
    return results
