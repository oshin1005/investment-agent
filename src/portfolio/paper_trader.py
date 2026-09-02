"""
ペーパートレード（仮想売買）エンジン

Saxo APIに依存せず、Yahoo Financeの実株価だけで売買を再現する。
・シグナル発生 → 翌営業日の始値でエントリー（positions に ORDERED→OPEN）
・毎日引け後に高値/安値をチェックし、目標到達→利確 / 損切り到達→損切
・最大保有日数を超えたら成行決済
・結果は trades テーブルに記録される

SIM口座のトークン期限やデモ口座の有効期限に影響されないため、
長期の成績検証はこちらを正とする。
"""
from datetime import datetime, timedelta
from sqlalchemy.orm import Session

import yfinance as yf
import pandas as pd

from src import config
from src.portfolio.models import Position, Trade, get_engine


MAX_HOLD_DAYS   = 10        # 最大保有営業日数
POSITION_BUDGET = 1_000_000 # 1ポジションあたりの想定投下額（円）
LOT_SIZE        = 100       # 日本株の売買単位


def _fetch(ticker: str, days: int = 40) -> "pd.DataFrame | None":
    """直近の日足を取得"""
    start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    end   = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    try:
        df = yf.download(f"{ticker}.T", start=start, end=end,
                         interval="1d", progress=False, auto_adjust=True)
        if df is None or df.empty:
            return None
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
        df.index = pd.to_datetime(df.index).tz_localize(None)
        return df
    except Exception as e:
        print(f"  [WARN] {ticker} 株価取得失敗: {e}")
        return None


def open_positions_from_signals(signals: list) -> int:
    """
    シグナルからペーパーポジションを作成する（発注相当）。
    同一銘柄で未決済ポジションがある場合は重複を作らない。
    """
    engine = get_engine()
    opened = 0
    with Session(engine) as session:
        for sig in signals:
            if sig.signal not in config.ORDER_TARGET_SIGNALS:
                continue
            existing = session.query(Position).filter(
                Position.ticker == sig.ticker,
                Position.status.in_(["ORDERED", "OPEN"]),
            ).first()
            if existing:
                print(f"  ・{sig.name}({sig.ticker}): 既に保有中のためスキップ")
                continue

            qty = max(int(POSITION_BUDGET / sig.entry_price / LOT_SIZE), 1) * LOT_SIZE
            pos = Position(
                ticker        = sig.ticker,
                name          = sig.name,
                sector        = getattr(sig, "sector", ""),
                saxo_order_id = "PAPER",
                entry_price   = sig.entry_price,
                quantity      = qty,
                target_price  = sig.target_price,
                stop_loss     = sig.stop_loss,
                status        = "ORDERED",
            )
            session.add(pos)
            opened += 1
            print(f"  ・{sig.name}({sig.ticker}) {sig.signal} "
                  f"{qty}株 目標¥{sig.target_price:,.0f} 損切¥{sig.stop_loss:,.0f}")
        session.commit()
    return opened


