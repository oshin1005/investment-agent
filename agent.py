#!/usr/bin/env python3
"""
AI自動売買エージェント - メインエントリーポイント
Saxo Bank API × Claude AI Agent
"""
import argparse
import sys
from src.portfolio.models import init_db


def main():
    parser = argparse.ArgumentParser(description="AI自動売買エージェント")
    parser.add_argument("--run-once", action="store_true", help="シグナル生成を1回実行して終了")
    parser.add_argument("--emergency-stop", action="store_true", help="緊急停止（全新規注文停止）")
    parser.add_argument("--init-db", action="store_true", help="データベース初期化")
    parser.add_argument("--test-notify", action="store_true", help="通知テスト")
    args = parser.parse_args()

    if args.init_db:
        print("[INFO] データベースを初期化します...")
        init_db()
        print("[INFO] 完了")
        return

    if args.emergency_stop:
        from src.market_data.auth import SaxoAuth
        from src.order_manager.order_manager import OrderManager
        print("[EMERGENCY] 緊急停止を実行します...")
        auth = SaxoAuth()
        manager = OrderManager(auth)
        manager.emergency_stop()
        return

    if args.test_notify:
        from src.notification.notifier import NotificationService
        from src.signal_engine.signal_generator import TradingSignal
        notifier = NotificationService()
        dummy = TradingSignal(
            ticker="7203", name="トヨタ自動車", signal="BUY", confidence=74,
            entry_price=3850.0, target_price=4050.0, stop_loss=3750.0,
            target_pct=5.2, stop_loss_pct=-2.6,
            reasoning="テスト通知: RSIが中立圏でMACDがゴールデンクロス形成中",
        )
        notifier.send_signal(dummy)
        print("[INFO] 通知テスト完了")
        return

    if args.run_once:
        from src.scheduler.scheduler import run_signal_cycle
        init_db()
        run_signal_cycle()
        return

    # 通常モード: スケジューラー起動（毎朝8:00自動実行）
    from src.scheduler.scheduler import start_scheduler
    start_scheduler()


if __name__ == "__main__":
    main()
