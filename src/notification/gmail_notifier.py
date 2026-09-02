import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from src import config
from src.signal_engine.signal_generator import TradingSignal


def _build_html_report(signals: list[TradingSignal], account_value: float, drawdown_pct: float) -> str:
    rows = ""
    for s in signals:
        color = "#28a745" if "BUY" in s.signal else "#dc3545" if "SELL" in s.signal else "#6c757d"
        rows += (
            f"<tr>"
            f"<td>{s.name}({s.ticker})</td>"
            f"<td style='color:{color}'><b>{s.signal}</b></td>"
            f"<td>{s.confidence}</td>"
            f"<td>¥{s.entry_price:,.0f}</td>"
            f"<td>¥{s.target_price:,.0f}({s.target_pct:+.1f}%)</td>"
            f"<td>¥{s.stop_loss:,.0f}({s.stop_loss_pct:.1f}%)</td>"
            f"</tr>"
        )
    return f"""
<html><body>
<h2>📊 日次トレーディングレポート</h2>
<p>口座評価額: <b>¥{account_value:,.0f}</b> | ドローダウン: <b>{drawdown_pct:.1f}%</b></p>
<table border="1" cellpadding="5" style="border-collapse:collapse;width:100%">
<tr style="background:#343a40;color:white">
<th>銘柄</th><th>シグナル</th><th>信頼度</th>
<th>現在値</th><th>目標</th><th>損切り</th>
</tr>
{rows}
</table>
<p style="color:#6c757d;font-size:12px">
※本レポートは投資助言ではありません。最終判断はご自身でお願いします。
</p>
</body></html>
"""


class GmailNotifier:
    """Gmail SMTP経由の通知（LINEのフォールバック）"""

    SMTP_HOST = "smtp.gmail.com"
    SMTP_PORT = 587

    def __init__(self):
        self.address = config.GMAIL_ADDRESS
        self.password = config.GMAIL_APP_PASSWORD

    def _send(self, subject: str, body: str, html: bool = False) -> bool:
        if not self.address or not self.password:
            print("[WARN] Gmail未設定、通知をスキップ")
            return False
        try:
            msg = MIMEMultipart("alternative")
            msg["From"] = self.address
            msg["To"] = self.address
            msg["Subject"] = subject
            content_type = "html" if html else "plain"
            msg.attach(MIMEText(body, content_type, "utf-8"))

            with smtplib.SMTP(self.SMTP_HOST, self.SMTP_PORT, timeout=10) as server:
                server.starttls()
                server.login(self.address, self.password)
                server.send_message(msg)
            return True
        except Exception as e:
            print(f"[ERROR] Gmail送信失敗: {e}")
            return False

    def send_signal(self, signal: TradingSignal) -> bool:
        subject = f"[{signal.signal}] {signal.name}({signal.ticker}) 信頼度:{signal.confidence}"
        body = (
            f"シグナル: {signal.signal}\n"
            f"銘柄: {signal.name} ({signal.ticker})\n"
            f"信頼度: {signal.confidence}/100\n"
            f"推奨エントリー: ¥{signal.entry_price:,.0f}\n"
            f"目標価格: ¥{signal.target_price:,.0f} ({signal.target_pct:+.1f}%)\n"
            f"損切り: ¥{signal.stop_loss:,.0f} ({signal.stop_loss_pct:.1f}%)\n\n"
            f"根拠:\n{signal.reasoning}"
        )
        return self._send(subject, body)

    def send_daily_report(self, signals: list[TradingSignal], account_value: float, drawdown_pct: float) -> bool:
        subject = f"[日次レポート] 口座: ¥{account_value:,.0f} | DD: {drawdown_pct:.1f}%"
        html = _build_html_report(signals, account_value, drawdown_pct)
        return self._send(subject, html, html=True)

    def send_alert(self, message: str) -> bool:
        return self._send("[緊急アラート] AI自動売買エージェント", message)

    def send_paper_report(self, summary: dict, closed_today: list, open_positions: list) -> bool:
        """ペーパートレードの日次成績レポート"""
        if not summary.get("trades"):
            subject = "[ペーパートレード] 保有 {}件 / 決済実績なし".format(summary.get("open", 0))
        else:
            subject = (f"[ペーパートレード] 累計 {summary['total_pct']:+.1f}% "
                       f"勝率{summary['win_rate']:.0f}% 保有{summary['open']}件")
        html = _build_paper_html(summary, closed_today, open_positions)
        return self._send(subject, html, html=True)


