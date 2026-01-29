# SwitchBot Hub Monitor

SwitchBotデバイスの状態を定期的に監視し、変化があればSlackに通知するツールです。

## 必要要件

- Python 3.7以上
- requests ライブラリ
- SwitchBot Hub (Hub Mini, Hub 2など) とクラウドサービスの有効化
- SwitchBot API トークンとシークレットキー

## セットアップ

### 1. SwitchBot API認証情報の取得

1. SwitchBotアプリを開く (v6.14以上)
2. プロフィール > 設定 > アプリバージョン を10回タップ
3. 開発者オプションが表示される
4. トークンとシークレットキーを取得

### 2. Slack Incoming Webhookの設定

1. [Slack API](https://api.slack.com/apps) でアプリを作成
2. Incoming Webhooksを有効化
3. Webhook URLを取得

### 3. 設定ファイルの作成

```bash
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
        "interval_seconds": 300,
        "device_ids": []
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

### 設定項目の説明

| 項目 | 説明 |
|------|------|
| `switchbot.token` | SwitchBot APIトークン |
| `switchbot.secret` | SwitchBot APIシークレットキー |
| `slack.webhook_url` | Slack Incoming Webhook URL |
| `slack.enabled` | Slack通知の有効/無効 |
| `slack.notify_startup` | 起動時に通知を送信 |
| `slack.notify_errors` | エラー発生時に通知を送信 |
| `monitor.interval_seconds` | 監視間隔（秒）。デフォルト300秒（5分） |
| `monitor.device_ids` | 監視対象デバイスID（空配列で全デバイス） |
| `database.path` | SQLiteデータベースファイルパス |
| `database.history_days` | 履歴保持日数 |
| `logging.level` | ログレベル (DEBUG, INFO, WARNING, ERROR) |
| `logging.file` | ログファイルパス（nullでコンソールのみ） |

### 4. 依存関係のインストール

```bash
pip install requests
```

## 使い方

### 直接実行

```bash
python main.py
```

または設定ファイルを指定:

```bash
python main.py /path/to/config.json
```

### Supervisorでサービス化

`/etc/supervisor/conf.d/switchbot-monitor.conf` にコピー:

```bash
sudo cp supervisor/switchbot-monitor.conf /etc/supervisor/conf.d/
sudo supervisorctl reread
sudo supervisorctl update
sudo supervisorctl start switchbot-monitor
```

## 対応デバイス

SwitchBot API v1.1がサポートする全デバイス:

- 温湿度計 (Meter, MeterPlus)
- ボット (Bot)
- カーテン (Curtain)
- プラグ (Plug, PlugMini)
- ロック (Lock)
- 人感センサー (Motion Sensor)
- 開閉センサー (Contact Sensor)
- Hub 2
- その他

## ファイル構成

```
switchbot-hub/
├── main.py              # メイン監視ループ
├── switchbot_api.py     # SwitchBot API v1.1クライアント
├── database.py          # SQLiteデータベース管理
├── slack_notifier.py    # Slack通知
├── config.json.example  # 設定ファイルサンプル
├── config.json          # 設定ファイル（要作成）
└── supervisor/
    └── switchbot-monitor.conf  # Supervisor設定
```

## API制限

SwitchBot APIは1日10,000リクエストまで。監視間隔を適切に設定してください。

例: 10デバイス × 5分間隔 = 2,880リクエスト/日

## ライセンス

MIT
