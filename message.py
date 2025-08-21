import requests
import json
import os

SAVE_FILE = "E:/フォートナイト/Picture/Loot Pool/TEST4/Hotfix/tokens.json"  # 保存先ファイル

def save_tokens(tokens: dict):
    """トークンをファイルに保存"""
    try:
        with open(SAVE_FILE, "w", encoding="utf-8") as f:
            json.dump(tokens, f, ensure_ascii=False, indent=2)
        print(f"トークンを {os.path.abspath(SAVE_FILE)} に保存しました")
    except Exception as e:
        print(f"トークン保存エラー: {e}")

def token_client():
    auth_token = "M2Y2OWU1NmM3NjQ5NDkyYzhjYzI5ZjFhZjA4YThhMTI6YjUxZWU5Y2IxMjIzNGY1MGE2OWVmYTY3ZWY1MzgxMmU="
    print("token_client: リクエストの準備を開始します")
    try:
        url = "https://account-public-service-prod.ol.epicgames.com/account/api/oauth/token"
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": f"Basic {auth_token}"
        }
        data = {
            "grant_type": "client_credentials"
        }
        print(f"token_client: リクエストを送信します\nURL: {url}\nヘッダー: {headers}\nデータ: {data}")
        response = requests.post(url, headers=headers, data=data)
        print(f"token_client: サーバーからの応答を受信しました\nステータスコード: {response.status_code}")
        response_json = response.json()
        print("token_client: レスポンス (JSON整形出力):\n" + json.dumps(response_json, indent=4, ensure_ascii=False))
        if response.status_code != 200:
            print(f"token_client: エラー - ステータスコード: {response.status_code}, 理由: {response.reason}")
            return None
        return response_json.get("access_token")
    except Exception as e:
        print(f"token_client: エラーが発生しました: {e}")
        return None
if __name__ == "__main__":
    print("メイン処理: 各トークンの取得を開始します")
    client_token = token_client()
    tokens = {
        "client_token": client_token,
    }
    save_tokens(tokens)

    print("\nメイン処理: 全てのトークン取得が完了しました")
    print(f"クライアントトークン: {client_token if client_token else '取得失敗'}")
    print("メイン処理: 全ての処理が終了しました")