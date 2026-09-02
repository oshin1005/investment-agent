"""
APSchedulerによる自動実行スケジューラー
・毎朝8:00（東証営業日のみ）にシグナルサイクルを実行
・15:30に日次サマリーをGmailで送信
"""
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime
import jpbizday


def is_trading_day() -> bool:
    return jpbizday.isOpen(datetime.now().date())


def morning_cycle():
    if not is_trading_day():
        print(f"[{datetime.now().strftime('%H:%M')}] 本日は東証非営業日。スキップ。")
        return
    print(f"[{datetime.now().strftime('%H:%M')}] 朝の分析サイクル開始")
    from src.scheduler.runner import run_signal_cycle
    run_signal_cycle(notify=True)


def daily_summary():
    if not is_trading_day():
        return
    print(f"[{datetime.now().strftime('%H:%M')}] 日次サマリー・ポジション同期")
    from src.notification.notifier import NotificationService
    from src.portfolio.tracker import PortfolioTracker
    notifier = NotificationService()
    tracker  = PortfolioTracker()

    # Saxoポジション同期（約定確認・損益更新）
    tracker.sync_positions()

    try:
        from src.market_data.auth import SaxoAuth
        from src.market_data.data_fetcher import MarketDataFetcher
        auth    = SaxoAuth()
        fetcher = MarketDataFetcher(auth)
        account = fetcher.get_account_info()
        value   = float(account.get("TotalValue", 0))
        dd      = tracker.calculate_drawdown(value)
        summary = tracker.get_trade_summary()
        notifier.send_daily_summary([], value, dd)
        print(f"  取引統計: {summary}")
    except Exception as e:
        notifier.send_alert(f"日次サマリー取得失敗: {e}")


def start_scheduler():
    from src.portfolio.models import init_db
    init_db()

    scheduler = BlockingScheduler(timezone="Asia/Tokyo")

    # 毎朝8:00
    scheduler.add_job(
        morning_cycle,
        CronTrigger(hour=8, minute=0, day_of_week="mon-fri", timezone="Asia/Tokyo"),
        id="morning_cycle",
    )

    # 毎日15:30（引け後）
    scheduler.add_job(
        daily_summary,
        CronTrigger(hour=15, minute=30, day_of_week="mon-fri", timezone="Asia/Tokyo"),
        id="daily_summary",
    )

    print("="*50)
    print("  AI投資エージェント スケジューラー起動")
    print("  実行時刻: 毎朝8:00 / 15:30（東証営業日のみ）")
    print("="*50)
    scheduler.start()
