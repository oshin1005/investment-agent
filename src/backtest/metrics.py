"""パフォーマンス指標の計算"""
import numpy as np
from dataclasses import dataclass
from src.backtest.engine import BacktestResult, Trade


@dataclass
class PerformanceMetrics:
    ticker: str
    name: str
    sector: str
    total_trades: int
    win_trades: int
    lose_trades: int
    win_rate: float          # %
    total_return: float      # %（全トレード合計）
    avg_profit: float        # 勝ちトレード平均リターン%
    avg_loss: float          # 負けトレード平均リターン%
    profit_factor: float     # 総利益 / 総損失
    max_drawdown: float      # %
    avg_holding_days: float
    exit_by_target: int      # 目標到達エグジット数
    exit_by_stop: int        # 損切りエグジット数
    exit_by_timeout: int     # タイムアウトエグジット数


def calc_metrics(result: BacktestResult) -> PerformanceMetrics:
    trades = result.closed_trades
    if not trades:
        return PerformanceMetrics(
            ticker=result.ticker, name=result.name, sector=result.sector,
            total_trades=0, win_trades=0, lose_trades=0,
            win_rate=0, total_return=0, avg_profit=0, avg_loss=0,
            profit_factor=0, max_drawdown=0, avg_holding_days=0,
            exit_by_target=0, exit_by_stop=0, exit_by_timeout=0,
        )

    wins  = [t.pnl_pct for t in trades if t.pnl_pct > 0]
    loses = [t.pnl_pct for t in trades if t.pnl_pct <= 0]

    gross_profit = sum(wins) if wins else 0.0
    gross_loss   = abs(sum(loses)) if loses else 0.0
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    # 最大ドローダウン（累積リターンから計算）
    cumulative = np.cumsum([t.pnl_pct for t in trades])
    peak = np.maximum.accumulate(cumulative)
    drawdown = peak - cumulative
    max_drawdown = float(np.max(drawdown)) if len(drawdown) > 0 else 0.0

    return PerformanceMetrics(
        ticker=result.ticker,
        name=result.name,
        sector=result.sector,
        total_trades=len(trades),
        win_trades=len(wins),
        lose_trades=len(loses),
        win_rate=len(wins) / len(trades) * 100 if trades else 0,
        total_return=sum(t.pnl_pct for t in trades),
        avg_profit=np.mean(wins) if wins else 0.0,
        avg_loss=np.mean(loses) if loses else 0.0,
        profit_factor=profit_factor,
        max_drawdown=max_drawdown,
        avg_holding_days=np.mean([t.holding_days for t in trades]) if trades else 0,
        exit_by_target=sum(1 for t in trades if t.exit_reason == "target"),
        exit_by_stop=sum(1 for t in trades if t.exit_reason == "stop"),
        exit_by_timeout=sum(1 for t in trades if t.exit_reason == "timeout"),
    )


def aggregate_metrics(metrics_list: list[PerformanceMetrics]) -> dict:
    """全銘柄の集計サマリー"""
    valid = [m for m in metrics_list if m.total_trades > 0]
    if not valid:
        return {}

    all_win_rate     = np.mean([m.win_rate for m in valid])
    all_total_return = sum(m.total_return for m in valid)
    all_pf           = [m.profit_factor for m in valid if m.profit_factor != float("inf")]
    all_max_dd       = max(m.max_drawdown for m in valid)

    return {
        "対象銘柄数": len(valid),
        "総トレード数": sum(m.total_trades for m in valid),
        "平均勝率": f"{all_win_rate:.1f}%",
        "全銘柄合計リターン": f"{all_total_return:.1f}%",
        "平均プロフィットファクター": f"{np.mean(all_pf):.2f}" if all_pf else "N/A",
        "最大ドローダウン": f"{all_max_dd:.1f}%",
        "目標到達エグジット": sum(m.exit_by_target for m in valid),
        "損切りエグジット": sum(m.exit_by_stop for m in valid),
        "タイムアウトエグジット": sum(m.exit_by_timeout for m in valid),
    }
