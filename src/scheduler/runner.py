from datetime import datetime
from src.market_data.yahoo_fetcher import get_all_tickers_with_data
from src.market_data.yahoo_fetcher import get_market_rss_news
from src.signal_engine.indicators import calculate_summary, screen_by_technical
from src.signal_engine.news_analyzer import NewsAnalyzer
from src.signal_engine.signal_generator import SignalGenerator
from src.signal_engine.market_filter import evaluate_market
from src.notification.notifier import NotificationService
from src.portfolio.models import init_db
from src.portfolio.tracker import PortfolioTracker


def run_signal_cycle(notify: bool = True) -> list:
    print(f"\n{'='*60}")
    print(f"  AI投資エージェント: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}")

    init_db()
    notifier = NotificationService()
    tracker  = PortfolioTracker()

    # ━━━ STEP 1: 相場環境フィルター ━━━
    print("\n【STEP 1】相場環境チェック中...")
    headlines = get_market_rss_news()

    # 口座DDを取得（Saxo未接続時は0%）
    try:
        from src.market_data.auth import SaxoAuth
        from src.market_data.data_fetcher import MarketDataFetcher
        auth    = SaxoAuth()
        fetcher = MarketDataFetcher(auth)
        account = fetcher.get_account_info()
        account_value = float(account.get("TotalValue", 0))
        drawdown_pct  = tracker.calculate_drawdown(account_value)
    except Exception:
        drawdown_pct = 0.0

    market = evaluate_market(drawdown_pct=drawdown_pct, headlines=headlines)
    tracker.log_market(market)  # 相場状態をDB記録

    status_emoji = {"NORMAL": "✅", "CAUTION": "⚠️", "STOP": "🛑"}
    print(f"  → 相場状態: {status_emoji.get(market.status, '')} {market.status}")
    print(f"     日経トレンド: {market.nikkei_trend} | "
          f"本日: {market.daily_change:+.1f}% | "
          f"3日: {market.three_day_change:+.1f}% | "
          f"週間: {market.weekly_change:+.1f}%")
    print(f"     ニュースリスク: {market.news_risk} | 理由: {market.reason}")

    if market.status == "STOP":
        msg = f"🛑 本日取引停止\n理由: {market.reason}"
        print(f"\n  {msg}")
        if notify:
            notifier.send_alert(msg)
        return []

    max_positions = market.max_positions
    if market.status == "CAUTION":
        print(f"  ⚠️ 注意モード: 最大{max_positions}銘柄に制限")

    # ━━━ STEP 2: データ取得 ━━━
    print("\n【STEP 2】Yahoo Financeからデータ取得中...")
    stock_data = get_all_tickers_with_data()
    print(f"  → {len(stock_data)}銘柄取得完了（除外済み）")

    # ━━━ STEP 3: テクニカル指標計算 ━━━
    print("\n【STEP 3】テクニカル指標計算中...")
    summaries = []
    for item in stock_data:
        try:
            s = calculate_summary(
                item["df_daily"], item["df_weekly"],
                item["ticker"], item["name"], item["sector"]
            )
            summaries.append(s)
        except Exception as e:
            print(f"  [WARN] {item['ticker']} スキップ: {e}")
    print(f"  → {len(summaries)}銘柄計算完了")

    # ━━━ STEP 4: テクニカルスクリーニング（上位10銘柄・スコア閾値75）━━━
    print("\n【STEP 4】テクニカルスクリーニング（上位10銘柄）...")
    candidates = screen_by_technical(summaries, top_n=10)
    print(f"  → 選定銘柄:")
    for s in candidates:
        print(f"     [{s.tech_score:.0f}pt] {s.name}({s.ticker}) "
              f"週足:{s.weekly_trend} MACD:{s.macd_signal}")

    # ━━━ STEP 5: ニュース分析（Claude 1回目）━━━
    print("\n【STEP 5】ニュース・情勢分析中（Claude API 1回目）...")
    news_analyzer = NewsAnalyzer()
    news_scores   = news_analyzer.analyze(candidates)
    merged        = news_analyzer.merge_scores(candidates, news_scores)
    print(f"  → ニューススコア:")
    for ns in merged:
        flag = f" ⚠️{ns.risk_flags}" if ns.risk_flags else ""
        print(f"     [{ns.final_score:.0f}pt] {ns.ticker} "
              f"ニュース:{ns.news_score:.0f} {ns.sentiment}{flag}")

    # ━━━ STEP 6: 最終シグナル生成（Claude 2回目）━━━
    top_n = min(max_positions, 5)
    print(f"\n【STEP 6】最終シグナル生成中（上位{top_n}銘柄・Claude API 2回目）...")
    generator  = SignalGenerator()
    signals    = generator.generate_signals(candidates, merged, top_n=top_n)
    actionable = generator.filter_actionable(signals)

    # 結果表示
    print(f"\n{'='*60}")
    print(f"  分析結果")
    print(f"{'='*60}")
    for s in signals:
        flag = f" ⚠️{s.risk_flags}" if s.risk_flags else ""
        print(f"  [{s.signal}] {s.name}({s.ticker}) 信頼度:{s.confidence}{flag}")
        print(f"    エントリー:¥{s.entry_price:,.0f} "
              f"目標:¥{s.target_price:,.0f}({s.target_pct:+.1f}%) "
              f"損切:¥{s.stop_loss:,.0f}({s.stop_loss_pct:.1f}%)")
        print(f"    根拠: {s.reasoning[:60]}...")
    print(f"{'='*60}")

    tracker.save_signals(signals, market_status=market.status)

    # ━━━ STEP 7: Gmail通知 ━━━
    if notify and actionable:
        print(f"\n【STEP 7】{len(actionable)}件をGmailで通知中...")
        notifier.send_signals(actionable)
        print("  → 完了")
    elif notify:
        print("\n【STEP 7】通知対象シグナルなし")

    # ━━━ STEP 8: ペーパートレード発注（成績検証の正） ━━━
    from src import config as _cfg
    from src.portfolio import paper_trader
    print(f"\n【STEP 8】ペーパートレード発注...")
    try:
        n = paper_trader.open_positions_from_signals(signals)
        print(f"  → {n}件をペーパー発注")
    except Exception as e:
        print(f"  [WARN] ペーパー発注失敗: {e}")

    # ━━━ STEP 9: Saxo SIM 自動注文（トークン有効時のみ） ━━━
    strong_buy = [s for s in actionable if s.signal in _cfg.ORDER_TARGET_SIGNALS]
    from src.market_data.auth import SaxoAuth
    saxo_ready = SaxoAuth().is_token_valid()

    if strong_buy and not saxo_ready:
        print(f"\n【STEP 9】Saxo SIM 自動注文: スキップ"
              f"（トークン未設定/期限切れ・ペーパートレードで記録済み）")
    elif strong_buy:
        print(f"\n【STEP 9】Saxo SIM 自動注文: {len(strong_buy)}件...")
        try:
            from src.order_manager.order_manager import OrderManager
            auth    = SaxoAuth()
            manager = OrderManager(auth)
            for sig in strong_buy:
                try:
                    result = manager.place_order(sig)
                    if result:
                        order_id = result.get("OrderId", "")
                        qty = manager.calc_quantity(
                            manager.get_account_equity(), sig.entry_price
                        )
                        tracker.record_order(sig, order_id, qty)
                        print(f"  ✅ 注文完了: {sig.name}({sig.ticker}) OrderId={order_id}")
                    else:
                        print(f"  ⚠️ 注文スキップ: {sig.name}({sig.ticker})")
                except Exception as e:
                    print(f"  [WARN] 注文失敗 {sig.ticker}: {e}")
        except Exception as e:
            print(f"  [INFO] Saxo未接続、注文スキップ: {type(e).__name__}")

    print(f"\n  完了: {datetime.now().strftime('%H:%M:%S')}")
    print(f"  Claude API使用: 2回 | 対象銘柄: {max_positions}銘柄上限\n")
    return signals
