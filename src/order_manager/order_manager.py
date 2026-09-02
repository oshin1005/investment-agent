from src.market_data.auth import SaxoAuth
from src.signal_engine.signal_generator import TradingSignal
from src import config


class OrderManager:
    """Saxo Bank API経由の注文管理"""

    def __init__(self, auth: SaxoAuth):
        self.auth             = auth
        self._account_key: str = ""
        self._last_asset_type: str = "CfdOnStock"  # UIC検索で確認した実際のAssetType

    # ──────────────────────────────
    # アカウント情報
    # ──────────────────────────────
    def get_account_key(self) -> str:
        if self._account_key:
            return self._account_key
        resp = self.auth.make_request("GET", "/port/v1/accounts/me")
        accounts = resp.json().get("Data", [])
        if accounts:
            self._account_key = accounts[0].get("AccountKey", "")
        return self._account_key

    def get_account_equity(self) -> float:
        """口座の純資産額を取得"""
        try:
            resp = self.auth.make_request("GET", "/port/v1/balances/me")
            data = resp.json()
            return float(data.get("TotalValue", data.get("NetEquityForMargin", 0)))
        except Exception as e:
            print(f"[WARN] 口座資産取得失敗: {e}")
            return 0.0

    # ──────────────────────────────
    # 銘柄UIC検索
    # ──────────────────────────────
    def get_uic(self, ticker_code: str) -> "int | None":
        """日本株ティッカーコード → Saxo UIC変換（CfdOnStock優先）"""
        # デモ/SIM口座では日本株はCFD形式で取引可能
        for asset_type in ("CfdOnStock", "Stock"):
            try:
                resp = self.auth.make_request(
                    "GET",
                    "/ref/v1/instruments",
                    params={
                        "Keywords":   ticker_code,
                        "AssetTypes": asset_type,
                        "ExchangeId": "TYO",
                        "$top":       5,
                    },
                )
                data = resp.json().get("Data", [])
                for item in data:
                    symbol = item.get("Symbol", "")
                    # "7203:xtks" or "7203" 形式に対応
                    if symbol.startswith(ticker_code):
                        self._last_asset_type = asset_type
                        return item.get("Identifier")
            except Exception as e:
                print(f"[WARN] UIC取得失敗 {ticker_code} ({asset_type}): {e}")
        return None

    # ──────────────────────────────
    # ポジションサイズ計算
    # ──────────────────────────────
    def calc_quantity(self, equity: float, entry_price: float, lot_size: int = 100) -> int:
        """1ポジションの株数を計算（日本株は100株単位）"""
        if equity <= 0 or entry_price <= 0:
            return 0
        position_value = equity * (config.MAX_POSITION_RATIO_PCT / 100)
        qty = int(position_value / entry_price)
        # 日本株は100株単位に切り捨て
        qty = (qty // lot_size) * lot_size
        return max(qty, lot_size)

    # ──────────────────────────────
    # 注文構築
    # ──────────────────────────────
    def _limit_order(self, uic: int, direction: str, price: float, qty: int, account_key: str) -> dict:
        return {
            "Uic":        uic,
            "AssetType":  self._last_asset_type,
            "BuySell":    direction,
            "Amount":     qty,
            "OrderType":  "Limit",
            "OrderPrice": round(price, 1),
            "OrderDuration": {"DurationType": "DayOrder"},
            "AccountKey": account_key,
            "ManualOrder": False,
        }

    def _stop_order(self, uic: int, direction: str, stop_price: float, qty: int, account_key: str) -> dict:
        return {
            "Uic":        uic,
            "AssetType":  self._last_asset_type,
            "BuySell":    direction,
            "Amount":     qty,
            "OrderType":  "StopIfTraded",
            "OrderPrice": round(stop_price, 1),
            "OrderDuration": {"DurationType": "GoodTillCancel"},
            "AccountKey":  account_key,
            "ManualOrder": False,
        }

    # ──────────────────────────────
    # 注文実行
    # ──────────────────────────────
    def place_order(self, signal: TradingSignal) -> "dict | None":
        """
        シグナルに基づき指値+逆指値を発注。
        SIMモードのみ自動実行。本番はユーザー承認後に呼ぶ。
        """
        if config.SAXO_ENV != "sim":
            raise RuntimeError("本番執行はユーザーの明示的許可が必要です")

        if "BUY" not in signal.signal:
            return None

        uic = self.get_uic(signal.ticker)
        if uic is None:
            print(f"[WARN] {signal.ticker}: UIC取得できず注文スキップ")
            return None

        equity  = self.get_account_equity()
        qty     = self.calc_quantity(equity, signal.entry_price)
        acc_key = self.get_account_key()
        if not acc_key:
            print("[WARN] AccountKey取得できず注文スキップ")
            return None

        # エントリー + 損切りをIfDone（関連注文）で一括送信
        entry_payload = self._limit_order(uic, "Buy", signal.entry_price, qty, acc_key)
        if signal.stop_loss:
            stop_part = self._stop_order(uic, "Sell", signal.stop_loss, qty, acc_key)
            entry_payload["Orders"] = [stop_part]  # 約定後に損切りを自動発動

        resp = self.auth.make_request("POST", "/trade/v2/orders", json=entry_payload)
        order_data = resp.json()
        order_id   = order_data.get("OrderId", "")

        print(
            f"[ORDER] {signal.name}({signal.ticker}) {signal.signal} "
            f"UIC={uic} qty={qty} entry={signal.entry_price} stop={signal.stop_loss}"
        )
        return order_data

    def cancel_order(self, order_id: str) -> bool:
        try:
            self.auth.make_request("DELETE", f"/trade/v2/orders/{order_id}")
            return True
        except Exception:
            return False

    def get_positions(self) -> list:
        try:
            resp = self.auth.make_request("GET", "/port/v1/positions/me")
            return resp.json().get("Data", [])
        except Exception:
            return []

    def emergency_stop(self) -> None:
        """緊急停止: 全注文キャンセル"""
        positions = self.get_positions()
        print(f"[EMERGENCY] {len(positions)}件のポジションを確認。新規注文を停止します。")
