#!/usr/bin/env python3
"""
AI投資エージェント ダッシュボード

ローカル:  streamlit run dashboard.py
公開時:    Streamlit Community Cloud（st.secrets に SUPABASE_URL / SUPABASE_SERVICE_KEY / DASHBOARD_PASSWORD）
"""
import os
from datetime import datetime, timedelta, date

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# ───────────────────────── 設定 ─────────────────────────
st.set_page_config(
    page_title="AI投資エージェント",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed",
)

CAPITAL = 300_000  # 元金（円）


def _secret(key: str, default: str = "") -> str:
    """st.secrets → 環境変数 → .env の順に探す"""
    try:
        if key in st.secrets:
            return st.secrets[key]
    except Exception:
        pass
    v = os.getenv(key)
    if v:
        return v
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(os.path.dirname(__file__), ".env"), override=False)
        return os.getenv(key, default)
    except Exception:
        return default


# ───────────────────────── 認証 ─────────────────────────
def check_password() -> bool:
    pw = _secret("DASHBOARD_PASSWORD")
    if not pw:
        return True  # 未設定なら認証なし（ローカル用）
    if st.session_state.get("auth_ok"):
        return True
    st.title("🔒 AI投資エージェント")
    entered = st.text_input("パスワード", type="password")
    if entered:
        if entered == pw:
            st.session_state["auth_ok"] = True
            st.rerun()
        else:
            st.error("パスワードが違います")
    return False


if not check_password():
    st.stop()


# 接続情報が無いまま進むと supabase 側の例外になって原因が分かりにくいので、
# ここで設定漏れを明示する
_missing = [k for k in ("SUPABASE_URL", "SUPABASE_SERVICE_KEY") if not _secret(k)]
if _missing:
    st.title("⚙️ 設定が必要です")
    st.error(f"接続情報が設定されていません: {', '.join(_missing)}")
    st.markdown(
        """
**Streamlit Community Cloud の場合**

右下の **Manage app** → 右上の **⋮** → **Settings** → **Secrets** に次の3行を貼り付けて Save してください。

```toml
SUPABASE_URL = "https://xxxxx.supabase.co"
SUPABASE_SERVICE_KEY = "eyJhbGci..."
DASHBOARD_PASSWORD = "任意のパスワード"
```

**ローカルの場合**

同じ内容を `.streamlit/secrets.toml` に置くか、`.env` に設定してください。
        """
    )
    st.stop()


# ───────────────────────── データ取得 ─────────────────────────
@st.cache_resource
def get_client():
    from supabase import create_client
    return create_client(_secret("SUPABASE_URL"), _secret("SUPABASE_SERVICE_KEY"))


@st.cache_data(ttl=300)
def load(table: str, order: "str | None" = None, desc: bool = True, limit: int = 2000) -> pd.DataFrame:
    q = get_client().table(table).select("*")
    if order:
        q = q.order(order, desc=desc)
    r = q.limit(limit).execute()
    return pd.DataFrame(r.data or [])


trades    = load("trades", "closed_at")
positions = load("positions", "created_at")
signals   = load("signals", "created_at")
market    = load("market_log", "date")

for df, cols in [
    (trades,    ["entry_date", "closed_at"]),
    (positions, ["created_at", "updated_at"]),
    (signals,   ["created_at"]),
    (market,    ["date"]),
]:
    for c in cols:
        if c in df.columns:
            # Supabaseの日付は行によってマイクロ秒の有無が混在する。
            # pandasは先頭行から書式を推定するため、format="ISO8601" を明示しないと
            # 書式の違う行がまとめてNaTになる。
            df[c] = (
                pd.to_datetime(df[c], errors="coerce", utc=True, format="ISO8601")
                .dt.tz_convert("Asia/Tokyo").dt.tz_localize(None)
            )

closed = trades[trades["status"] == "CLOSED"].copy() if len(trades) else trades
open_pos = positions[positions["status"] == "OPEN"].copy() if len(positions) else positions

# ───────────────────────── ヘッダー ─────────────────────────
c1, c2 = st.columns([3, 1])
with c1:
    st.title("📈 AI投資エージェント")
with c2:
    if st.button("🔄 更新", width="stretch"):
        st.cache_data.clear()
        st.rerun()
    st.caption(f"更新: {datetime.now().strftime('%m/%d %H:%M')}")