def _build_paper_html(summary: dict, closed_today: list, open_positions: list) -> str:
    if not summary.get("trades"):
        stats = "<p>まだ決済済みの取引がありません。</p>"
    else:
        pf = f"{summary['pf']:.2f}" if summary["pf"] != float("inf") else "∞"
        color = "#28a745" if summary["total_pct"] > 0 else "#dc3545"
        stats = f"""
<table border="0" cellpadding="10" style="border-collapse:collapse;background:#f8f9fa;width:100%">
<tr>
  <td><b>決済数</b><br>{summary['trades']}件</td>
  <td><b>勝率</b><br>{summary['win_rate']:.1f}%</td>
  <td><b>平均損益</b><br>{summary['avg_pct']:+.2f}%</td>
  <td><b>累計損益</b><br><span style="color:{color};font-size:18px"><b>{summary['total_pct']:+.1f}%</b></span></td>
  <td><b>PF</b><br>{pf}</td>
</tr>
<tr>
  <td colspan="5">実現損益 <b>¥{summary['total_pnl']:+,.0f}</b> ／
      保有中 {summary['open']}件（含み損益 ¥{summary.get('unrealized', 0):+,.0f}）</td>
</tr>
</table>"""

    closed_rows = ""
    for t in closed_today:
        c = "#28a745" if (t.pnl_pct or 0) > 0 else "#dc3545"
        closed_rows += (f"<tr><td>{t.name}({t.ticker})</td>"
                        f"<td>{t.exit_reason}</td>"
                        f"<td style='color:{c}'><b>{t.pnl_pct:+.2f}%</b></td>"
                        f"<td>¥{t.pnl:+,.0f}</td><td>{t.holding_days}日</td></tr>")
    closed_html = f"""
<h3>本日の決済</h3>
<table border="1" cellpadding="6" style="border-collapse:collapse;width:100%">
<tr style="background:#343a40;color:white"><th>銘柄</th><th>理由</th><th>損益率</th><th>損益</th><th>保有</th></tr>
{closed_rows}</table>""" if closed_rows else ""

    open_rows = ""
    for p in open_positions:
        pct = p.unrealized_pnl_pct or 0
        c = "#28a745" if pct > 0 else "#dc3545"
        open_rows += (f"<tr><td>{p.name}({p.ticker})</td>"
                      f"<td>¥{p.entry_price:,.0f}</td>"
                      f"<td>¥{p.current_price or 0:,.0f}</td>"
                      f"<td style='color:{c}'><b>{pct:+.2f}%</b></td>"
                      f"<td>¥{p.target_price:,.0f}</td><td>¥{p.stop_loss:,.0f}</td></tr>")
    open_html = f"""
<h3>保有中のポジション</h3>
<table border="1" cellpadding="6" style="border-collapse:collapse;width:100%">
<tr style="background:#343a40;color:white"><th>銘柄</th><th>取得</th><th>現在</th><th>含み</th><th>目標</th><th>損切</th></tr>
{open_rows}</table>""" if open_rows else "<p>保有中のポジションはありません。</p>"

    return f"""
<html><body style="font-family:sans-serif">
<h2>📈 ペーパートレード日次レポート</h2>
{stats}
{closed_html}
{open_html}
<p style="color:#6c757d;font-size:12px">
※Yahoo Financeの実株価に基づく仮想売買の記録です。実際の約定・スリッページ・手数料は考慮していません。<br>
※本レポートは投資助言ではありません。最終判断はご自身でお願いします。
</p>
</body></html>
"""
