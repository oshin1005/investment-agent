-- ═══════════════════════════════════════════════════════════
--  AI投資エージェント — Supabase テーブル定義
--  Supabase Dashboard の SQL Editor に貼り付けて Run してください
-- ═══════════════════════════════════════════════════════════

-- ① シグナル履歴（毎朝の分析結果）
create table if not exists signals (
  id            bigserial primary key,
  created_at    timestamptz default now(),
  ticker        text,
  name          text,
  sector        text,
  signal        text,          -- STRONG_BUY / BUY / HOLD / SELL
  confidence    int,
  tech_score    real,
  news_score    real,
  final_score   real,
  entry_price   real,
  target_price  real,
  stop_loss     real,
  target_pct    real,
  stop_loss_pct real,
  risk_flags    text,
  reasoning     text,
  market_status text           -- NORMAL / CAUTION / STOP
);
create index if not exists idx_signals_created on signals (created_at desc);
create index if not exists idx_signals_ticker  on signals (ticker);

-- ② 保有ポジション
create table if not exists positions (
  id                 bigserial primary key,
  created_at         timestamptz default now(),
  updated_at         timestamptz default now(),
  ticker             text,
  name               text,
  sector             text,
  saxo_order_id      text,
  saxo_position_id   text,
  entry_price        real,
  quantity           int,
  target_price       real,
  stop_loss          real,
  current_price      real,
  unrealized_pnl     real,
  unrealized_pnl_pct real,
  status             text default 'ORDERED'   -- ORDERED / OPEN / CLOSED
);
create index if not exists idx_positions_status on positions (status);

-- ③ 決済済み取引履歴
create table if not exists trades (
  id            bigserial primary key,
  entry_date    timestamptz,
  closed_at     timestamptz,
  ticker        text,
  name          text,
  sector        text,
  direction     text,
  entry_price   real,
  exit_price    real,
  target_price  real,
  stop_loss     real,
  quantity      int,
  pnl           real,
  pnl_pct       real,
  exit_reason   text,          -- target / stop / timeout
  holding_days  int,
  saxo_order_id text,
  status        text default 'OPEN'
);
create index if not exists idx_trades_closed on trades (closed_at desc);

-- ④ 相場環境ログ
create table if not exists market_log (
  id               bigserial primary key,
  date             date,
  status           text,       -- NORMAL / CAUTION / STOP
  nikkei_trend     text,
  daily_change     real,
  three_day_change real,
  weekly_change    real,
  news_risk        text,
  reason           text
);
create index if not exists idx_market_date on market_log (date desc);

-- ═══════════════════════════════════════════════════════════
--  成績サマリー用ビュー（ダッシュボードで見やすくするため）
-- ═══════════════════════════════════════════════════════════
create or replace view performance_summary as
select
  count(*)                                              as 取引数,
  count(*) filter (where pnl_pct > 0)                   as 勝ち,
  count(*) filter (where pnl_pct <= 0)                  as 負け,
  round((count(*) filter (where pnl_pct > 0))::numeric
        / nullif(count(*), 0) * 100, 1)                 as 勝率,
  round(avg(pnl_pct)::numeric, 2)                       as 平均損益率,
  round(sum(pnl_pct)::numeric, 1)                       as 累計損益率,
  round(sum(pnl)::numeric, 0)                           as 実現損益,
  round(
    (sum(pnl_pct) filter (where pnl_pct > 0))::numeric
    / nullif(abs(sum(pnl_pct) filter (where pnl_pct <= 0)), 0)
  , 2)                                                  as プロフィットファクター
from trades
where status = 'CLOSED';

-- 銘柄別の成績
create or replace view ticker_performance as
select
  ticker,
  name,
  count(*)                                    as 取引数,
  round((count(*) filter (where pnl_pct > 0))::numeric
        / nullif(count(*), 0) * 100, 0)       as 勝率,
  round(sum(pnl_pct)::numeric, 1)             as 累計損益率,
  round(sum(pnl)::numeric, 0)                 as 実現損益
from trades
where status = 'CLOSED'
group by ticker, name
order by sum(pnl_pct) desc;