# 今日の相場判定
if len(market):
    latest = market.iloc[0]
    status = latest.get("status", "-")
    icon = {"NORMAL": "✅", "CAUTION": "⚠️", "STOP": "🛑"}.get(status, "")
    color = {"NORMAL": "green", "CAUTION": "orange", "STOP": "red"}.get(status, "gray")
    st.markdown(
        f"<div style='padding:12px 18px;border-radius:10px;background:rgba(128,128,128,0.08);"
        f"border-left:5px solid {color};margin-bottom:8px'>"
        f"<b>{icon} 相場判定: {status}</b>　"
        f"<span style='color:gray'>{pd.Timestamp(latest['date']).strftime('%m/%d')} ／ "
        f"日経 本日 {latest.get('daily_change', 0):+.1f}%　3日 {latest.get('three_day_change', 0):+.1f}%　"
        f"週間 {latest.get('weekly_change', 0):+.1f}%　ニュース {latest.get('news_risk', '-')}</span>"
        f"<br><span style='font-size:0.85em;color:gray'>{latest.get('reason', '')}</span></div>",
        unsafe_allow_html=True,
    )

# ───────────────────────── KPI ─────────────────────────
if len(closed):
    n = len(closed)
    wins = (closed["pnl_pct"] > 0).sum()
    gw = closed.loc[closed["pnl_pct"] > 0, "pnl_pct"].sum()
    gl = abs(closed.loc[closed["pnl_pct"] <= 0, "pnl_pct"].sum())
    pf = gw / gl if gl else float("inf")
    total_pnl = closed["pnl"].sum()
    unreal = open_pos["unrealized_pnl"].fillna(0).sum() if len(open_pos) else 0

    # 最大ドローダウン（累計損益率ベース）
    eq_pct = closed.sort_values("closed_at")["pnl_pct"].cumsum()
    max_dd = float((eq_pct - eq_pct.cummax()).min()) if len(eq_pct) else 0.0

    k1, k2, k3, k4, k5, k6 = st.columns(6)
    k1.metric("実現損益", f"{total_pnl/10000:+,.1f}万", f"{closed['pnl_pct'].sum():+.1f}%")
    k2.metric("勝率", f"{wins/n*100:.1f}%", f"{wins}勝{n-wins}敗")
    k3.metric("PF", f"{pf:.2f}" if pf != float("inf") else "∞")
    k4.metric("平均損益率", f"{closed['pnl_pct'].mean():+.2f}%")
    k5.metric("保有中", f"{len(open_pos)}件", f"含み {unreal/10000:+,.1f}万")
    k6.metric("最大DD", f"{max_dd:.1f}%")
else:
    st.info("まだ決済済みの取引がありません")

st.divider()

# ───────────────────────── 推移グラフ ─────────────────────────
g1, g2 = st.columns([2, 1])

with g1:
    st.subheader("累計損益の推移")
    if len(closed):
        eq = closed.sort_values("closed_at").copy()
        eq["累計損益"] = eq["pnl"].cumsum()
        eq["累計損益率"] = eq["pnl_pct"].cumsum()
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=eq["closed_at"], y=eq["累計損益"], mode="lines+markers",
            line=dict(width=2.5, color="#2E86DE"),
            fill="tozeroy", fillcolor="rgba(46,134,222,0.12)",
            hovertemplate="%{x|%m/%d}<br>¥%{y:,.0f}<extra></extra>",
        ))
        fig.add_hline(y=0, line_dash="dot", line_color="gray", opacity=0.5)
        fig.update_layout(height=320, margin=dict(l=10, r=10, t=10, b=10),
                          yaxis_title="円", xaxis_title=None, showlegend=False)
        st.plotly_chart(fig, use_container_width=True)

with g2:
    st.subheader("月別損益")
    if len(closed):
        m = closed.copy()
        m["月"] = m["closed_at"].dt.strftime("%Y-%m")
        mon = m.groupby("月")["pnl"].sum().reset_index()
        mon["色"] = mon["pnl"].apply(lambda v: "#27AE60" if v >= 0 else "#E74C3C")
        fig = go.Figure(go.Bar(x=mon["月"], y=mon["pnl"], marker_color=mon["色"],
                               hovertemplate="%{x}<br>¥%{y:,.0f}<extra></extra>"))
        fig.update_layout(height=320, margin=dict(l=10, r=10, t=10, b=10),
                          yaxis_title="円", xaxis_title=None)
        st.plotly_chart(fig, use_container_width=True)

