"""バックテスト結果のHTMLレポート生成 + Gmail送信"""
from src.backtest.metrics import PerformanceMetrics, aggregate_metrics
from src.backtest.engine import Trade


def _signal_color(pf: float) -> str:
    if pf >= 1.5:
        return "#28a745"
    if pf >= 1.0:
        return "#ffc107"
    return "#dc3545"


def _wr_color(wr: float) -> str:
    if wr >= 55:
        return "#28a745"
    if wr >= 45:
        return "#ffc107"
    return "#dc3545"


def build_html_report(
    metrics_list: list[PerformanceMetrics],
    all_trades: list[Trade],
    period: str,
) -> str:
    agg = aggregate_metrics(metrics_list)

    # 集計サマリー行
    agg_rows = "".join(
        f"<tr><td><b>{k}</b></td><td>{v}</td></tr>"
        for k, v in agg.items()
    )

    # 銘柄別テーブル
    metrics_list_sorted = sorted(metrics_list, key=lambda m: m.total_return, reverse=True)
    ticker_rows = ""
    for m in metrics_list_sorted:
        if m.total_trades == 0:
            continue
        pf_str = f"{m.profit_factor:.2f}" if m.profit_factor != float("inf") else "∞"
        ticker_rows += f"""
        <tr>
          <td>{m.name}<br><small>{m.ticker} / {m.sector}</small></td>
          <td>{m.total_trades}</td>
          <td style="color:{_wr_color(m.win_rate)}"><b>{m.win_rate:.1f}%</b></td>
          <td style="color:{'#28a745' if m.total_return>0 else '#dc3545'}">
            <b>{m.total_return:+.1f}%</b>
          </td>
          <td style="color:{_signal_color(m.profit_factor if m.profit_factor!=float('inf') else 2)}">
            {pf_str}
          </td>
          <td>{m.max_drawdown:.1f}%</td>
          <td>{m.avg_holding_days:.1f}日</td>
          <td>{m.exit_by_target} / {m.exit_by_stop} / {m.exit_by_timeout}</td>
        </tr>"""

    # 直近トレード履歴（最新20件）
    recent_trades = sorted(all_trades, key=lambda t: t.exit_date or t.entry_date, reverse=True)[:20]
    trade_rows = ""
    for t in recent_trades:
        if t.exit_date is None:
            continue
        color = "#28a745" if t.pnl_pct > 0 else "#dc3545"
        trade_rows += f"""
        <tr>
          <td>{t.exit_date}</td>
          <td>{t.name}({t.ticker})</td>
          <td>{t.entry_date}</td>
          <td>¥{t.entry_price:,.0f}</td>
          <td>¥{t.exit_price:,.0f}</td>
          <td style="color:{color}"><b>{t.pnl_pct:+.1f}%</b></td>
          <td>{t.exit_reason}</td>
          <td>{t.holding_days}日</td>
        </tr>"""

    return f"""
<html><head><meta charset="utf-8">
<style>
  body {{ font-family: 'Helvetica Neue', sans-serif; margin: 20px; color: #333; }}
  h2 {{ color: #1a1a2e; border-bottom: 2px solid #1a1a2e; padding-bottom: 8px; }}
  h3 {{ color: #16213e; margin-top: 30px; }}
  table {{ border-collapse: collapse; width: 100%; margin-bottom: 20px; }}
  th {{ background: #16213e; color: white; padding: 10px 8px; text-align: left; font-size: 13px; }}
  td {{ padding: 8px; border-bottom: 1px solid #eee; font-size: 13px; }}
  tr:hover {{ background: #f8f9fa; }}
  .summary-box {{ background: #f0f4ff; border-left: 4px solid #1a1a2e;
                  padding: 15px 20px; margin: 20px 0; border-radius: 4px; }}
  .disclaimer {{ color: #888; font-size: 11px; margin-top: 40px; border-top: 1px solid #eee;
                 padding-top: 10px; }}
</style>
</head><body>
<h2>📊 バックテストレポート</h2>
<p>対象期間: <b>{period}</b> | 戦略: テクニカルスコアベース日足スイングトレード</p>
<p>エントリー条件: スコア≥70 | 利確: ATR×3 | 損切: ATR×1.5 | 最大保有: 10営業日</p>

<div class="summary-box">
  <h3 style="margin-top:0">📈 全体サマリー</h3>
  <table>{''.join(f'<tr><td><b>{k}</b></td><td>{v}</td></tr>' for k,v in agg.items())}</table>
</div>

<h3>🏦 銘柄別パフォーマンス</h3>
<table>
  <tr>
    <th>銘柄</th><th>取引数</th><th>勝率</th><th>合計リターン</th>
    <th>PF</th><th>最大DD</th><th>平均保有</th><th>利確/損切/TM</th>
  </tr>
  {ticker_rows}
</table>

<h3>📋 直近トレード履歴（最新20件）</h3>
<table>
  <tr>
    <th>エグジット日</th><th>銘柄</th><th>エントリー日</th>
    <th>買値</th><th>売値</th><th>損益</th><th>理由</th><th>保有期間</th>
  </tr>
  {trade_rows}
</table>

<p class="disclaimer">
※本レポートはバックテスト（過去データ検証）結果です。将来の運用成果を保証するものではありません。<br>
投資判断はご自身の責任において行ってください。
</p>
</body></html>
"""


def send_backtest_report(
    metrics_list: list[PerformanceMetrics],
    all_trades: list[Trade],
    period: str,
) -> bool:
    from src.notification.gmail_notifier import GmailNotifier
    gmail = GmailNotifier()
    html  = build_html_report(metrics_list, all_trades, period)
    agg   = aggregate_metrics(metrics_list)
    subject = (
        f"[バックテスト結果] 勝率{agg.get('平均勝率','?')} "
        f"合計リターン{agg.get('全銘柄合計リターン','?')} PF{agg.get('平均プロフィットファクター','?')}"
    )
    return gmail._send(subject, html, html=True)
