import requests
from src import config
from src.signal_engine.signal_generator import TradingSignal


SIGNAL_EMOJI = {
    "STRONG_BUY": "🚀",
    "BUY": "📈",
    "HOLD": "➡️",
    "SELL": "📉",
    "STRONG_SELL": "🔻",
}


def _format_signal_message(signal: TradingSignal) -> str:
    emoji = SIGNAL_EMOJI.get(signal.signal, "")
    return (
        f"━━━━━━━━━━━━━━━\n"
        f"{emoji} 【{signal.signal.replace('_', ' ')} シグナル】\n"
        f"銘柄: {signal.name} ({signal.ticker})\n"
        f"信頼度: {signal.confidence} / 100\n"
        f"現在値: ¥{signal.entry_price:,.0f}\n"
        f"推奨エントリー: ¥{signal.entry_price:,.0f}\n"
        f"目標価格: ¥{signal.target_price:,.0f}（{signal.target_pct:+.1f}%）\n"
        f"損切り: ¥{signal.stop_loss:,.0f}（{signal.stop_loss_pct:.1f}%）\n"
        f"\n根拠:\n{signal.reasoning}\n"
        f"━━━━━━━━━━━━━━━"
    )


def _format_daily_summary(signals: list[TradingSignal], account_value: float, drawdown_pct: float) -> str:
    buy_signals = [s for s in signals if "BUY" in s.signal]
    sell_signals = [s for s in signals if "SELL" in s.signal]
    return (
        f"━━━ 📊 日次サマリー ━━━\n"
        f"口座評価額: ¥{account_value:,.0f}\n"
        f"ドローダウン: {drawdown_pct:.1f}%\n"
        f"買いシグナル: {len(buy_signals)}件\n"
        f"売りシグナル: {len(sell_signals)}件\n"
        f"━━━━━━━━━━━━━━━"
    )


class LineNotifier:
    """LINE Messaging API通知"""

    LINE_API_URL = "https://api.line.me/v2/bot/message/push"

    def __init__(self):
        self.token = config.LINE_CHANNEL_ACCESS_TOKEN
        self.user_id = config.LINE_USER_ID

    def _send(self, text: str) -> bool:
        if not self.token or not self.user_id or self.token == "your_token":
            print("[WARN] LINE未設定、通知をスキップ")
            return False
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.token}",
        }
        payload = {
            "to": self.user_id,
            "messages": [{"type": "text", "text": text}],
        }
        resp = requests.post(self.LINE_API_URL, headers=headers, json=payload, timeout=10)
        return resp.status_code == 200

    def send_signal(self, signal: TradingSignal) -> bool:
        msg = _format_signal_message(signal)
        return self._send(msg)

    def send_signals(self, signals: list[TradingSignal]) -> None:
        for signal in signals:
            if signal.confidence >= config.SIGNAL_THRESHOLD:
                self.send_signal(signal)

    def send_daily_summary(self, signals: list[TradingSignal], account_value: float, drawdown_pct: float) -> bool:
        msg = _format_daily_summary(signals, account_value, drawdown_pct)
        return self._send(msg)

    def send_alert(self, message: str) -> bool:
        return self._send(f"⚠️ アラート\n{message}")
