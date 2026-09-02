from src.notification.line_notifier import LineNotifier
from src.notification.gmail_notifier import GmailNotifier
from src.signal_engine.signal_generator import TradingSignal


class NotificationService:
    """LINE優先・Gmail自動フォールバック"""

    def __init__(self):
        self.line = LineNotifier()
        self.gmail = GmailNotifier()

    def send_signal(self, signal: TradingSignal) -> None:
        if not self.line.send_signal(signal):
            self.gmail.send_signal(signal)

    def send_signals(self, signals: list[TradingSignal]) -> None:
        for signal in signals:
            self.send_signal(signal)

    def send_daily_summary(self, signals: list[TradingSignal], account_value: float, drawdown_pct: float) -> None:
        if not self.line.send_daily_summary(signals, account_value, drawdown_pct):
            self.gmail.send_daily_report(signals, account_value, drawdown_pct)

    def send_alert(self, message: str) -> None:
        if not self.line.send_alert(message):
            self.gmail.send_alert(message)
