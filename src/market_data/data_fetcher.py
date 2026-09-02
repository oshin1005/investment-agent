import pandas as pd
from datetime import datetime, timedelta
from typing import Optional
from src.market_data.auth import SaxoAuth
from src import config


class MarketDataFetcher:
    """Saxo Bank APIから日本株OHLCVデータを取得"""

    def __init__(self, auth: SaxoAuth):
        self.auth = auth

    def get_nikkei225_list(self) -> list[dict]:
        """日経225銘柄リストをSaxo Bank APIから取得"""
        resp = self.auth.make_request(
            "GET",
            "/ref/v1/instruments",
            params={
                "AssetTypes": "Stock",
                "ExchangeId": "XJPX",
                "Tags": "Nikkei225",
                "FieldGroups": "SummaryType",
                "$top": 250,
            },
        )
        data = resp.json()
        return data.get("Data", [])

    def get_ohlcv(self, uic: int, horizon: int = 60, count: int = 100) -> Optional[pd.DataFrame]:
        """
        1時間足OHLCVデータを取得
        uic: Saxo Bank UIC（銘柄コード）
        horizon: 60分足
        count: 取得本数
        """
        resp = self.auth.make_request(
            "GET",
            "/chart/v1/charts",
            params={
                "AssetType": "Stock",
                "Uic": uic,
                "Horizon": horizon,
                "Count": count,
                "Mode": "UpTo",
            },
        )
        data = resp.json()
        raw = data.get("Data", [])
        if not raw:
            return None

        df = pd.DataFrame(raw)
        df["Time"] = pd.to_datetime(df["Time"])
        df = df.rename(columns={
            "OpenAsk": "Open",
            "HighAsk": "High",
            "LowAsk": "Low",
            "CloseAsk": "Close",
            "Volume": "Volume",
        })
        return df[["Time", "Open", "High", "Low", "Close", "Volume"]].set_index("Time")

    def get_current_price(self, uic: int) -> Optional[float]:
        """現在値を取得"""
        resp = self.auth.make_request(
            "GET",
            f"/trade/v1/prices/subscriptions",
            params={"AssetType": "Stock", "Uic": uic},
        )
        data = resp.json()
        return data.get("LastTraded", {}).get("Price")

    def get_account_info(self) -> dict:
        """口座残高・ポジション情報を取得"""
        resp = self.auth.make_request("GET", "/port/v1/accounts/me")
        return resp.json()
