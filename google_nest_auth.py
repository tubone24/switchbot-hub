#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Google Nest Device Access OAuth2 authentication helper.

This script helps you obtain the refresh_token needed for the Google Nest API.

Prerequisites:
1. Register for Device Access ($5 one-time fee)
   https://developers.google.com/nest/device-access/registration
2. Create a Google Cloud Project and enable SDM API
3. Create OAuth 2.0 Client ID (Web application type)
4. Add http://localhost:8888 to Authorized redirect URIs
5. Note your Device Access Project ID (UUID)

Usage:
    python google_nest_auth.py
"""
import json
import sys
import webbrowser
import socket
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlencode, urlparse, parse_qs
import threading

import requests


class OAuthCallbackHandler(BaseHTTPRequestHandler):
    """Handle OAuth callback and extract authorization code."""

    authorization_code = None

    def do_GET(self):
        """Handle GET request from OAuth redirect."""
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        if 'code' in params:
            OAuthCallbackHandler.authorization_code = params['code'][0]
            self.send_response(200)
            self.send_header('Content-type', 'text/html; charset=utf-8')
            self.end_headers()
            response = """
            <html>
            <head><title>認証成功</title></head>
            <body style="font-family: sans-serif; text-align: center; padding-top: 50px;">
                <h1>認証成功!</h1>
                <p>このウィンドウを閉じて、ターミナルに戻ってください。</p>
            </body>
            </html>
            """
            self.wfile.write(response.encode('utf-8'))
        elif 'error' in params:
            error = params.get('error', ['unknown'])[0]
            error_desc = params.get('error_description', ['No description'])[0]
            self.send_response(400)
            self.send_header('Content-type', 'text/html; charset=utf-8')
            self.end_headers()
            response = """
            <html>
            <head><title>認証エラー</title></head>
            <body style="font-family: sans-serif; text-align: center; padding-top: 50px;">
                <h1>認証エラー</h1>
                <p>エラー: {}</p>
                <p>{}</p>
            </body>
            </html>
            """.format(error, error_desc)
            self.wfile.write(response.encode('utf-8'))
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        """Suppress HTTP server logs."""
        pass


def find_free_port():
    """Find a free port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('', 0))
        return s.getsockname()[1]


def get_authorization_url(project_id, client_id, redirect_uri):
    """Generate the authorization URL for Google Nest Device Access."""
    base_url = "https://nestservices.google.com/partnerconnections/{}/auth".format(project_id)

    # Scopes: SDM API for device access, Pub/Sub for real-time events
    scopes = ' '.join([
        'https://www.googleapis.com/auth/sdm.service',
        'https://www.googleapis.com/auth/pubsub'
    ])

    params = {
        'redirect_uri': redirect_uri,
        'client_id': client_id,
        'access_type': 'offline',
        'prompt': 'consent',
        'response_type': 'code',
        'scope': scopes
    }

    return "{}?{}".format(base_url, urlencode(params))


def exchange_code_for_tokens(client_id, client_secret, code, redirect_uri):
    """Exchange authorization code for access and refresh tokens."""
    token_url = "https://oauth2.googleapis.com/token"

    data = {
        'client_id': client_id,
        'client_secret': client_secret,
        'code': code,
        'grant_type': 'authorization_code',
        'redirect_uri': redirect_uri
    }

    response = requests.post(token_url, data=data, timeout=30)
    response.raise_for_status()
    return response.json()


def main():
    print("=" * 60)
    print("Google Nest Device Access - OAuth2 Setup Helper")
    print("=" * 60)
    print()

    print("事前準備の確認:")
    print("1. Device Access に登録済み ($5)")
    print("2. Google Cloud で SDM API を有効化済み")
    print("3. OAuth 2.0 Client ID を作成済み (Web application タイプ)")
    print("4. Authorized redirect URIs に http://localhost:8888 を追加済み")
    print()

    # Get credentials from user
    project_id = input("Device Access Project ID (UUID): ").strip()
    if not project_id:
        print("Error: Project ID is required")
        sys.exit(1)

    client_id = input("OAuth2 Client ID: ").strip()
    if not client_id:
        print("Error: Client ID is required")
        sys.exit(1)

    client_secret = input("OAuth2 Client Secret: ").strip()
    if not client_secret:
        print("Error: Client Secret is required")
        sys.exit(1)

    # Use localhost redirect
    port = 8888
    redirect_uri = "http://localhost:{}".format(port)

    print()
    print("=" * 60)
    print("重要: Google Cloud Console で以下を設定してください")
    print("=" * 60)
    print()
    print("Authorized redirect URIs に追加:")
    print("  {}".format(redirect_uri))
    print()
    input("設定が完了したら Enter を押してください...")

    # Start local server
    print()
    print("ローカルサーバーを起動中 (port {})...".format(port))

    server = HTTPServer(('localhost', port), OAuthCallbackHandler)
    server_thread = threading.Thread(target=server.handle_request)
    server_thread.start()

    # Generate authorization URL
    auth_url = get_authorization_url(project_id, client_id, redirect_uri)

    print()
    print("ブラウザで認証ページを開きます...")
    print("自動で開かない場合は以下のURLにアクセス:")
    print()
    print(auth_url)
    print()

    # Open browser
    try:
        webbrowser.open(auth_url)
    except Exception:
        pass

    print("ブラウザで認証を完了してください...")
    print("(認証後、自動的にこのスクリプトに戻ります)")
    print()

    # Wait for callback
    server_thread.join(timeout=300)  # 5 minute timeout
    server.server_close()

    code = OAuthCallbackHandler.authorization_code

    if not code:
        print("Error: 認証コードを取得できませんでした")
        print()
        print("手動で認証コードを入力してください。")
        print("ブラウザのURLから code=XXXX の部分をコピーしてください。")
        code = input("認証コード: ").strip()

        if 'code=' in code:
            parsed = urlparse(code)
            params = parse_qs(parsed.query)
            if 'code' in params:
                code = params['code'][0]

    if not code:
        print("Error: 認証コードが必要です")
        sys.exit(1)

    # Exchange code for tokens
    print()
    print("トークンを取得中...")

    try:
        tokens = exchange_code_for_tokens(client_id, client_secret, code, redirect_uri)
    except requests.exceptions.HTTPError as e:
        print("Error: トークン取得に失敗しました")
        print("Response: {}".format(e.response.text))
        sys.exit(1)

    print()
    print("=" * 60)
    print("成功! 以下の設定を config.json に追加してください:")
    print("=" * 60)
    print()

    config = {
        "google_nest": {
            "enabled": True,
            "project_id": project_id,
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": tokens.get('refresh_token'),
            "credentials_file": None,
            "interval_seconds": 300
        }
    }

    print(json.dumps(config, indent=4, ensure_ascii=False))
    print()

    # Save to file option
    save = input("google_nest_credentials.json に保存しますか? (y/n): ").strip().lower()
    if save == 'y':
        creds = {
            'project_id': project_id,
            'client_id': client_id,
            'client_secret': client_secret,
            'refresh_token': tokens.get('refresh_token')
        }
        with open('google_nest_credentials.json', 'w') as f:
            json.dump(creds, f, indent=2)
        print("保存しました: google_nest_credentials.json")
        print()
        print("重要: このファイルには機密情報が含まれています。")
        print("      .gitignore に追加されていることを確認してください。")

    print()
    print("セットアップ完了!")


if __name__ == '__main__':
    main()
