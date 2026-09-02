"""
SQLite → Supabase 同期

ローカルのSQLiteを正とし、Supabaseへミラーする。
・ローカルが常に高速に動く（ネット障害の影響を受けない）
・Supabaseはバックアップ＋スマホ/ブラウザからの閲覧用
毎日の引け後処理から呼ばれる。
"""
import os
import sqlite3
from datetime import datetime, date

from src import config

DB_PATH = "data/trading.db"
TABLES  = ["signals", "positions", "trades", "market_log"]

# SQLite側に残っている旧スキーマの列（Supabaseには送らない）
# trades.created_at は entry_date に置き換わっており、全行NULLのため除外する
EXCLUDE_COLUMNS = {
    "trades": {"created_at"},
}


def _client():
    """Supabaseクライアントを返す（未設定ならNone）"""
    url = os.getenv("SUPABASE_URL", "")
    key = os.getenv("SUPABASE_SERVICE_KEY", "")
    if not url or not key or "貼り付け" in key:
        return None
    try:
        from supabase import create_client
        return create_client(url, key)
    except Exception as e:
        print(f"  [WARN] Supabase接続失敗: {e}")
        return None


def _rows(table: str) -> list:
    """SQLiteから全行を辞書で取得（id列は除く＝Supabase側で採番）"""
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    try:
        cur.execute(f"SELECT * FROM {table}")
        drop = EXCLUDE_COLUMNS.get(table, set())
        out = []
        for r in cur.fetchall():
            d = dict(r)
            d.pop("id", None)
            for c in drop:
                d.pop(c, None)
            # datetime/date を ISO文字列に正規化
            for k, v in list(d.items()):
                if isinstance(v, (datetime, date)):
                    d[k] = v.isoformat()
                elif v == "":
                    d[k] = None
            out.append(d)
        return out
    finally:
        con.close()


def sync_all(verbose: bool = True) -> dict:
    """
    全テーブルをSupabaseへ同期する（洗い替え方式）。
    行数が少ない（年間数百行）ので、毎回truncate→全件挿入で十分。
    """
    sb = _client()
    if sb is None:
        if verbose:
            print("  [SKIP] Supabase未設定のため同期をスキップ")
        return {}

    result = {}
    for table in TABLES:
        try:
            rows = _rows(table)
            # 既存行を削除（id > 0 で全件対象）
            sb.table(table).delete().neq("id", 0).execute()
            # 500件ずつ挿入
            for i in range(0, len(rows), 500):
                chunk = rows[i:i + 500]
                if chunk:
                    sb.table(table).insert(chunk).execute()
            result[table] = len(rows)
            if verbose:
                print(f"  ✅ {table:12} {len(rows):>4}行を同期")
        except Exception as e:
            result[table] = -1
            if verbose:
                print(f"  ❌ {table:12} 同期失敗: {str(e)[:90]}")
    return result


def fetch_summary() -> dict:
    """Supabase側の成績サマリービューを読む（動作確認用）"""
    sb = _client()
    if sb is None:
        return {}
    try:
        r = sb.table("performance_summary").select("*").execute()
        return r.data[0] if r.data else {}
    except Exception as e:
        print(f"  [WARN] サマリー取得失敗: {e}")
        return {}
