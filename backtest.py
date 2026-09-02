#!/usr/bin/env python3
"""
バックテスト実行スクリプト
使い方:
  python3 backtest.py                   # 全銘柄・2年間
  python3 backtest.py --period 1y       # 1年間
  python3 backtest.py --ticker 7203     # 特定銘柄のみ
  python3 backtest.py --no-email        # メール送信なし
"""
import argparse
import yfinance as yf
import pandas as pd
from src.market_data.yahoo_fetcher import NIKKEI225_TICKERS, HIGH_RISK_SECTORS
from src.backtest.engine import run_backtest_for_ticker, Trade
from src.backtest.metrics import calc_metrics, PerformanceMetrics
from src.backtest.report import send_backtest_report, build_html_report


PERIOD_MAP = {
    "1y": ("2y", "2024-05-01"),
    "2y": ("2y", "2023-05-01"),
}


def fetch_historical(ticker_code: str, period: str = "2y") -> "pd.DataFrame | None":
    ticker = f"{ticker_code}.T"
    df = yf.download(ticker, period=period, interval="1d", progress=False, auto_adjust=True)
    if df is None or df.empty:
        return None
    df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
    df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()
    df.index = pd.to_datetime(df.index)
    return df


def main():
    parser = argparse.ArgumentParser(description="バックテスト実行")
    parser.add_argument("--period", default="2y", choices=["1y", "2y"], help="バックテスト期間")
    parser.add_argument("--ticker", default=None, help="特定銘柄のみ（例: 7203）")
    parser.add_argument("--no-email", action="store_true", help="メール送信しない")
    args = parser.parse_args()

    yf_period = "2y" if args.period == "2y" else "2y"
    period_label = "過去2年間" if args.period == "2y" else "過去1年間"

    # 対象銘柄リスト
    from src.market_data.yahoo_fetcher import EXCLUDED_TICKERS
    targets = [
        (code, name, sector)
        for code, name, sector in NIKKEI225_TICKERS
        if sector not in HIGH_RISK_SECTORS and code not in EXCLUDED_TICKERS
    ]
    if args.ticker:
        targets = [(c, n, s) for c, n, s in targets if c == args.ticker]

    print(f"\n{'='*60}")
    print(f"  バックテスト開始: {period_label} | {len(targets)}銘柄")
    print(f"{'='*60}")
    print(f"  条件: スコア≥75でBUY | ATR×2利確 | ATR×1.5損切 | 最大10日保有 | 相場フィルター有\n")

    # 日経225過去データ取得（相場フィルター用）
    from src.backtest.market_filter_bt import load_nikkei_history
    print("  日経225履歴データ取得中...")
    nikkei_df = load_nikkei_history(yf_period)
    print(f"  → {len(nikkei_df)}営業日分取得完了\n")

    all_metrics: list[PerformanceMetrics] = []
    all_trades:  list[Trade]              = []

    for i, (code, name, sector) in enumerate(targets, 1):
        print(f"  [{i:02d}/{len(targets)}] {name}({code}) データ取得中...", end=" ")
        df = fetch_historical(code, yf_period)
        if df is None or len(df) < 60:
            print("データ不足 → スキップ")
            continue

        result  = run_backtest_for_ticker(code, name, sector, df,
                      buy_threshold=75.0, atr_target_mult=2.0,
                      nikkei_df=nikkei_df)
        metrics = calc_metrics(result)
        all_metrics.append(metrics)
        all_trades.extend(result.closed_trades)

        if metrics.total_trades > 0:
            pf_str = f"{metrics.profit_factor:.2f}" if metrics.profit_factor != float("inf") else "∞"
            print(f"完了 | {metrics.total_trades}取引 勝率{metrics.win_rate:.0f}% "
                  f"合計{metrics.total_return:+.1f}% PF{pf_str}")
        else:
            print("取引なし")

    # 結果集計
    from src.backtest.metrics import aggregate_metrics
    agg = aggregate_metrics(all_metrics)
    print(f"\n{'='*60}")
    print(f"  全体サマリー")
    print(f"{'='*60}")
    for k, v in agg.items():
        print(f"  {k}: {v}")

    # 上位・下位銘柄
    valid = sorted([m for m in all_metrics if m.total_trades > 0],
                   key=lambda m: m.total_return, reverse=True)
    if valid:
        print(f"\n  ▲ トップ5銘柄:")
        for m in valid[:5]:
            print(f"     {m.name}({m.ticker}): {m.total_return:+.1f}% 勝率{m.win_rate:.0f}%")
        print(f"\n  ▼ ワースト5銘柄:")
        for m in valid[-5:]:
            print(f"     {m.name}({m.ticker}): {m.total_return:+.1f}% 勝率{m.win_rate:.0f}%")

    # HTMLレポートをGmailで送信
    if not args.no_email:
        print(f"\n  Gmailでレポート送信中...")
        ok = send_backtest_report(all_metrics, all_trades, period_label)
        print(f"  {'✅ 送信完了' if ok else '⚠️ 送信失敗'}")
    else:
        # ローカルにHTML保存
        html = build_html_report(all_metrics, all_trades, period_label)
        with open("backtest_report.html", "w", encoding="utf-8") as f:
            f.write(html)
        print("\n  backtest_report.html に保存しました")

    print(f"\n{'='*60}\n")


if __name__ == "__main__":
    main()
