#!/usr/bin/env python3
"""
接続状況の一括確認

  python3 healthcheck.py

自動実行・外部API・データ同期が今も生きているかをまとめて点検する。
"""
import os
import sys
import subprocess
import sqlite3
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))
from dotenv import load_dotenv
load_dotenv(".env", override=True)

OK, NG, WARN = "✅", "❌", "⚠️ "
results = []


def check(name, fn):
    try:
        mark, detail = fn()
    except Exception as e:
        mark, detail = NG, f"{type(e).__name__}: {str(e)[:70]}"
    results.append((mark, name, detail))
    print(f"  {mark} {name:<22} {detail}")


# ── 1. 自動実行（launchd）──
def _launchd():
    out = subprocess.run(["launchctl", "list"], capture_output=True, text=True).stdout
    jobs = [l for l in out.splitlines() if "investment-agent" in l]
    if len(jobs) < 2:
        return NG, f"登録{len(jobs)}件（朝8:00と15:30の2件必要）"
    bad = [j for j in jobs if j.split("\t")[1] not in ("0", "-")]
    label = " / ".join(j.split("\t")[-1].split(".")[-1] for j in jobs)
    if bad:
        return WARN, f"{label} — 前回終了コード異常"
    return OK, f"{label} の2件が登録済み"


# ── 2. 直近の実行ログ ──
def _last_run():
    if not os.path.exists("logs/morning.log"):
        return NG, "ログなし"
    import re
    stamps = re.findall(r"AI投資エージェント[^:\n]*: (\d{4}-\d{2}-\d{2} \d{2}:\d{2})",
                        open("logs/morning.log", errors="replace").read())
    if not stamps:
        return NG, "実行記録なし"
    last = stamps[-1]
    d = datetime.strptime(last[:10], "%Y-%m-%d")
    days = (datetime.now().date() - d.date()).days
    # 土日祝を挟んだ空きは正常。直近の営業日に動いていたかで判定する
    import jpbizday
    prev_biz = datetime.now().date() - timedelta(days=1)
    while not jpbizday.is_bizday(prev_biz):
        prev_biz -= timedelta(days=1)
    mark = OK if d.date() >= prev_biz else WARN
    return mark, f"最終 {last}（{days}日前）"


# ── 3. Claude API ──
def _claude():
    import anthropic
    from src import config
    if not config.ANTHROPIC_API_KEY:
        return NG, "APIキー未設定"
    c = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    m = c.messages.create(model=config.CLAUDE_MODEL, max_tokens=8,
                          messages=[{"role": "user", "content": "hi"}])
    return OK, f"応答あり（{config.CLAUDE_MODEL}）"


# ── 4. Supabase ──
def _supabase():
    from supabase import create_client
    url, key = os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_KEY")
    if not url or not key:
        return NG, "接続情報が未設定"
    sb = create_client(url, key)
    counts = {}
    for t in ("signals", "trades", "positions", "market_log"):
        counts[t] = sb.table(t).select("id", count="exact").limit(1).execute().count
    return OK, f"signals {counts['signals']} / trades {counts['trades']} / market {counts['market_log']}"


# ── 5. ローカルDBとの同期ずれ ──
def _sync():
    con = sqlite3.connect("data/trading.db")
    local = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
             for t in ("signals", "trades", "positions", "market_log")}
    con.close()
    from supabase import create_client
    sb = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_KEY"))
    remote = {t: sb.table(t).select("id", count="exact").limit(1).execute().count
              for t in local}
    diff = {t: local[t] - remote[t] for t in local if local[t] != remote[t]}
    if not diff:
        return OK, f"一致（ローカル{sum(local.values())}行）"
    return WARN, f"差分あり {diff} — 次の15:30同期で解消見込み"


# ── 6. Gmail ──
def _gmail():
    import smtplib
    from src import config
    if not config.GMAIL_ADDRESS or not config.GMAIL_APP_PASSWORD:
        return NG, "認証情報が未設定"
    s = smtplib.SMTP("smtp.gmail.com", 587, timeout=10)
    s.starttls()
    s.login(config.GMAIL_ADDRESS, config.GMAIL_APP_PASSWORD)
    s.quit()
    return OK, f"ログイン成功（{config.GMAIL_ADDRESS}）"


# ── 7. 株価取得 ──
def _yahoo():
    import yfinance as yf
    df = yf.download("^N225", period="5d", interval="1d",
                     progress=False, auto_adjust=True)
    if df is None or df.empty:
        return NG, "データ取得失敗"
    last = df.index[-1].date()
    days = (datetime.now().date() - last).days
    close = float(df["Close"].iloc[-1].squeeze())
    return (OK if days <= 3 else WARN), f"日経 {close:,.0f}円（{last} 時点）"


# ── 8. Saxo ──
def _saxo():
    from src.market_data.auth import SaxoAuth
    a = SaxoAuth()
    if not a.is_token_valid():
        return WARN, "トークン期限切れ（発注は停止中／検証はペーパートレードで継続）"
    return OK, "トークン有効"


print("=" * 74)
print(f"  接続状況の確認  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
print("=" * 74)
print("\n【自動実行】")
check("launchd登録", _launchd)
check("直近の実行", _last_run)
print("\n【外部サービス】")
check("Claude API", _claude)
check("Supabase", _supabase)
check("Gmail送信", _gmail)
check("Yahoo Finance", _yahoo)
check("Saxo Bank", _saxo)
print("\n【データ】")
check("ローカル↔クラウド", _sync)

ng = [r for r in results if r[0] == NG]
warn = [r for r in results if r[0] == WARN]
print("\n" + "=" * 74)
if ng:
    print(f"  {NG} 要対応 {len(ng)}件: " + ", ".join(r[1] for r in ng))
elif warn:
    print(f"  {OK} 主要機能は正常（注意 {len(warn)}件: " + ", ".join(r[1] for r in warn) + "）")
else:
    print(f"  {OK} すべて正常")
print("=" * 74)
