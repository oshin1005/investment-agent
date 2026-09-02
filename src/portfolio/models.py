from sqlalchemy import Column, Integer, Float, String, DateTime, Date, create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session
from datetime import datetime
from src import config


class Base(DeclarativeBase):
    pass


class Signal(Base):
    """毎サイクルのシグナル分析結果"""
    __tablename__ = "signals"
    id           = Column(Integer, primary_key=True, autoincrement=True)
    created_at   = Column(DateTime, default=datetime.utcnow)
    ticker       = Column(String)
    name         = Column(String)
    sector       = Column(String)
    signal       = Column(String)       # STRONG_BUY / BUY / HOLD / SELL
    confidence   = Column(Integer)
    tech_score   = Column(Float)
    news_score   = Column(Float)
    final_score  = Column(Float)
    entry_price  = Column(Float)
    target_price = Column(Float)
    stop_loss    = Column(Float)
    target_pct   = Column(Float)
    stop_loss_pct= Column(Float)
    risk_flags   = Column(String)       # JSON文字列
    reasoning    = Column(String)
    market_status= Column(String)       # NORMAL / CAUTION / STOP


class Position(Base):
    """Saxo SIMの保有ポジション（オープン中）"""
    __tablename__ = "positions"
    id              = Column(Integer, primary_key=True, autoincrement=True)
    created_at      = Column(DateTime, default=datetime.utcnow)
    updated_at      = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    ticker          = Column(String)
    name            = Column(String)
    sector          = Column(String)
    saxo_order_id   = Column(String)    # エントリー注文ID
    saxo_position_id= Column(String)    # 約定後のポジションID
    entry_price     = Column(Float)
    quantity        = Column(Integer)
    target_price    = Column(Float)
    stop_loss       = Column(Float)
    current_price   = Column(Float, nullable=True)
    unrealized_pnl  = Column(Float, nullable=True)   # 含み損益（円）
    unrealized_pnl_pct = Column(Float, nullable=True) # 含み損益（%）
    status          = Column(String, default="ORDERED")  # ORDERED / OPEN / CLOSED


class Trade(Base):
    """決済済みの取引履歴"""
    __tablename__ = "trades"
    id           = Column(Integer, primary_key=True, autoincrement=True)
    entry_date   = Column(DateTime, default=datetime.utcnow)
    closed_at    = Column(DateTime, nullable=True)
    ticker       = Column(String)
    name         = Column(String)
    sector       = Column(String)
    direction    = Column(String)        # BUY / SELL
    entry_price  = Column(Float)
    exit_price   = Column(Float, nullable=True)
    target_price = Column(Float, nullable=True)
    stop_loss    = Column(Float, nullable=True)
    quantity     = Column(Integer)
    pnl          = Column(Float, nullable=True)   # 損益（円）
    pnl_pct      = Column(Float, nullable=True)   # 損益（%）
    exit_reason  = Column(String, nullable=True)  # target / stop / timeout / manual
    holding_days = Column(Integer, nullable=True)
    saxo_order_id= Column(String, nullable=True)
    status       = Column(String, default="OPEN")  # OPEN / CLOSED


class MarketLog(Base):
    """毎日の相場状態ログ"""
    __tablename__ = "market_log"
    id              = Column(Integer, primary_key=True, autoincrement=True)
    date            = Column(Date, default=datetime.utcnow)
    status          = Column(String)     # NORMAL / CAUTION / STOP
    nikkei_trend    = Column(String)
    daily_change    = Column(Float)
    three_day_change= Column(Float)
    weekly_change   = Column(Float)
    news_risk       = Column(String)
    reason          = Column(String)


def get_engine():
    return create_engine(config.DATABASE_URL)


def init_db():
    engine = get_engine()
    Base.metadata.create_all(engine)
    _migrate_existing(engine)
    return engine


def _migrate_existing(engine):
    """既存テーブルに新カラムを追加（冪等）"""
    new_signal_cols = [
        ("sector",        "VARCHAR"),
        ("tech_score",    "FLOAT"),
        ("news_score",    "FLOAT"),
        ("final_score",   "FLOAT"),
        ("target_pct",    "FLOAT"),
        ("stop_loss_pct", "FLOAT"),
        ("risk_flags",    "VARCHAR"),
        ("market_status", "VARCHAR"),
    ]
    new_trade_cols = [
        ("entry_date",   "DATETIME"),
        ("sector",       "VARCHAR"),
        ("target_price", "FLOAT"),
        ("stop_loss",    "FLOAT"),
        ("pnl_pct",      "FLOAT"),
        ("exit_reason",  "VARCHAR"),
        ("holding_days", "INTEGER"),
    ]
    with engine.connect() as conn:
        for col, typ in new_signal_cols:
            try:
                conn.execute(text(f"ALTER TABLE signals ADD COLUMN {col} {typ}"))
                conn.commit()
            except Exception:
                pass
        for col, typ in new_trade_cols:
            try:
                conn.execute(text(f"ALTER TABLE trades ADD COLUMN {col} {typ}"))
                conn.commit()
            except Exception:
                pass
