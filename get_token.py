#!/usr/bin/env python3
"""
Saxo Bank SIM OAuth認証トークン取得スクリプト
実行するとブラウザが開き、ログイン後に .env へトークンを自動保存します
"""
import http.server
import threading
import webbrowser
import urllib.parse
import requests
import os
import re
from dotenv import load_dotenv

load_dotenv(override=True)

APP_KEY = os.getenv("SAXO_APP_KEY", "")
APP_SECRET = os.getenv("SAXO_APP_SECRET", "")
REDIRECT_URI = "http://localhost:8080/callback"
AUTH_URL = "https://sim.logonvalidation.net/authorize"
TOKEN_URL = "https://sim.logonvalidation.net/token"

auth_code = None
server_done = threading.Event()


class CallbackHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        global auth_code
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        if "code" in params:
            auth_code = params["code"][0]
            self.send_response(200)
            self.send_header("Content-type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"<h2>&#x8A8D;&#x8A3C;&#x6210;&#x529F;&#xFF01;&#x3053;&#x306E;&#x753B;&#x9762;&#x3092;&#x9589;&#x3058;&#x3066;&#x304F;&#x3060;&#x3055;&#x3044;&#x3002;</h2>")
        else:
            self.send_response(400)
            self.end_headers()
        server_done.set()

    def log_message(self, format, *args):
        pass


ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")


def save_to_env(key: str, value: str):
    env_path = ENV_PATH
    if not os.path.exists(env_path):
        with open(env_path, "w") as f:
            f.write("")

    with open(env_path, "r") as f:
        content = f.read()

    pattern = rf"^{key}=.*$"
    replacement = f"{key}={value}"
    if re.search(pattern, content, re.MULTILINE):
        content = re.sub(pattern, replacement, content, flags=re.MULTILINE)
    else:
        content += f"\n{key}={value}"

    with open(env_path, "w") as f:
        f.write(content)


def main():
    if not APP_KEY or not APP_SECRET:
        print("エラー: .env に SAXO_APP_KEY と SAXO_APP_SECRET を設定してください")
        return

    # ローカルサーバー起動
    server = http.server.HTTPServer(("localhost", 8080), CallbackHandler)
    thread = threading.Thread(target=server.serve_forever)
    thread.daemon = True
    thread.start()

    import time
    time.sleep(1)  # サーバー起動を待つ

    # 認証URLを生成してブラウザで開く
    params = urllib.parse.urlencode({
        "response_type": "code",
        "client_id": APP_KEY,
        "redirect_uri": REDIRECT_URI,
        "state": "saxo_sim_auth",
    })
    full_auth_url = f"{AUTH_URL}?{params}"
    print(f"ブラウザで認証画面を開きます...")
    webbrowser.open(full_auth_url)
    print("Saxo Bankにログインして認証を許可してください。")

    # コールバック待機
    server_done.wait(timeout=120)
    server.shutdown()

    if not auth_code:
        print("エラー: 認証コードを取得できませんでした（タイムアウト）")
        return

    # アクセストークン取得
    print("トークンを取得中...")
    resp = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": auth_code,
            "redirect_uri": REDIRECT_URI,
        },
        auth=(APP_KEY, APP_SECRET),
        timeout=15,
    )

    if resp.status_code not in (200, 201):
        print(f"エラー: トークン取得失敗 ({resp.status_code}): {resp.text}")
        return

    data = resp.json()
    access_token = data.get("access_token", "")
    refresh_token = data.get("refresh_token", "")

    # .env に保存
    save_to_env("SAXO_ACCESS_TOKEN", access_token)
    save_to_env("SAXO_REFRESH_TOKEN", refresh_token)

    print("✅ トークンを .env に保存しました！")
    print(f"   Access Token: {access_token[:20]}...")
    print(f"   Refresh Token: {refresh_token[:20]}...")
    print("\n次のコマンドでエージェントをテストできます:")
    print("   python agent.py --run-once")


if __name__ == "__main__":
    main()
