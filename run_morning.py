#!/usr/bin/env python3
"""毎朝8:00にlaunchdから実行される朝のシグナルサイクル"""
import sys, os, traceback
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"), override=True)

import jpbizday
from datetime import datetime

FORCE = "--force" in sys.argv
if not FORCE and not jpbizday.is_bizday(datetime.now().date()):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] 本日は東証非営業日。スキップ。")
    sys.exit(0)


def notify_failure(err: Exception) -> None:
    """処理が落ちたらGmailで知らせる（黙って止まるのを防ぐ）"""
    detail = traceback.format_exc()
    hint = ""
    msg = str(err)
    if "credit balance is too low" in msg:
        hint = ("【対処】Anthropic APIのクレジットが不足しています。\n"
                "https://console.anthropic.com の Plans & Billing から補充してください。\n"
                "補充するまで毎朝の分析は停止します。\n\n")
    elif "401" in msg or "Unauthorized" in msg:
        hint = "【対処】Saxoのアクセストークンが失効しています。get_token.py を実行してください。\n\n"

    body = (f"AI投資エージェントの朝の処理が失敗しました。\n\n"
            f"日時: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
            f"エラー: {type(err).__name__}: {msg[:300]}\n\n"
            f"{hint}"
            f"--- 詳細 ---\n{detail[-1500:]}")
    try:
        from src.notification.gmail_notifier import GmailNotifier
        GmailNotifier()._send("🚨 [投資エージェント] 朝の処理が失敗しました", body)
        print("  → 失敗をGmailで通知しました")
    except Exception as e2:
        print(f"  [WARN] 通知自体も失敗: {e2}")


try:
    from src.portfolio.models import init_db
    init_db()
    from src.scheduler.runner import run_signal_cycle
    run_signal_cycle(notify=True)
except Exception as e:
    print(f"\n[ERROR] 処理が失敗しました: {type(e).__name__}: {e}")
    notify_failure(e)
    sys.exit(1)
