#!/usr/bin/env python3
"""毎日15:30にlaunchdから実行される引け後サマリー・ポジション同期"""
import sys, os
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

print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] 引け後サマリー・ポジション同期開始")

from src.portfolio.models import init_db
from src.portfolio.tracker import PortfolioTracker
from src.portfolio import paper_trader
from src.notification.notifier import NotificationService

init_db()
tracker  = PortfolioTracker()
notifier = NotificationService()

# ── ペーパートレード更新（約定・決済判定）──
print("\n【ペーパートレード更新】")
stats = paper_trader.update_positions()
print(f"  チェック{stats['checked']}件 / 新規約定{stats['entered']}件 / "
      f"決済{stats['closed']}件（利確{stats['target']} 損切{stats['stop']} 期限{stats['timeout']}）")

s = paper_trader.get_summary()
if s.get("trades"):
    pf = f"{s['pf']:.2f}" if s["pf"] != float("inf") else "∞"
    print(f"\n【ペーパートレード累計成績】")
    print(f"  決済 {s['trades']}件 | 勝率 {s['win_rate']:.1f}% | "
          f"平均 {s['avg_pct']:+.2f}% | 累計 {s['total_pct']:+.1f}% | PF {pf}")
    print(f"  実現損益 ¥{s['total_pnl']:+,.0f} | 保有中 {s['open']}件（含み損益 ¥{s['unrealized']:+,.0f}）")
else:
    print(f"  決済済み取引なし | 保有中 {s.get('open', 0)}件")

# ペーパートレードのレポートをGmail送信
try:
    from sqlalchemy.orm import Session
    from src.portfolio.models import Trade, Position, get_engine
    from datetime import date
    with Session(get_engine()) as _s:
        closed_today = _s.query(Trade).filter(
            Trade.status == "CLOSED",
            Trade.closed_at >= datetime.combine(date.today(), datetime.min.time()),
        ).all()
        open_pos = _s.query(Position).filter(Position.status == "OPEN").all()
        notifier.gmail.send_paper_report(s, closed_today, open_pos)
    print("  → ペーパートレードレポートを送信しました")
except Exception as e:
    print(f"  [WARN] レポート送信失敗: {e}")

# ── Saxoポジション同期（トークン有効時のみ）──
tracker.sync_positions()

# ── ローカルバックアップ（世代管理・直近14日分を保持）──
try:
    import shutil, glob
    os.makedirs("data/backup", exist_ok=True)
    dst = f"data/backup/trading_{datetime.now().strftime('%Y%m%d')}.db"
    shutil.copy2("data/trading.db", dst)
    olds = sorted(glob.glob("data/backup/trading_*.db"))[:-14]
    for f in olds:
        os.remove(f)
    print(f"\n【バックアップ】{dst}")
except Exception as e:
    print(f"  [WARN] バックアップ失敗: {e}")

# ── Supabaseへ同期（クラウド保管＋閲覧用）──
print("\n【Supabase同期】")
try:
    from src.portfolio import supabase_sync
    supabase_sync.sync_all()
except Exception as e:
    print(f"  [WARN] 同期失敗: {e}")

# ── Saxo口座サマリー（トークン有効時のみ）──
from src.market_data.auth import SaxoAuth
if SaxoAuth().is_token_valid():
    try:
        from src.market_data.data_fetcher import MarketDataFetcher
        fetcher = MarketDataFetcher(SaxoAuth())
        account = fetcher.get_account_info()
        value   = float(account.get("TotalValue", 0))
        dd      = tracker.calculate_drawdown(value)
        notifier.send_daily_summary([], value, dd)
        print(f"\n【Saxo口座】資産 ¥{value:,.0f} / DD {dd:.1f}%")
    except Exception as e:
        print(f"  [WARN] Saxo口座情報の取得に失敗: {e}")
else:
    print("\n【Saxo口座】トークン未設定/期限切れのためスキップ")

print(f"\n[{datetime.now().strftime('%H:%M')}] 完了")
