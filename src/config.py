import os
from dotenv import load_dotenv

load_dotenv(override=True)

SAXO_APP_KEY = os.getenv("SAXO_APP_KEY", "")
SAXO_APP_SECRET = os.getenv("SAXO_APP_SECRET", "")
SAXO_ACCESS_TOKEN = os.getenv("SAXO_ACCESS_TOKEN", "")
SAXO_REFRESH_TOKEN = os.getenv("SAXO_REFRESH_TOKEN", "")
SAXO_ENV = os.getenv("SAXO_ENV", "sim")

LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")
LINE_USER_ID = os.getenv("LINE_USER_ID", "")

GMAIL_ADDRESS = os.getenv("GMAIL_ADDRESS", "")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = "claude-sonnet-4-6"

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./data/trading.db")

SAXO_BASE_URLS = {
    "sim": "https://gateway.saxobank.com/sim/openapi",
    "live": "https://gateway.saxobank.com/openapi",
}

SAXO_BASE_URL = SAXO_BASE_URLS[SAXO_ENV]

# 収益目標パラメータ（要件定義書 3.3.1）
MONTHLY_PROFIT_TARGET_PCT = 5.0
ANNUAL_PROFIT_TARGET_PCT = 30.0
MAX_DRAWDOWN_PCT = 10.0
MAX_LOSS_PER_TRADE_PCT = 2.0
MAX_POSITIONS = 10
MAX_POSITION_RATIO_PCT = 20.0

# スクリーニングパラメータ（要件定義書 3.1.2）
VOLUME_FILTER_RATIO = 0.8
PRICE_CHANGE_FILTER_PCT = 0.3
TOP_N_CANDIDATES = 20

# テクニカル指標パラメータ（要件定義書 3.2.1）
SMA_PERIODS = [5, 25, 75]
RSI_PERIOD = 14
MACD_FAST, MACD_SLOW, MACD_SIGNAL = 12, 26, 9
BB_PERIOD, BB_STD = 20, 2
ATR_PERIOD = 14
VOLUME_LOOKBACK_DAYS = 20

# シグナル信頼度閾値（要件定義書 3.2.2）
STRONG_SIGNAL_THRESHOLD = 80
SIGNAL_THRESHOLD = 65

# ─────────────────────────────────────────
# モメンタムフィルター
# 2026/5〜8の実シグナル110件の検証で判明した調整:
#   直前20日で+10%以上上昇した銘柄を買うと勝率32%/PF0.36（高値掴み）
#   -3%未満の下落局面も勝率46%/PF0.79
#   -3%〜+10%の緩やかな上昇帯が勝率64%/PF2.24で最良
# ─────────────────────────────────────────
MOMENTUM_MIN_20D = -3.0    # 直前20日上昇率の下限（%）
MOMENTUM_MAX_20D = 10.0    # 直前20日上昇率の上限（%）
MOMENTUM_FILTER_ENABLED = True

# 自動発注の対象シグナル
# 同検証でSTRONG_BUYは勝率37.5%/PF0.53、BUYは勝率56%/PF1.26。
# Claudeが「強い」と判断する銘柄ほど既に上昇済みで高値掴みになる傾向があるため、
# STRONG_BUY単独ではなくBUY系全体を対象にする（モメンタムフィルターと併用）。
ORDER_TARGET_SIGNALS = ("STRONG_BUY", "BUY")
