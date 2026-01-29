# SwitchBot Hub Monitor

SwitchBotデバイスの状態を監視し、変化があればSlackに通知するツールです。

**特徴:**
- ポーリング方式とWebhook方式のハイブリッド監視
- デバイスごとに監視方式を選択可能（無視/ポーリング/Webhook）
- Cloudflare Tunnelによる外部公開対応
- SQLiteによる状態履歴の保存

## 必要要件

- Python 3.7以上
- requests ライブラリ
- SwitchBot Hub (Hub Mini, Hub 2など) とクラウドサービスの有効化
- cloudflared (Webhook使用時)

## クイックスタート

### 1. SwitchBot API認証情報の取得

1. SwitchBotアプリを開く (v6.14以上)
2. **プロフィール** > **設定** > **アプリバージョン** を10回タップ
3. **開発者オプション** が表示される
4. **トークン** と **シークレットキー** を取得・保存

### 2. Slack Incoming Webhookの設定

1. [Slack API](https://api.slack.com/apps) でアプリを作成
2. **Incoming Webhooks** を有効化
3. チャンネルを選択して **Webhook URL** を取得

### 3. Cloudflare Tunnelの設定（Webhook使用時）

#### cloudflaredのインストール（Raspberry Pi）

```bash
# ARM版をダウンロード
wget https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64
sudo mv cloudflared-linux-arm64 /usr/local/bin/cloudflared
sudo chmod +x /usr/local/bin/cloudflared

# 確認
cloudflared --version
```

#### Cloudflare Tunnelの作成

```bash
# Cloudflareにログイン
cloudflared tunnel login

# トンネルを作成
cloudflared tunnel create switchbot-webhook

# 作成されたトンネルIDを確認
cloudflared tunnel list
```

#### DNSレコードの設定

```bash
# トンネルをドメインにルーティング
cloudflared tunnel route dns switchbot-webhook webhook.your-domain.com
```

#### cloudflared設定ファイルの作成

`~/.cloudflared/config.yml`:

```yaml
tunnel: <TUNNEL_ID>
credentials-file: /home/pi/.cloudflared/<TUNNEL_ID>.json

ingress:
  - hostname: webhook.your-domain.com
    service: http://localhost:8080
  - service: http_status:404
```

### 4. 設定ファイルの作成

```bash
cd /path/to/switchbot-hub
cp config.json.example config.json
```

`config.json` を編集:

```json
{
    "switchbot": {
        "token": "YOUR_SWITCHBOT_API_TOKEN",
        "secret": "YOUR_SWITCHBOT_API_SECRET"
    },
    "slack": {
        "webhook_url": "https://hooks.slack.com/services/YOUR/WEBHOOK/URL",
        "enabled": true,
        "notify_startup": true,
        "notify_errors": true
    },
    "monitor": {
        "interval_seconds": 1800,
        "ignore_devices": [
            "テープライト BA",
            "学習リモコン 23",
            "サーキュレーター B7",
            "玄関通話",
            "おいだき",
            "アロマディヒューザー",
            "ハブミニ DC",
            "玄関Open",
            "ハブミニ C6",
            "キーパッド"
        ],
        "polling_devices": [
            "CO2センサー（温湿度計） 3A",
            "CO2センサー（温湿度計） C3",
            "温湿度計Pro 7B",
            "CO2センサー（温湿度計） 17",
            "防水温湿度計 1C",
            "ハブ２ 19"
        ]
    },
    "webhook": {
        "enabled": true,
        "port": 8080,
        "path": "/switchbot/webhook"
    },
    "cloudflare_tunnel": {
        "enabled": true,
        "hostname": "webhook.your-domain.com",
        "config_path": "/home/pi/.cloudflared/config.yml"
    },
    "database": {
        "path": "device_states.db",
        "history_days": 30
    },
    "logging": {
        "level": "INFO",
        "file": null
    }
}
```

## 設定項目の説明

### switchbot

| 項目 | 説明 |
|------|------|
| `token` | SwitchBot APIトークン |
| `secret` | SwitchBot APIシークレットキー |

### slack

| 項目 | 説明 |
|------|------|
| `webhook_url` | Slack Incoming Webhook URL |
| `enabled` | Slack通知の有効/無効 |
| `notify_startup` | 起動時に通知 |
| `notify_errors` | エラー発生時に通知 |

### monitor

| 項目 | 説明 |
|------|------|
| `interval_seconds` | ポーリング間隔（秒）。デフォルト1800秒（30分） |
| `ignore_devices` | 監視しないデバイス名のリスト（部分一致） |
| `polling_devices` | ポーリングで監視するデバイス名のリスト（部分一致） |

**デバイスの振り分けロジック:**
1. `ignore_devices` に一致 → 無視
2. `polling_devices` に一致 → 30分ごとにAPI取得
3. どちらにも一致しない → Webhook経由で監視

### webhook

| 項目 | 説明 |
|------|------|
| `enabled` | Webhookサーバーの有効/無効 |
| `port` | リッスンポート |
| `path` | Webhookエンドポイントパス |

### cloudflare_tunnel

| 項目 | 説明 |
|------|------|
| `enabled` | Cloudflare Tunnelの有効/無効 |
| `hostname` | トンネルのホスト名（DNS設定済み） |
| `config_path` | cloudflared設定ファイルパス（nullでQuick Tunnel） |

### database

| 項目 | 説明 |
|------|------|
| `path` | SQLiteデータベースファイルパス |
| `history_days` | 状態変更履歴の保持日数 |
| `sensor_data_days` | センサー時系列データの保持日数（デフォルト7日） |

### daily_report

| 項目 | 説明 |
|------|------|
| `enabled` | 日次レポートの有効/無効 |
| `hour` | レポート送信時刻（0-23、デフォルト8時） |

### logging

| 項目 | 説明 |
|------|------|
| `level` | ログレベル (DEBUG, INFO, WARNING, ERROR) |
| `file` | ログファイルパス（nullでコンソールのみ） |

## 使い方

### 依存関係のインストール

```bash
pip install requests
```

### 直接実行

```bash
python main.py
```

### Supervisorでサービス化

`/etc/supervisor/conf.d/switchbot-monitor.conf`:

```ini
[program:switchbot-monitor]
command=/usr/bin/python3 /home/pi/switchbot-hub/main.py
directory=/home/pi/switchbot-hub
user=pi
autostart=true
autorestart=true
stdout_logfile=/var/log/switchbot-monitor.log
stderr_logfile=/var/log/switchbot-monitor-error.log
```

```bash
sudo supervisorctl reread
sudo supervisorctl update
sudo supervisorctl start switchbot-monitor
```

## 動作確認

### デバイス一覧の確認

```bash
python -c "
import json
from switchbot_api import SwitchBotAPI
config = json.load(open('config.json'))
api = SwitchBotAPI(config['switchbot']['token'], config['switchbot']['secret'])
devices = api.get_devices()
for d in devices.get('deviceList', []):
    print('{} ({})'.format(d['deviceName'], d['deviceType']))
"
```

### Webhook登録状況の確認

```bash
python -c "
import json
from switchbot_api import SwitchBotAPI
config = json.load(open('config.json'))
api = SwitchBotAPI(config['switchbot']['token'], config['switchbot']['secret'])
print(api.query_webhook())
"
```

## アーキテクチャ

```
┌─────────────────────────────────────────────────────────────┐
│                     main.py (SwitchBotMonitor)              │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────────┐  │
│  │ Polling     │    │ Webhook     │    │ Cloudflare      │  │
│  │ (30分間隔)  │    │ Server      │◄───│ Tunnel          │  │
│  │             │    │ (port 8080) │    │                 │  │
│  └──────┬──────┘    └──────┬──────┘    └─────────────────┘  │
│         │                  │                                 │
│         ▼                  ▼                                 │
│  ┌─────────────────────────────────────────────────────┐    │
│  │              database.py (SQLite)                   │    │
│  │              状態保存・変更検出                       │    │
│  └─────────────────────────┬───────────────────────────┘    │
│                            │                                 │
│                            ▼                                 │
│  ┌─────────────────────────────────────────────────────┐    │
│  │           slack_notifier.py                         │    │
│  │           変更があればSlack通知                      │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                             │
└─────────────────────────────────────────────────────────────┘

        ┌─────────────────────┐
        │   SwitchBot Cloud   │
        │   (API & Webhook)   │
        └─────────────────────┘
```

## 日次レポートとグラフ機能

温湿度計・CO2センサーのデータは時系列で保存され、毎日指定時刻にグラフ付きレポートがSlackに送信されます。

### 機能

- **時系列データ保存**: ポーリングごとに温度・湿度・CO2をSQLiteに記録
- **日次サマリー**: 最高/最低/平均値を算出
- **グラフ生成**: QuickChart.io APIで温湿度・CO2のグラフを生成
- **Slack通知**: グラフ画像付きでレポートを送信

### 設定例

```json
{
    "daily_report": {
        "enabled": true,
        "hour": 8
    },
    "database": {
        "sensor_data_days": 7
    }
}
```

毎朝8時に前日のレポートが送信されます。

### 手動でレポートを生成

```bash
python -c "
import json
from main import SwitchBotMonitor
config = json.load(open('config.json'))
monitor = SwitchBotMonitor(config)
monitor.send_daily_report('2024-01-30')  # 指定日
"
```

## API制限について

SwitchBot APIは **1日10,000リクエスト** の制限があります。

**計算例（ポーリングのみの場合）:**
- 10デバイス × 48回/日（30分間隔） = 480リクエスト/日

**Webhookを使う利点:**
- Webhookはサーバー側からのPush通知なのでAPI制限にカウントされない
- リアルタイム性が高い
- ポーリング対象を減らせばAPI使用量を大幅に削減可能

## トラブルシューティング

### cloudflaredが見つからない

```bash
# インストール確認
which cloudflared

# パスを通す
export PATH=$PATH:/usr/local/bin
```

### Webhookが登録できない

1. Cloudflare Tunnelが正しく動作しているか確認
2. DNS設定が反映されているか確認（数分かかる場合あり）
3. `https://webhook.your-domain.com/health` にアクセスして `{"status": "ok"}` が返るか確認

### デバイスがWebhookに反応しない

一部のデバイスはWebhook非対応です。その場合は `polling_devices` に追加してポーリング監視してください。

## ファイル構成

```
switchbot-hub/
├── main.py                 # メインエントリーポイント
├── switchbot_api.py        # SwitchBot API v1.1クライアント
├── database.py             # SQLite状態管理・時系列データ
├── slack_notifier.py       # Slack通知（グラフ付きレポート対応）
├── webhook_server.py       # HTTPサーバー（Webhook受信）
├── cloudflare_tunnel.py    # Cloudflare Tunnel管理
├── chart_generator.py      # QuickChart.ioでグラフ生成
├── config.json.example     # 設定サンプル
├── config.json             # 設定ファイル（要作成）
└── supervisor/
    └── switchbot-monitor.conf
```

## ライセンス

MIT
