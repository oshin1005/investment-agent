import json
from datetime import datetime
from sqlalchemy.orm import Session
from src.portfolio.models import Signal, Trade, Position, MarketLog, get_engine
from src.signal_engine.signal_generator import TradingSignal
from src import config


class PortfolioTracker:
    """ポジション管理・損益計算・取引履歴記録"""

    def __init__(self):
        self.engine = get_engine()
        self._peak_value: float = 0.0

    # ──────────────────────────────
    # シグナル保存
    # ──────────────────────────────
    def save_signals(self, signals: list, market_status: str = "NORMAL") -> None:
        with Session(self.engine) as session:
            for s in signals:
                record = Signal(
                    ticker       = s.ticker,
                    name         = s.name,
                    sector       = getattr(s, "sector", ""),
                    signal       = s.signal,
                    confidence   = s.confidence,
                    tech_score   = getattr(s, "tech_score", None),
                    news_score   = getattr(s, "news_score", None),
                    final_score  = getattr(s, "final_score", None),
                    entry_price  = s.entry_price,
                    target_price = s.target_price,
                    stop_loss    = s.stop_loss,
                    target_pct   = getattr(s, "target_pct", None),
                    stop_loss_pct= getattr(s, "stop_loss_pct", None),
                    risk_flags   = json.dumps(getattr(s, "risk_flags", []), ensure_ascii=False),
                    reasoning    = s.reasoning,
                    market_status= market_status,
                )
                session.add(record)
            session.commit()

    # ──────────────────────────────
    # 注文記録（Saxo注文直後に呼ぶ）
    # ──────────────────────────────
    def record_order(self, signal: TradingSignal, saxo_order_id: str, quantity: int) -> Position:
        with Session(self.engine) as session:
            pos = Position(
                ticker        = signal.ticker,
                name          = signal.name,
                sector        = getattr(signal, "sector", ""),
                saxo_order_id = saxo_order_id,
                entry_price   = signal.entry_price,
                quantity      = quantity,
                target_price  = signal.target_price,
                stop_loss     = signal.stop_loss,
                status        = "ORDERED",
            )
            session.add(pos)
            session.commit()
            session.refresh(pos)
            return pos

    # ──────────────────────────────
    # Saxoポジション同期
    # ──────────────────────────────
    def sync_positions(self) -> None:
        """SaxoのポジションをDBに同期（15:30の日次サマリー時に実行）"""
        try:
            from src.market_data.auth import SaxoAuth
            from src.order_manager.order_manager import OrderManager
            auth = SaxoAuth()
            if not auth.is_token_valid():
                print("  [DB] Saxo同期スキップ（トークン未設定/期限切れ）")
                return
            manager = OrderManager(auth)
            saxo_positions = manager.get_positions()
            saxo_pos_map   = {str(p.get("PositionId", "")): p for p in saxo_positions}

            with Session(self.engine) as session:
                db_positions = session.query(Position).filter(
                    Position.status.in_(["ORDERED", "OPEN"])
                ).all()

                for pos in db_positions:
                    # Saxoに対応ポジションがあれば更新
                    matched = None
                    for sp in saxo_positions:
                        base = sp.get("PositionBase", {})
                        if str(base.get("Uic", "")) and pos.ticker:
                            matched = sp
                            break

                    if matched:
                        base  = matched.get("PositionBase", {})
                        view  = matched.get("PositionView", {})
                        pos.saxo_position_id  = str(matched.get("PositionId", ""))
                        pos.current_price     = view.get("CurrentPrice")
                        pos.unrealized_pnl    = view.get("ProfitLossOnTrade")
                        pos.unrealized_pnl_pct = (
                            (pos.current_price - pos.entry_price) / pos.entry_price * 100
                            if pos.current_price and pos.entry_price else None
                        )
                        pos.status    = "OPEN"
                        pos.updated_at = datetime.utcnow()
                    else:
                        # Saxoにポジションがない = 決済済み
                        if pos.status == "OPEN":
                            self._close_position(session, pos)

                session.commit()
                print(f"  [DB] ポジション同期完了: {len(db_positions)}件")
        except Exception as e:
            print(f"  [WARN] ポジション同期失敗: {e}")

    def _close_position(self, session: Session, pos: Position) -> None:
        """ポジションをCLOSEDにしてTradeに移す"""
        pos.status = "CLOSED"
        trade = Trade(
            entry_date  = pos.created_at,
            closed_at   = datetime.utcnow(),
            ticker      = pos.ticker,
            name        = pos.name,
            sector      = pos.sector,
            direction   = "BUY",
            entry_price = pos.entry_price,
            exit_price  = pos.current_price,
            target_price= pos.target_price,
            stop_loss   = pos.stop_loss,
            quantity    = pos.quantity,
            pnl         = pos.unrealized_pnl,
            pnl_pct     = pos.unrealized_pnl_pct,
            holding_days= (datetime.utcnow() - pos.created_at).days if pos.created_at else None,
            saxo_order_id= pos.saxo_order_id,
            status      = "CLOSED",
        )
        session.add(trade)

    # ──────────────────────────────
    # 相場状態ログ
    # ──────────────────────────────
    def log_market(self, market) -> None:
        with Session(self.engine) as session:
            record = MarketLog(
                date            = datetime.utcnow().date(),
                status          = market.status,
                nikkei_trend    = market.nikkei_trend,
                daily_change    = market.daily_change,
                three_day_change= market.three_day_change,
                weekly_change   = market.weekly_change,
                news_risk       = market.news_risk,
                reason          = market.reason,
            )
            session.add(record)
            session.commit()

    # ──────────────────────────────
    # 統計・照会
    # ──────────────────────────────
    def get_open_positions(self) -> list:
        with Session(self.engine) as session:
            return session.query(Position).filter(
                Position.status.in_(["ORDERED", "OPEN"])
            ).order_by(Position.created_at.desc()).all()

    def open_position_count(self) -> int:
        return len(self.get_open_positions())

    def get_trade_summary(self) -> dict:
        with Session(self.engine) as session:
            trades = session.query(Trade).filter(Trade.status == "CLOSED").all()
            if not trades:
                return {"total": 0}
            wins  = [t for t in trades if (t.pnl or 0) > 0]
            total_pnl = sum(t.pnl or 0 for t in trades)
            return {
                "total":    len(trades),
                "wins":     len(wins),
                "losses":   len(trades) - len(wins),
                "win_rate": len(wins) / len(trades) * 100,
                "total_pnl": total_pnl,
            }

    def calculate_drawdown(self, current_value: float) -> float:
        if current_value > self._peak_value:
            self._peak_value = current_value
        if self._peak_value == 0:
            return 0.0
        return (self._peak_value - current_value) / self._peak_value * 100

    def can_open_position(self) -> bool:
        return self.open_position_count() < config.MAX_POSITIONS