# ───────────────────────── 保有中 ─────────────────────────
st.subheader(f"保有中のポジション（{len(open_pos)}件）")
if len(open_pos):
    v = open_pos.copy()
    v["目標まで"] = (v["target_price"] / v["current_price"] - 1) * 100
    v["損切まで"] = (v["stop_loss"] / v["current_price"] - 1) * 100
    v["保有日数"] = (
        (pd.Timestamp.now().normalize() - pd.to_datetime(v["created_at"], errors="coerce"))
        .dt.days.fillna(0).astype(int)
    )
    show = pd.DataFrame({
        "銘柄": v["name"] + "(" + v["ticker"] + ")",
        "取得": v["entry_price"].map("¥{:,.0f}".format),
        "現在": v["current_price"].fillna(0).map("¥{:,.0f}".format),
        "株数": v["quantity"],
        "含み損益": v["unrealized_pnl"].fillna(0).map("¥{:+,.0f}".format),
        "含み率": v["unrealized_pnl_pct"].fillna(0).map("{:+.2f}%".format),
        "目標まで": v["目標まで"].map("{:+.1f}%".format),
        "損切まで": v["損切まで"].map("{:+.1f}%".format),
        "保有": v["保有日数"].astype(str) + "日",
    })
    st.dataframe(show, hide_index=True, width="stretch")
else:
    st.caption("保有中のポジションはありません")

st.divider()

# ───────────────────────── 銘柄別 & 決済理由 ─────────────────────────
b1, b2 = st.columns([3, 2])

with b1:
    st.subheader("銘柄別の成績")
    if len(closed):
        by = closed.groupby(["ticker", "name"]).agg(
            取引数=("pnl_pct", "size"),
            勝率=("pnl_pct", lambda s: (s > 0).mean() * 100),
            累計損益率=("pnl_pct", "sum"),
            実現損益=("pnl", "sum"),
        ).reset_index().sort_values("累計損益率", ascending=False)
        by["label"] = by["name"] + "(" + by["ticker"] + ")"
        by["色"] = by["累計損益率"].apply(lambda v: "#27AE60" if v >= 0 else "#E74C3C")
        lo, hi = float(by["累計損益率"].min()), float(by["累計損益率"].max())
        span = max(hi - lo, 1.0)
        label_x = max(hi, 0) + span * 0.06   # 数値ラベルは右端に揃えて置く（負の棒と軸ラベルの重なり防止）
        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=by["累計損益率"], y=by["label"], orientation="h", marker_color=by["色"],
            hovertemplate="%{y}<br>累計 %{x:+.1f}%<extra></extra>",
        ))
        fig.add_trace(go.Scatter(
            x=[label_x] * len(by), y=by["label"], mode="text",
            text=by.apply(lambda r: f"{r['累計損益率']:+.1f}%　勝率{r['勝率']:.0f}%・{r['取引数']}件", axis=1),
            textposition="middle right", textfont=dict(size=11),
            hoverinfo="skip", showlegend=False,
        ))
        fig.update_layout(
            height=max(280, 28 * len(by) + 60), margin=dict(l=10, r=10, t=10, b=10),
            xaxis=dict(title="累計損益率 (%)", range=[min(lo, 0) - span * 0.15, label_x + span * 0.9],
                       zeroline=True, zerolinecolor="gray"),
            yaxis=dict(autorange="reversed"), showlegend=False,
        )
        st.plotly_chart(fig, use_container_width=True)

with b2:
    st.subheader("決済理由の内訳")
    if len(closed):
        r = closed["exit_reason"].map({"target": "利確", "stop": "損切", "timeout": "期限切れ"}).value_counts()
        fig = go.Figure(go.Pie(
            labels=r.index, values=r.values, hole=0.5,
            marker_colors=["#27AE60", "#E74C3C", "#95A5A6"][:len(r)],
            textinfo="label+percent",
        ))
        fig.update_layout(height=300, margin=dict(l=10, r=10, t=10, b=10), showlegend=False)
        st.plotly_chart(fig, use_container_width=True)

        st.caption("損益率の分布")
        fig2 = px.histogram(closed, x="pnl_pct", nbins=20,
                            color_discrete_sequence=["#2E86DE"])
        fig2.add_vline(x=0, line_dash="dot", line_color="gray")
        fig2.update_layout(height=200, margin=dict(l=10, r=10, t=10, b=10),
                           xaxis_title="損益率 (%)", yaxis_title="件数", showlegend=False)
        st.plotly_chart(fig2, use_container_width=True)

