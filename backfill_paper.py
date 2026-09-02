#!/usr/bin/env python3
"""
過去シグナルからペーパートレード履歴を復元する（初回のみ実行）

DBに蓄積済みのシグナルを、当時ペーパートレードしていた場合の結果として
trades テーブルに書き戻す。以降は run_summary.py が日々更新する。

  python3 backfill_paper.py            # 新ロジック（モメンタムフィルター適用）
  python3 backfill_paper.py --all      # フィルターなし（全BUY系）
"""
import sys, os, argparse
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))
from dotenv import load_dotenv
load_dotenv(override=True)

import pandas as pd
from sqlalchemy.orm import Session

from src import config
from src.portfolio.models import Trade, get_engine, init_db
from src.portfolio.paper_trader import MAX_HOLD_DAYS, POSITION_BUDGET, LOT_SIZE
from verify_signals import load_signals, fetch_prices, evaluate


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="モメンタムフィルターを適用しない")
    ap.add_argument("--reset", action="store_true", help="既存のPAPER取引を削除してから復元")
    args = ap.parse_args()

    init_db()
    engine = get_engine()

    if args.reset:
        with Session(engine) as s:
            n = s.query(Trade).filter(Trade.saxo_order_id == "PAPER_BACKFILL").delete()
            s.commit()
            print(f"既存のバックフィル取引 {n}件を削除しました")

    signals = load_signals()
    tickers = {s["ticker"] for s in signals}
    start = (datetime.strptime(signals[0]["created_at"][:10], "%Y-%m-%d") - timedelta(days=40)).strftime("%Y-%m-%d")
    end   = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    print(f"株価取得中（{len(tickers)}銘柄）...")
    prices = fetch_prices(tickers, start, end)

    written = 0
    skipped_momentum = 0
    held_until = {}   # ticker -> 決済日（保有中の重複エントリーを防ぐ）

    with Session(engine) as session:
        for sig in signals:
            if sig["signal"] not in config.ORDER_TARGET_SIGNALS:
                continue
            df = prices.get(sig["ticker"])
            if df is None:
                continue

            sig_date = pd.Timestamp(sig["created_at"][:10])

            # 既に同銘柄を保有中ならスキップ（実運用と同じ制約）
            if sig["ticker"] in held_until and sig_date <= held_until[sig["ticker"]]:
                continue

            # モメンタムフィルター
            if not args.all:
                past = df[df.index <= sig_date]
                if len(past) < 22:
                    continue
                c = past["Close"]
                ret20 = float((c.iloc[-1] / c.iloc[-21] - 1) * 100)
                if not (config.MOMENTUM_MIN_20D <= ret20 < config.MOMENTUM_MAX_20D):
                    skipped_momentum += 1
                    continue

            r = evaluate(sig, df, MAX_HOLD_DAYS)
            if r is None:
                continue

            qty = max(int(POSITION_BUDGET / r["entry"] / LOT_SIZE), 1) * LOT_SIZE
            pnl = (r["exit_price"] - r["entry"]) * qty

            session.add(Trade(
                entry_date   = r["entry_date"].to_pydatetime(),
                closed_at    = r["exit_date"].to_pydatetime(),
                ticker       = sig["ticker"],
                name         = sig["name"],
                sector       = sig.get("sector") or "",
                direction    = "BUY",
                entry_price  = r["entry"],
                exit_price   = r["exit_price"],
                target_price = sig["target_price"],
                stop_loss    = sig["stop_loss"],
                quantity     = qty,
                pnl          = pnl,
                pnl_pct      = r["pnl_pct"],
                exit_reason  = r["exit_reason"],
                holding_days = r["holding"],
                saxo_order_id= "PAPER_BACKFILL",
                status       = "CLOSED",
            ))
            held_until[sig["ticker"]] = r["exit_date"]
            written += 1
        session.commit()

    print(f"\n{'='*80}")
    print(f"  ペーパートレード履歴を復元しました")
    print(f"{'='*80}")
    print(f"  記録した取引: {written}件")
    if not args.all:
        print(f"  モメンタムフィルターで除外: {skipped_momentum}件")

    with Session(engine) as session:
        trades = session.query(Trade).filter(
            Trade.saxo_order_id == "PAPER_BACKFILL").all()
    if trades:
        wins = [t for t in trades if t.pnl_pct > 0]
        gw = sum(t.pnl_pct for t in trades if t.pnl_pct > 0)
        gl = abs(sum(t.pnl_pct for t in trades if t.pnl_pct <= 0))
        pf = gw / gl if gl else float("inf")
        total_pnl = sum(t.pnl for t in trades)
        print(f"\n  勝率     : {len(wins)/len(trades)*100:.1f}% ({len(wins)}/{len(trades)})")
        print(f"  平均損益 : {sum(t.pnl_pct for t in trades)/len(trades):+.2f}%")
        print(f"  累計損益 : {sum(t.pnl_pct for t in trades):+.1f}%")
        print(f"  PF       : {pf:.2f}")
        print(f"  実現損益 : ¥{total_pnl:+,.0f}（1ポジション¥{POSITION_BUDGET:,}想定）")
        reasons = {}
        for t in trades:
            reasons[t.exit_reason] = reasons.get(t.exit_reason, 0) + 1
        print(f"  内訳     : {reasons}")
    print()


if __name__ == "__main__":
    main()
