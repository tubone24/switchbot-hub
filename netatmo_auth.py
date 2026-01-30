#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Netatmo OAuth2 Authorization Helper

このスクリプトは、Netatmo APIのリフレッシュトークンを取得するための
対話式ヘルパーです。

使い方:
    python netatmo_auth.py

必要な情報（事前にNetatmo Developer Portalで取得）:
    - Client ID
    - Client Secret

参考: https://dev.netatmo.com/apidocumentation/oauth
"""
import sys
import json
import webbrowser
import http.server
import socketserver
import threading
import urllib.parse
import requests


# ローカルサーバーでコールバックを受け取るためのポート
CALLBACK_PORT = 9876
CALLBACK_PATH = "/callback"
REDIRECT_URI = "http://localhost:{port}{path}".format(port=CALLBACK_PORT, path=CALLBACK_PATH)

# Netatmo OAuth2 エンドポイント
AUTH_URL = "https://api.netatmo.com/oauth2/authorize"
TOKEN_URL = "https://api.netatmo.com/oauth2/token"

# 取得するスコープ（Weather Station読み取り権限）
SCOPES = "read_station"


class CallbackHandler(http.server.BaseHTTPRequestHandler):
    """OAuth2コールバックを処理するHTTPハンドラー"""

    authorization_code = None
    error = None

    def do_GET(self):
        """GETリクエストを処理"""
        parsed = urllib.parse.urlparse(self.path)

        if parsed.path == CALLBACK_PATH:
            query = urllib.parse.parse_qs(parsed.query)

            if 'code' in query:
                CallbackHandler.authorization_code = query['code'][0]
                self.send_response(200)
                self.send_header('Content-type', 'text/html; charset=utf-8')
                self.end_headers()
                response = """
                <html>
                <head><title>認証成功</title></head>
                <body style="font-family: sans-serif; text-align: center; padding-top: 50px;">
                    <h1 style="color: green;">認証成功!</h1>
                    <p>このウィンドウを閉じて、ターミナルに戻ってください。</p>
                </body>
                </html>
                """
                self.wfile.write(response.encode('utf-8'))
            elif 'error' in query:
                CallbackHandler.error = query.get('error_description', query['error'])[0]
                self.send_response(400)
                self.send_header('Content-type', 'text/html; charset=utf-8')
                self.end_headers()
                response = """
                <html>
                <head><title>認証エラー</title></head>
                <body style="font-family: sans-serif; text-align: center; padding-top: 50px;">
                    <h1 style="color: red;">認証エラー</h1>
                    <p>{error}</p>
                </body>
                </html>
                """.format(error=CallbackHandler.error)
                self.wfile.write(response.encode('utf-8'))
            else:
                self.send_response(400)
                self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        """ログを抑制"""
        pass


def get_authorization_url(client_id, state="netatmo_auth"):
    """認可URLを生成"""
    params = {
        'client_id': client_id,
        'redirect_uri': REDIRECT_URI,
        'scope': SCOPES,
        'state': state,
    }
    return AUTH_URL + "?" + urllib.parse.urlencode(params)


def exchange_code_for_tokens(client_id, client_secret, authorization_code):
    """認可コードをトークンに交換"""
    payload = {
        'grant_type': 'authorization_code',
        'client_id': client_id,
        'client_secret': client_secret,
        'code': authorization_code,
        'redirect_uri': REDIRECT_URI,
        'scope': SCOPES,
    }

    headers = {
        'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8'
    }

    response = requests.post(TOKEN_URL, data=payload, headers=headers, timeout=30)

    if response.status_code != 200:
        raise Exception("Token exchange failed: {} - {}".format(
            response.status_code, response.text
        ))

    return response.json()


def start_callback_server():
    """コールバック用の一時HTTPサーバーを起動"""
    handler = CallbackHandler

    # SO_REUSEADDR を設定
    socketserver.TCPServer.allow_reuse_address = True

    server = socketserver.TCPServer(("", CALLBACK_PORT), handler)

    # タイムアウト設定
    server.timeout = 300  # 5分

    return server


def wait_for_callback(server):
    """コールバックを待機"""
    CallbackHandler.authorization_code = None
    CallbackHandler.error = None

    # 1リクエストだけ処理
    server.handle_request()

    return CallbackHandler.authorization_code, CallbackHandler.error


def save_credentials(client_id, client_secret, refresh_token, filepath):
    """認証情報をファイルに保存"""
    credentials = {
        'client_id': client_id,
        'client_secret': client_secret,
        'refresh_token': refresh_token
    }

    with open(filepath, 'w') as f:
        json.dump(credentials, f, indent=2)


def main():
    """メイン処理"""
    print("=" * 60)
    print("Netatmo OAuth2 認証ヘルパー")
    print("=" * 60)
    print()
    print("このスクリプトは、Netatmo APIのリフレッシュトークンを取得します。")
    print()
    print("事前準備:")
    print("  1. https://dev.netatmo.com/ にアクセス")
    print("  2. 「My Apps」からアプリを作成（まだの場合）")
    print("  3. Client ID と Client Secret を取得")
    print()

    # Client ID の入力
    client_id = input("Client ID を入力: ").strip()
    if not client_id:
        print("エラー: Client ID が必要です")
        sys.exit(1)

    # Client Secret の入力
    client_secret = input("Client Secret を入力: ").strip()
    if not client_secret:
        print("エラー: Client Secret が必要です")
        sys.exit(1)

    print()
    print("-" * 60)
    print("ステップ 1: ブラウザで認証")
    print("-" * 60)

    # コールバックサーバーを起動
    print()
    print("コールバックサーバーを起動中 (port {})...".format(CALLBACK_PORT))

    try:
        server = start_callback_server()
    except OSError as e:
        print("エラー: ポート {} が使用中です。".format(CALLBACK_PORT))
        print("       他のプロセスを終了してから再試行してください。")
        sys.exit(1)

    # 認可URLを生成
    auth_url = get_authorization_url(client_id)

    print()
    print("ブラウザで以下のURLを開きます...")
    print()
    print("  {}".format(auth_url))
    print()

    # ブラウザを自動で開く
    try:
        webbrowser.open(auth_url)
        print("（ブラウザが自動で開かない場合は、上記URLを手動でコピーしてください）")
    except Exception:
        print("ブラウザを自動で開けませんでした。上記URLを手動で開いてください。")

    print()
    print("ブラウザで Netatmo にログインし、アクセスを許可してください...")
    print("（最大5分間待機します）")
    print()

    # コールバックを待機
    authorization_code, error = wait_for_callback(server)
    server.server_close()

    if error:
        print("エラー: {}".format(error))
        sys.exit(1)

    if not authorization_code:
        print("エラー: 認可コードを取得できませんでした（タイムアウト）")
        sys.exit(1)

    print("認可コードを取得しました!")
    print()
    print("-" * 60)
    print("ステップ 2: トークンの取得")
    print("-" * 60)
    print()

    try:
        tokens = exchange_code_for_tokens(client_id, client_secret, authorization_code)
    except Exception as e:
        print("エラー: {}".format(e))
        sys.exit(1)

    access_token = tokens.get('access_token')
    refresh_token = tokens.get('refresh_token')
    expires_in = tokens.get('expires_in', 10800)

    if not refresh_token:
        print("エラー: リフレッシュトークンが取得できませんでした")
        print("レスポンス: {}".format(json.dumps(tokens, indent=2)))
        sys.exit(1)

    print("トークン取得成功!")
    print()
    print("-" * 60)
    print("結果")
    print("-" * 60)
    print()
    print("Access Token:  {}...（{}秒で期限切れ）".format(
        access_token[:20] if access_token else "N/A",
        expires_in
    ))
    print()
    print("Refresh Token: {}".format(refresh_token))
    print()

    # 認証情報の保存
    print("-" * 60)
    print("認証情報の保存")
    print("-" * 60)
    print()

    save_choice = input("認証情報をファイルに保存しますか? (y/N): ").strip().lower()

    if save_choice == 'y':
        default_path = "netatmo_credentials.json"
        filepath = input("保存先ファイルパス [{}]: ".format(default_path)).strip()
        if not filepath:
            filepath = default_path

        try:
            save_credentials(client_id, client_secret, refresh_token, filepath)
            print()
            print("保存しました: {}".format(filepath))
        except Exception as e:
            print("保存エラー: {}".format(e))

    print()
    print("=" * 60)
    print("config.json に以下を追加してください:")
    print("=" * 60)
    print()
    print(json.dumps({
        "netatmo": {
            "enabled": True,
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "credentials_file": None,
            "interval_seconds": 600
        }
    }, indent=4, ensure_ascii=False))
    print()
    print("完了!")


if __name__ == '__main__':
    main()