st.divider()

# ───────────────────────── 今朝のシグナル ─────────────────────────
st.subheader("直近のシグナル")
if len(signals):
    latest_day = signals["created_at"].dt.date.max()
    today_sig = signals[signals["created_at"].dt.date == latest_day].copy()
    # 同日・同銘柄は最新だけ
    today_sig = today_sig.sort_values("created_at").drop_duplicates("ticker", keep="last")
    st.caption(f"{latest_day.strftime('%Y/%m/%d')} の分析結果 ／ {len(today_sig)}銘柄")
    order = {"STRONG_BUY": 0, "BUY": 1, "HOLD": 2, "SELL": 3, "STRONG_SELL": 4}
    today_sig["_o"] = today_sig["signal"].map(order).fillna(9)
    today_sig = today_sig.sort_values(["_o", "confidence"], ascending=[True, False])
    for _, s in today_sig.iterrows():
        badge = {"STRONG_BUY": "🟢🟢", "BUY": "🟢", "HOLD": "⚪", "SELL": "🔴", "STRONG_SELL": "🔴🔴"}.get(s["signal"], "")
        with st.expander(
            f"{badge} **{s['signal']}**　{s['name']}({s['ticker']})　信頼度 {s['confidence']}　"
            f"｜ ¥{s['entry_price']:,.0f} → 目標 ¥{s['target_price']:,.0f} ({s.get('target_pct') or 0:+.1f}%) "
            f"／ 損切 ¥{s['stop_loss']:,.0f} ({s.get('stop_loss_pct') or 0:+.1f}%)"
        ):
            cc1, cc2, cc3 = st.columns(3)
            cc1.metric("テクニカル", f"{s.get('tech_score') or 0:.0f}")
            cc2.metric("ニュース", f"{s.get('news_score') or 0:.0f}")
            cc3.metric("最終スコア", f"{s.get('final_score') or 0:.0f}")
            rf = s.get("risk_flags")
            if rf and rf not in ("[]", ""):
                st.warning(f"⚠️ {rf}")
            st.write(s.get("reasoning", ""))

st.divider()

# ───────────────────────── 決済履歴 ─────────────────────────
st.subheader("決済履歴")
if len(closed):
    h = closed.sort_values("closed_at", ascending=False).head(50)
    show = pd.DataFrame({
        "決済日": h["closed_at"].dt.strftime("%m/%d"),
        "銘柄": h["name"] + "(" + h["ticker"] + ")",
        "結果": h["exit_reason"].map({"target": "✅ 利確", "stop": "❌ 損切", "timeout": "⏱ 期限"}),
        "取得": h["entry_price"].map("¥{:,.0f}".format),
        "決済": h["exit_price"].map("¥{:,.0f}".format),
        "損益率": h["pnl_pct"].map("{:+.2f}%".format),
        "損益": h["pnl"].map("¥{:+,.0f}".format),
        "保有": h["holding_days"].fillna(0).astype(int).astype(str) + "日",
    })
    st.dataframe(show, hide_index=True, width="stretch", height=min(420, 38 * len(show) + 40))

# ───────────────────────── 相場ログ ─────────────────────────
with st.expander("相場判定の履歴"):
    if len(market):
        mm = market.sort_values("date", ascending=False).head(30)
        show = pd.DataFrame({
            "日付": mm["date"].dt.strftime("%m/%d"),
            "判定": mm["status"].map({"NORMAL": "✅ NORMAL", "CAUTION": "⚠️ CAUTION", "STOP": "🛑 STOP"}),
            "日経 本日": mm["daily_change"].map("{:+.1f}%".format),
            "3日": mm["three_day_change"].map("{:+.1f}%".format),
            "週間": mm["weekly_change"].map("{:+.1f}%".format),
            "ニュース": mm["news_risk"],
            "理由": mm["reason"].fillna("").str.slice(0, 60),
        })
        st.dataframe(show, hide_index=True, width="stretch")

st.caption("※ Yahoo Financeの実株価に基づく仮想売買（ペーパートレード）の記録です。実際の約定・スリッページ・手数料は含みません。")
