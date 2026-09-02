#!/usr/bin/env python3
"""
Saxo SIM接続テスト
使い方: python3 test_saxo.py
"""
from dotenv import load_dotenv
load_dotenv(override=True)

from src.market_data.auth import SaxoAuth
from src.order_manager.order_manager import OrderManager
from src import config


def test_connection():
    print(f"\n{'='*50}")
    print(f"  Saxo SIM 接続テスト (ENV={config.SAXO_ENV})")
    print(f"{'='*50}\n")

    if not config.SAXO_ACCESS_TOKEN or config.SAXO_ACCESS_TOKEN == "your_access_token":
        print("❌ アクセストークン未設定")
        print("   先に get_token.py を実行してください:")
        print("   python3 get_token.py\n")
        return False

    auth    = SaxoAuth()
    manager = OrderManager(auth)

    # 1. アカウント情報
    print("[1] アカウント情報取得...")
    try:
        acc_key = manager.get_account_key()
        equity  = manager.get_account_equity()
        print(f"   AccountKey: {acc_key[:20] if acc_key else '取得失敗'}...")
        print(f"   口座資産: ¥{equity:,.0f}")
    except Exception as e:
        print(f"   ❌ 失敗: {e}")
        if "401" in str(e):
            print("   → トークン期限切れ。python3 get_token.py を再実行してください")
        return False

    # 2. 銘柄UIC検索
    print("\n[2] 銘柄UIC検索テスト (トヨタ 7203 / ファナック 6954)...")
    for ticker in ["7203", "6954", "8306"]:
        try:
            uic = manager.get_uic(ticker)
            if uic:
                print(f"   ✅ {ticker}: UIC={uic} ({manager._last_asset_type})")
            else:
                print(f"   ⚠️ {ticker}: UIC未発見")
        except Exception as e:
            print(f"   ❌ {ticker}: {e}")

    # 3. ポジション確認
    print("\n[3] 現在のポジション確認...")
    try:
        positions = manager.get_positions()
        if positions:
            print(f"   {len(positions)}件のポジション")
            for p in positions[:3]:
                print(f"   - {p}")
        else:
            print("   ポジションなし（クリーン状態）")
    except Exception as e:
        print(f"   ❌ 失敗: {e}")

    print(f"\n{'='*50}")
    print("  テスト完了")
    print(f"{'='*50}\n")
    return True


if __name__ == "__main__":
    test_connection()