def update_positions() -> dict:
    """
    保有中のペーパーポジションを最新株価で評価し、決済条件を満たしたら決済する。
    引け後（15:30）に実行する想定。
    """
    engine = get_engine()
    stats = {"checked": 0, "entered": 0, "closed": 0, "target": 0, "stop": 0, "timeout": 0}

    with Session(engine) as session:
        positions = session.query(Position).filter(
            Position.status.in_(["ORDERED", "OPEN"])
        ).all()

        for pos in positions:
            stats["checked"] += 1
            df = _fetch(pos.ticker)
            if df is None or df.empty:
                continue

            created = pos.created_at or datetime.utcnow()
            after = df[df.index > pd.Timestamp(created.date())]

            # ── 未約定 → 翌営業日の始値で約定させる ──
            if pos.status == "ORDERED":
                if len(after) == 0:
                    continue  # まだ翌営業日が来ていない
                fill = float(after.iloc[0]["Open"])
                # 元の目標/損切り幅を実約定価格に合わせて再計算
                t_pct = (pos.target_price - pos.entry_price) / pos.entry_price
                s_pct = (pos.stop_loss    - pos.entry_price) / pos.entry_price
                pos.entry_price  = fill
                pos.target_price = fill * (1 + t_pct)
                pos.stop_loss    = fill * (1 + s_pct)
                pos.status       = "OPEN"
                pos.created_at   = after.index[0].to_pydatetime()
                stats["entered"] += 1
                print(f"  [約定] {pos.name}({pos.ticker}) @¥{fill:,.0f} × {pos.quantity}株")
                session.flush()
                after = df[df.index > pd.Timestamp(pos.created_at.date())]

            # ── 保有中 → 決済判定 ──
            held = df[df.index >= pd.Timestamp(pos.created_at.date())]
            if len(held) == 0:
                continue

            exit_reason = None
            exit_price  = None
            exit_date   = None
            for i in range(len(held)):
                row = held.iloc[i]
                low, high = float(row["Low"]), float(row["High"])
                # 同日に両方タッチした場合は損切り優先（保守的に評価）
                if low <= pos.stop_loss:
                    exit_reason, exit_price, exit_date = "stop", pos.stop_loss, held.index[i]
                    break
                if high >= pos.target_price:
                    exit_reason, exit_price, exit_date = "target", pos.target_price, held.index[i]
                    break
                if i + 1 >= MAX_HOLD_DAYS:
                    exit_reason, exit_price, exit_date = "timeout", float(row["Close"]), held.index[i]
                    break

            last_close = float(held.iloc[-1]["Close"])
            pos.current_price      = last_close
            pos.unrealized_pnl     = (last_close - pos.entry_price) * pos.quantity
            pos.unrealized_pnl_pct = (last_close - pos.entry_price) / pos.entry_price * 100
            pos.updated_at         = datetime.utcnow()

            if exit_reason:
                pnl_pct = (exit_price - pos.entry_price) / pos.entry_price * 100
                pnl     = (exit_price - pos.entry_price) * pos.quantity
                holding = (exit_date.date() - pos.created_at.date()).days

                session.add(Trade(
                    entry_date   = pos.created_at,
                    closed_at    = exit_date.to_pydatetime(),
                    ticker       = pos.ticker,
                    name         = pos.name,
                    sector       = pos.sector,
                    direction    = "BUY",
                    entry_price  = pos.entry_price,
                    exit_price   = exit_price,
                    target_price = pos.target_price,
                    stop_loss    = pos.stop_loss,
                    quantity     = pos.quantity,
                    pnl          = pnl,
                    pnl_pct      = pnl_pct,
                    exit_reason  = exit_reason,
                    holding_days = holding,
                    saxo_order_id= "PAPER",
                    status       = "CLOSED",
                ))
                pos.status = "CLOSED"
                stats["closed"] += 1
                stats[exit_reason] += 1
                mark = "✅" if pnl_pct > 0 else "❌"
                print(f"  [決済] {mark} {pos.name}({pos.ticker}) {exit_reason} "
                      f"{pnl_pct:+.2f}% (¥{pnl:+,.0f}) {holding}日保有")

        session.commit()
    return stats


def get_summary() -> dict:
    """ペーパートレードの累計成績"""
    engine = get_engine()
    with Session(engine) as session:
        trades = session.query(Trade).filter(
            Trade.status == "CLOSED",
            Trade.saxo_order_id.in_(["PAPER", "PAPER_BACKFILL"]),
        ).all()
        open_pos = session.query(Position).filter(Position.status == "OPEN").all()

        if not trades:
            return {"trades": 0, "open": len(open_pos)}

        wins = [t for t in trades if (t.pnl_pct or 0) > 0]
        gw = sum(t.pnl_pct for t in trades if (t.pnl_pct or 0) > 0)
        gl = abs(sum(t.pnl_pct for t in trades if (t.pnl_pct or 0) <= 0))
        return {
            "trades":     len(trades),
            "wins":       len(wins),
            "win_rate":   len(wins) / len(trades) * 100,
            "total_pnl":  sum(t.pnl or 0 for t in trades),
            "avg_pct":    sum(t.pnl_pct or 0 for t in trades) / len(trades),
            "total_pct":  sum(t.pnl_pct or 0 for t in trades),
            "pf":         gw / gl if gl else float("inf"),
            "open":       len(open_pos),
            "unrealized": sum(p.unrealized_pnl or 0 for p in open_pos),
        }
