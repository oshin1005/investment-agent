import os
import requests
import backoff
from src import config

SAXO_TOKEN_URLS = {
    "sim":  "https://sim.logonvalidation.net/token",
    "live": "https://live.logonvalidation.net/token",
}
ENV_FILE = os.path.join(os.path.dirname(__file__), "..", "..", ".env")


def _update_env_token(key: str, value: str) -> None:
    """Update a key in .env without rewriting unrelated lines."""
    try:
        env_path = os.path.abspath(ENV_FILE)
        with open(env_path) as f:
            lines = f.readlines()
        updated = False
        for i, line in enumerate(lines):
            if line.startswith(f"{key}="):
                lines[i] = f"{key}={value}\n"
                updated = True
                break
        if not updated:
            lines.append(f"{key}={value}\n")
        with open(env_path, "w") as f:
            f.writelines(lines)
    except Exception as e:
        print(f"[WARN] .envトークン保存失敗: {e}")


class SaxoAuth:
    """Saxo Bank OAuth 2.0トークン管理（自動リフレッシュ対応）"""

    def __init__(self):
        self.access_token  = config.SAXO_ACCESS_TOKEN
        self.refresh_token = config.SAXO_REFRESH_TOKEN
        self._env          = config.SAXO_ENV  # "sim" or "live"
        self._token_url    = SAXO_TOKEN_URLS.get(self._env, SAXO_TOKEN_URLS["sim"])

    def get_headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

    def is_token_valid(self) -> bool:
        """アクセストークンが未設定・期限切れでないかを事前チェック"""
        import base64, json, time
        token = self.access_token
        if not token or token in ("your_access_token", ""):
            return False
        try:
            parts = token.split(".")
            if len(parts) < 2:
                return False
            padded = parts[1] + "=" * (4 - len(parts[1]) % 4)
            payload = json.loads(base64.urlsafe_b64decode(padded))
            return int(payload.get("exp", 0)) > time.time()
        except Exception:
            return False

    @backoff.on_exception(backoff.expo, requests.exceptions.RequestException, max_tries=5)
    def refresh_access_token(self) -> bool:
        payload = {
            "grant_type":    "refresh_token",
            "refresh_token": self.refresh_token,
            "client_id":     config.SAXO_APP_KEY,
            "client_secret": config.SAXO_APP_SECRET,
        }
        try:
            resp = requests.post(self._token_url, data=payload, timeout=10)
        except requests.exceptions.RequestException:
            return False
        if resp.status_code == 200:
            data = resp.json()
            self.access_token  = data["access_token"]
            self.refresh_token = data.get("refresh_token", self.refresh_token)
            # .envへ永続化
            _update_env_token("SAXO_ACCESS_TOKEN",  self.access_token)
            _update_env_token("SAXO_REFRESH_TOKEN", self.refresh_token)
            print("[INFO] Saxoトークンを自動更新・.envに保存しました")
            return True
        print(f"[WARN] トークンリフレッシュ失敗: {resp.status_code} {resp.text[:100]}")
        return False

    def make_request(self, method: str, endpoint: str, **kwargs) -> requests.Response:
        url  = f"{config.SAXO_BASE_URL}{endpoint}"
        resp = requests.request(method, url, headers=self.get_headers(), timeout=30, **kwargs)
        if resp.status_code == 401:
            if self.refresh_access_token():
                resp = requests.request(method, url, headers=self.get_headers(), timeout=30, **kwargs)
        resp.raise_for_status()
        return resp
