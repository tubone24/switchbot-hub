# SwitchBot & Netatmo & Google Nest Hub Monitor

SwitchBotデバイス、Netatmo Weather Station、Google Nest（ドアベル/カメラ）の状態を監視し、変化があればSlackに通知するツールです。

<img width="652" height="582" alt="スクリーンショット 2026-01-30 11 09 42" src="https://github.com/user-attachments/assets/e5ddebe0-bcdb-4fd1-bc40-e2021252cba1" />


## 特徴

- **マルチプラットフォーム監視**: SwitchBot、Netatmo、Google Nestを一元管理
- **ハイブリッド監視**: ポーリング方式とWebhook方式を組み合わせ
- **複数Slackチャンネル対応**: 防犯/環境更新/グラフを別チャンネルに通知
- **日本語通知**: セキュリティイベントは「解錠されました」などわかりやすく通知
- **5分ごとのグラフレポート**: 温湿度・CO2・気圧・騒音を屋外/屋内で分けてグラフ化
- **ローカルチャート生成**: Raspberry Pi向けにmatplotlibでローカル生成＋Slackファイルアップロード対応
- **Quick Tunnel対応**: ドメイン不要でWebhook受信可能（URLは自動更新）
- **JST表示**: グラフの時間軸は日本時間
- **ゴミ収集通知**: 曜日ごとのゴミ出しリマインダーを画像付きで通知
- **Webダッシュボード**: LANからアクセス可能なリアルタイムダッシュボード（30秒自動更新）

## 対応デバイス

### SwitchBot
- 温湿度計（Meter, MeterPlus, MeterPro）
- CO2センサー（MeterPro CO2）
- 防水温湿度計（Outdoor Meter）
- Hub 2
- スマートロック
- 開閉センサー
- モーションセンサー
- ドアベル

### Netatmo Weather Station
- メインステーション / NAMain（温度・湿度・CO2・気圧・騒音）
- 屋外モジュール / NAModule1（温度・湿度）
- 追加室内モジュール / NAModule4（温度・湿度・CO2）
- 風センサー / NAModule2（風速・風向・突風速・突風向）
- 雨センサー / NAModule3（雨量・1時間累計・24時間累計）

### Google Nest（Device Access API）
- Nest Doorbell（ドアベルチャイム・人物検知・動体検知）
- Nest Camera（人物検知・動体検知・音声検知）
- クリッププレビュー対応（Nest Aware契約時）

## Slack通知チャンネル

| チャンネル | 用途 | 通知例 |
|-----------|------|--------|
| `#home-security` | 防犯デバイス（ロック、開閉センサー、Nest等） | 🔓 ロックPro 24が解錠されました / 🔔 玄関が押されました |
| `#atmos-update` | 温湿度・CO2の変化（Webhook） | CO2センサー 3A: 22.7°C / 51% / 1013ppm |
| `#atmos-graph` | 5分ごとのグラフレポート | 屋外/屋内の温度・湿度・CO2グラフ |
| `#outdoor-alert` | お外アラート（Netatmo専用） | ☔ 雨が降り始めました |
| `#general` | ゴミ収集リマインダー | 明日は「燃やすごみ」の日です（画像付き） |

## 必要要件

- Python 3.7以上
- requests ライブラリ
- SwitchBot Hub (Hub Mini, Hub 2など)
- cloudflared (Webhook使用時)
- Netatmo Weather Station（オプション）
- Google Nest Doorbell/Camera（オプション）
  - Device Access 登録（$5 一回払い）
  - Google Cloud プロジェクト
- matplotlib 3.5.3（ローカルチャート生成時、オプション）

## クイックスタート

### 1. SwitchBot API認証情報の取得

1. SwitchBotアプリを開く (v6.14以上)
2. **プロフィール** > **設定** > **アプリバージョン** を10回タップ
3. **開発者オプション** が表示される
4. **トークン** と **シークレットキー** を取得

### 2. Netatmo API認証情報の取得（オプション）

#### ステップ1: Netatmoアプリの作成

1. [Netatmo Connect](https://dev.netatmo.com/) にアクセス
2. **Create an App** でアプリを作成
   - App Name: 任意の名前（例: `Home Monitor`）
   - Description: 任意の説明
   - Data Protection Officer: 自分の名前とメールアドレス
3. **Client ID** と **Client Secret** をメモ

#### ステップ2: 認証ヘルパーでリフレッシュトークンを取得

```bash
# 認証ヘルパーを実行
python netatmo_auth.py
```

対話形式で案内されます:
1. Client ID を入力
2. Client Secret を入力
3. ブラウザが自動で開く → Netatmoにログイン → 許可
4. リフレッシュトークンが表示される

```
$ python netatmo_auth.py
============================================================
Netatmo OAuth2 認証ヘルパー
============================================================

Client ID を入力: xxxxxxxxxxxxxxxxxxxxxxxx
Client Secret を入力: xxxxxxxxxxxxxxxxxxxxxxxx

ブラウザで以下のURLを開きます...

認可コードを取得しました!

トークン取得成功!

Refresh Token: xxxxxxxxxxxxxxxxxxxxxxxx

============================================================
config.json に以下を追加してください:
============================================================
{
    "netatmo": {
        "enabled": true,
        "client_id": "xxxxxxxx",
        "client_secret": "xxxxxxxx",
        "refresh_token": "xxxxxxxx",
        ...
    }
}
```

> **Note**: 認証情報は `netatmo_credentials.json` に保存することもできます（スクリプト内で選択可能）

### 3. Google Nest API認証情報の取得（オプション）

Google Nest Doorbell/Cameraを監視する場合に必要です。

#### ステップ1: Device Access に登録

1. [Device Access Console](https://console.nest.google.com/device-access/) にアクセス
2. **$5** の一回払いで開発者登録
3. プロジェクトを作成し、**Project ID (UUID)** をメモ

#### ステップ2: Google Cloud プロジェクトの設定

1. [Google Cloud Console](https://console.cloud.google.com/) でプロジェクトを作成
2. **Smart Device Management API** を有効化
3. **OAuth 2.0 クライアント ID** を作成（Webアプリケーション）
4. **Authorized redirect URIs** に `http://localhost:8888` を追加
5. **Client ID** と **Client Secret** をメモ

#### ステップ3: Pub/Sub の設定（リアルタイムイベント用）

1. [Cloud Pub/Sub](https://console.cloud.google.com/cloudpubsub) でトピックを作成
   - トピック名: `projects/sdm-prod/topics/enterprise-YOUR_PROJECT_ID`
2. そのトピックに**サブスクリプション**を作成
3. サービスアカウントに `pubsub.subscriber` 権限を付与

#### ステップ4: 認証ヘルパーでリフレッシュトークンを取得

```bash
python google_nest_auth.py
```

対話形式で案内されます:
1. Device Access Project ID を入力
2. OAuth2 Client ID を入力
3. OAuth2 Client Secret を入力
4. ブラウザが開く → Googleアカウントでログイン → Nestデバイスへのアクセスを許可
5. リフレッシュトークンが表示される

```
$ python google_nest_auth.py
============================================================
Google Nest Device Access - OAuth2 Setup Helper
============================================================

Device Access Project ID (UUID): xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
OAuth2 Client ID: xxxxxxx.apps.googleusercontent.com
OAuth2 Client Secret: xxxxxxxxxxxxxxxx

ブラウザで認証ページを開きます...

成功! 以下の設定を config.json に追加してください:
{
    "google_nest": {
        "enabled": true,
        "project_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
        "client_id": "xxxxxxx.apps.googleusercontent.com",
        "client_secret": "xxxxxxxx",
        "refresh_token": "xxxxxxxx",
        ...
    }
}
```

### 4. Slack Incoming Webhookの設定

複数のチャンネル用にWebhook URLを取得:

1. [Slack API](https://api.slack.com/apps) でアプリを作成
2. **Incoming Webhooks** を有効化
3. 以下のチャンネルそれぞれにWebhook URLを作成:
   - `#home-security` (防犯通知)
   - `#atmos-update` (環境変化通知)
   - `#atmos-graph` (グラフレポート)

### 4. cloudflaredのインストール（Raspberry Pi）

```bash
# ARM版をダウンロード
wget https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm
sudo mv cloudflared-linux-arm /usr/local/bin/cloudflared
sudo chmod +x /usr/local/bin/cloudflared

# 確認
cloudflared --version
```

### 5. 設定ファイルの作成

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
    "netatmo": {
        "enabled": true,
        "client_id": "YOUR_NETATMO_CLIENT_ID",
        "client_secret": "YOUR_NETATMO_CLIENT_SECRET",
        "refresh_token": "YOUR_NETATMO_REFRESH_TOKEN",
        "credentials_file": null,
        "interval_seconds": 600
    },
    "google_nest": {
        "enabled": true,
        "project_id": "YOUR_DEVICE_ACCESS_PROJECT_ID",
        "client_id": "YOUR_OAUTH_CLIENT_ID.apps.googleusercontent.com",
        "client_secret": "YOUR_OAUTH_CLIENT_SECRET",
        "refresh_token": "YOUR_REFRESH_TOKEN",
        "credentials_file": null,
        "interval_seconds": 300,
        "pubsub": {
            "enabled": true,
            "gcp_project_id": "YOUR_GCP_PROJECT_ID",
            "subscription_id": "YOUR_PUBSUB_SUBSCRIPTION_ID",
            "poll_timeout_seconds": 60
        }
    },
    "slack": {
        "channels": {
            "home_security": "https://hooks.slack.com/services/YOUR/SECURITY/WEBHOOK",
            "atmos_update": "https://hooks.slack.com/services/YOUR/ATMOS/WEBHOOK",
            "atmos_graph": "https://hooks.slack.com/services/YOUR/GRAPH/WEBHOOK"
        },
        "enabled": true,
        "notify_startup": true,
        "notify_errors": true
    },
    "monitor": {
        "interval_seconds": 1800,
        "ignore_devices": ["テープライト BA", "ハブミニ DC"],
        "polling_devices": ["CO2センサー", "温湿度計", "ハブ２"]
    },
    "webhook": {
        "enabled": true,
        "port": 8080,
        "path": "/switchbot/webhook"
    },
    "cloudflare_tunnel": {
        "enabled": true,
        "hostname": null,
        "config_path": null
    },
    "database": {
        "path": "device_states.db",
        "history_days": 30,
        "sensor_data_days": 7,
        "netatmo_data_days": 7
    },
    "graph_report": {
        "enabled": true,
        "interval_minutes": 5
    },
    "dashboard": {
        "enabled": true,
        "port": 7777
    },
    "logging": {
        "level": "INFO",
        "file": null
    }
}
```

### 6. 実行

```bash
pip install requests
python main.py
```

## 設定項目

### switchbot

| 項目 | 説明 |
|------|------|
| `token` | SwitchBot APIトークン |
| `secret` | SwitchBot APIシークレットキー |

### netatmo

| 項目 | 説明 |
|------|------|
| `enabled` | Netatmo監視の有効/無効 |
| `client_id` | Netatmoアプリのクライアントid |
| `client_secret` | Netatmoアプリのクライアントシークレット |
| `refresh_token` | OAuth2リフレッシュトークン |
| `credentials_file` | リフレッシュトークン永続化ファイルパス（オプション） |
| `interval_seconds` | ポーリング間隔（秒）。デフォルト600秒（10分） |

**credentials_file について:**

Netatmoはリフレッシュトークンが定期的に更新されます。`credentials_file` を指定すると、更新されたトークンを自動で保存します。指定しない場合、長期間実行していると認証が切れる可能性があります。

### google_nest

| 項目 | 説明 |
|------|------|
| `enabled` | Google Nest監視の有効/無効 |
| `project_id` | Device Access プロジェクトID (UUID形式) |
| `client_id` | Google Cloud OAuth2 クライアントID |
| `client_secret` | Google Cloud OAuth2 クライアントシークレット |
| `refresh_token` | OAuth2リフレッシュトークン |
| `credentials_file` | リフレッシュトークン永続化ファイルパス（オプション） |
| `interval_seconds` | ポーリング間隔（秒）。デフォルト300秒（5分） |

#### google_nest.pubsub（リアルタイムイベント用）

| 項目 | 説明 |
|------|------|
| `enabled` | Pub/Sub リアルタイムイベント受信の有効/無効 |
| `gcp_project_id` | Google Cloud プロジェクトID |
| `subscription_id` | Pub/Sub サブスクリプションID |
| `poll_timeout_seconds` | Long polling タイムアウト（秒）。デフォルト60秒 |

**イベントタイプ:**

| イベント | 説明 | 対応デバイス |
|---------|------|-------------|
| `chime` | ドアベルが押された | Nest Doorbell |
| `motion` | 動きを検知 | Doorbell / Camera |
| `person` | 人物を検知 | Doorbell / Camera |
| `sound` | 音声を検知 | Camera |
| `clip_preview` | クリッププレビュー | Doorbell / Camera（Nest Aware契約時） |

**クリッププレビューについて:**

Nest Aware契約がある場合、イベント発生時にクリッププレビュー（短い動画）のURLが取得できます。本ツールはクリッププレビューを自動でダウンロードし、Slack通知に添付します。

### slack

| 項目 | 説明 |
|------|------|
| `bot_token` | Bot User OAuth Token（ローカルチャート使用時に必要、`xoxb-...`形式） |
| `channels.home_security` | 防犯通知用Webhook URL |
| `channels.atmos_update` | 環境変化通知用Webhook URL |
| `channels.atmos_graph` | グラフレポート用Webhook URLまたはChannel ID（ローカルチャート時は`C...`形式のID） |
| `enabled` | Slack通知の有効/無効 |
| `notify_startup` | 起動時に通知 |
| `notify_errors` | エラー発生時に通知 |

### monitor

| 項目 | 説明 |
|------|------|
| `interval_seconds` | SwitchBotポーリング間隔（秒）。デフォルト1800秒（30分） |
| `ignore_devices` | 監視しないデバイス名のリスト（部分一致） |
| `polling_devices` | ポーリングで監視するデバイス名のリスト（部分一致） |

**デバイスの振り分けロジック:**
1. `ignore_devices` に一致 → 無視
2. `polling_devices` に一致 → ポーリング監視（グラフ用データ蓄積）
3. どちらにも一致しない → Webhook監視

### webhook

| 項目 | 説明 |
|------|------|
| `enabled` | Webhookサーバーの有効/無効 |
| `port` | リッスンポート（デフォルト8080） |
| `path` | Webhookエンドポイントパス |

### cloudflare_tunnel

| 項目 | 説明 |
|------|------|
| `enabled` | Cloudflare Tunnelの有効/無効 |
| `hostname` | トンネルのホスト名（`null`でQuick Tunnel） |
| `config_path` | cloudflared設定ファイルパス（`null`でQuick Tunnel） |

**Quick Tunnel モード（推奨）:**

`hostname` と `config_path` の両方を `null` にすると、Cloudflare Quick Tunnelを使用します。

- ドメイン不要、認証不要で即座に使える
- 起動ごとにランダムなURL（`xxx.trycloudflare.com`）が生成される
- **自動クリーンアップ**: 起動時に古いWebhook URLをSwitchBotから自動削除し、新しいURLを登録

### database

| 項目 | 説明 |
|------|------|
| `path` | SQLiteデータベースファイルパス |
| `history_days` | 状態変更履歴の保持日数 |
| `sensor_data_days` | SwitchBotセンサー時系列データの保持日数（デフォルト7日） |
| `netatmo_data_days` | Netatmo時系列データの保持日数（デフォルト7日） |

### graph_report

| 項目 | 説明 |
|------|------|
| `enabled` | グラフレポートの有効/無効 |
| `interval_minutes` | レポート送信間隔（分）。デフォルト5分 |
| `downsample_seconds` | データのダウンサンプリング間隔（秒）。デフォルト600秒 |
| `use_local_chart` | ローカルチャート生成を使用（Raspberry Pi向け）。デフォルト`false` |

#### ローカルチャート生成（Raspberry Pi向け）

`use_local_chart: true` にすると、QuickChart.io URLの代わりにmatplotlibでローカル生成し、Slackファイルアップロードで送信します。

**利点:**
- QuickChart.ioへの外部依存なし
- ネットワーク不安定時でも確実にグラフ生成
- 高解像度の画像

**必要な設定:**

```json
{
  "slack": {
    "bot_token": "xoxb-your-bot-token",
    "channels": {
      "atmos_graph": "C0123456789"
    }
  },
  "graph_report": {
    "use_local_chart": true
  }
}
```

**必要なBot Tokenスコープ:**
- `files:write` - ファイルアップロード用
- `chat:write` - メッセージ送信用

**Raspberry Piでのセットアップ:**

```bash
# 日本語フォントのインストール
sudo apt-get install fonts-ipaexfont fonts-ipafont

# Python ライブラリ（Python 3.7対応版）
pip install matplotlib==3.5.3
```

### dashboard

| 項目 | 説明 |
|------|------|
| `enabled` | Webダッシュボードの有効/無効 |
| `port` | HTTPサーバーのポート番号（デフォルト7777） |

**設定例:**

```json
{
    "dashboard": {
        "enabled": true,
        "port": 7777
    }
}
```

**アクセス方法:**

ブラウザで `http://<Raspberry PiのIP>:7777/` にアクセス

**機能:**
- 全センサーの現在値をカード形式で表示
- 24時間分の時系列グラフ（温度・湿度・CO2・気圧・騒音・風速・雨量）
- 30秒ごとに自動リフレッシュ
- ダークテーマのレスポンシブUI
- スマートフォン対応

**エンドポイント:**

| パス | 説明 |
|------|------|
| `/` | ダッシュボードHTML |
| `/api/data` | センサーデータJSON API |
| `/health` | ヘルスチェック |

### logging

| 項目 | 説明 |
|------|------|
| `level` | ログレベル (DEBUG, INFO, WARNING, ERROR) |
| `file` | ログファイルパス（`null`でコンソールのみ） |

### garbage_collection

| 項目 | 説明 |
|------|------|
| `enabled` | ゴミ収集通知の有効/無効 |
| `channel_id` | 通知先SlackチャンネルID（`C...`形式） |
| `image_dir` | ゴミ種類ごとの画像ディレクトリ |
| `evening_hour` | 前日通知の時刻（0-23）。デフォルト20 |
| `morning_hour` | 当日通知の時刻（0-23）。デフォルト6 |
| `schedule` | 曜日ごとのゴミ種類（monday〜sunday） |
| `monthly_schedule` | 月次スケジュール（第n週の曜日指定） |
| `additional_rules` | メイン種類に紐づく追加収集アイテム |

**通知タイミング:**
- **evening_hour時**: 翌日のゴミ収集を通知（「明日は〇〇の日です」）
- **morning_hour時**: 当日のゴミ収集を通知（「今日は〇〇の日です」）

**月次スケジュールの設定例:**

古紙・段ボールのように「第2・第4日曜日」など隔週や月1回の収集に対応：

```json
"monthly_schedule": {
    "古紙・段ボール": {
        "weekday": "sunday",
        "weeks": [2, 4]
    },
    "粗大ごみ": {
        "weekday": "saturday",
        "weeks": [1]
    }
}
```

| フィールド | 説明 |
|-----------|------|
| `weekday` | 曜日（monday〜sunday） |
| `weeks` | 月の第n週のリスト（1〜5） |

上記の設定で、第2日曜日の通知は以下のようになります：
```
明日は「古紙・段ボール」の日です
```

週次スケジュール（`schedule`）と月次スケジュール（`monthly_schedule`）が同じ日に重なった場合、両方が通知されます：
```
明日は「燃やすごみ」、「古紙・段ボール」の日です
（燃えないごみ、スプレー缶、電池類も収集日です）
```

**追加収集ルールの設定例:**

```json
"additional_rules": {
    "燃やすごみ": ["燃えないごみ", "スプレー缶", "電池類"],
    "缶・びん・ペットボトル": ["小さな金属類"]
}
```

**画像ファイルの準備:**

`garbage_images/` ディレクトリに画像ファイルを配置します。

画像の検索優先順位：
1. **ゴミ種類名**（例：`古紙・段ボール.png`）
2. **曜日名**（例：`月.png`）

```
garbage_images/
├── 月.png           # 曜日ベース（燃やすごみ）
├── 火.png           # 曜日ベース（プラスチック資源）
├── 木.png           # 曜日ベース（缶・びん・ペットボトル）
├── 金.png           # 曜日ベース（燃やすごみ）
├── 古紙・段ボール.png  # 種類名ベース（月次スケジュール用）
└── 粗大ごみ.png      # 種類名ベース（月次スケジュール用）
```

**注**:
- 収集がない日は通知がスキップされるため、画像は不要です
- 月次スケジュールのゴミ種類は種類名での画像を推奨（曜日が不定のため）

## グラフレポート機能

5分ごとに `#atmos-graph` チャンネルへグラフ付きレポートを送信します。

### 生成されるグラフ（最大11種類）

| グラフ | 内容 | データソース |
|-------|------|-------------|
| 🌳 屋外 温度 | 屋外センサーの温度推移 | SwitchBot + Netatmo |
| 🌳 屋外 湿度 | 屋外センサーの湿度推移 | SwitchBot + Netatmo |
| 🏠 屋内 温度 | 室内センサーの温度推移 | SwitchBot + Netatmo |
| 🏠 屋内 湿度 | 室内センサーの湿度推移 | SwitchBot + Netatmo |
| 🏠 CO2濃度 | 室内のCO2推移（1000ppm/1500ppmしきい値ライン付き） | SwitchBot + Netatmo |
| 🏠 気圧 | 気圧推移 | Netatmo (NAMain) |
| 🏠 騒音 | 騒音レベル推移 | Netatmo (NAMain) |
| 🌬️ 風速 | 風速推移 | Netatmo (NAModule2) |
| 🌬️ 突風 | 突風速度推移 | Netatmo (NAModule2) |
| 🌧️ 雨量 | 現在の雨量 | Netatmo (NAModule3) |
| 🌧️ 雨量 (24h) | 24時間累計雨量 | Netatmo (NAModule3) |

**注**: センサーがない場合、そのグラフは生成されません。

### デバイス名のプレフィックス

グラフでは、デバイスのソースがわかるようにプレフィックスが付きます：

| プレフィックス | ソース |
|--------------|--------|
| `[SB]` | SwitchBot |
| `[NA]` | Netatmo |

### 屋外センサーの判定

**SwitchBot:** デバイス名に以下のキーワードが含まれる場合、屋外センサーとして扱います：
- `防水温湿度計`
- `屋外`
- `Outdoor`

**Netatmo:** モジュールタイプが `NAModule1`（屋外モジュール）の場合、自動的に屋外として判定されます。

### Netatmo固有の計測値

Netatmoセンサーはサマリーで以下の追加情報を表示します：

| モジュール | 計測値 |
|-----------|--------|
| NAMain（メインステーション） | 気圧（hPa）、騒音（dB） |
| NAModule2（風センサー） | 風速（km/h）、突風（km/h） |
| NAModule3（雨センサー） | 雨量（mm）、24h累計（mm） |

### タイムゾーン

グラフの横軸は **JST（日本標準時）** で表示されます。

## お外アラート（Netatmo専用）

Netatmoセンサーのデータを基に、天気・体調に関するアラートを `#outdoor-alert` チャンネルに送信します。

### アラートの種類

| アラート | 条件 | レベル | 根拠 |
|---------|------|--------|------|
| ☔ **雨が降り始めました** | 雨量 0→0超 | INFO | 雨センサー検知 |
| 🌬️ **やや強い風** | 36km/h (10m/s)以上 | INFO | [気象庁](https://www.jma.go.jp/jma/kishou/know/yougo_hp/kazehyo.pdf) - 傘がさせない |
| 🌬️ **強い風** | 54km/h (15m/s)以上 | WARNING | 気象庁 - 風に向かって歩けない |
| 🌬️ **非常に強い風（暴風）** | 72km/h (20m/s)以上 | DANGER | 気象庁 - 立っていられない |
| 🌡️ **昨日より暑い/寒い** | 前日同時刻比±2℃以上 | INFO/WARNING(±5℃) | 体感変化 |
| 📉 **気圧低下/上昇傾向** | 6時間で4hPa以上変化 | INFO | [研究](https://zutool.jp/column/lifestyle/post-26643) - 自律神経影響 |
| 📉 **気圧変化（頭痛注意）** | 6時間で6hPa以上変化 | WARNING | 研究 - 頭痛発症しやすい |
| 📉 **気圧急変（気象病警戒）** | 6時間で10hPa以上変化 | DANGER | 気象庁 - 急速発達低気圧基準 |

### アラートのクールダウン

同じ種類のアラートは、同一デバイスに対して**1時間に1回**までしか送信されません（スパム防止）。

### アラート判定ロジックの詳細

#### 雨アラート
```
IF 現在の雨量 > 0 AND (前回の雨量 == 0 OR 前回の雨量 == NULL)
THEN 「雨が降り始めました」を通知
```
- **データソース**: NAModule3 の `Rain` フィールド
- **判定タイミング**: Netatmoポーリング時（デフォルト10分間隔）

#### 風アラート
```
風速 = MAX(wind_strength, gust_strength)

IF 風速 >= 72 km/h THEN DANGER「非常に強い風（暴風）」
ELSE IF 風速 >= 54 km/h THEN WARNING「強い風」
ELSE IF 風速 >= 36 km/h THEN INFO「やや強い風」
```
- **しきい値根拠**: [気象庁 風の強さと吹き方](https://www.jma.go.jp/jma/kishou/know/yougo_hp/kazehyo.pdf)
- **変換**: 10m/s = 36km/h, 15m/s = 54km/h, 20m/s = 72km/h

#### 気温変化アラート
```
差分 = 現在の気温 - 24時間前の気温

IF |差分| >= 5.0°C THEN WARNING
ELSE IF |差分| >= 2.0°C THEN INFO

メッセージ:
  差分 > 0 → 「昨日より○°C暑いです」
  差分 < 0 → 「昨日より○°C寒いです」
```
- **比較対象**: 同じ屋外モジュール（NAModule1）の24時間前のデータ
- **許容誤差**: ±30分以内の最も近いデータポイントを使用

#### 気圧変化アラート（頭痛ーる風）
```
差分 = 現在の気圧 - 6時間前の気圧

IF |差分| >= 10 hPa THEN DANGER「気圧急激変化（気象病警戒）」
ELSE IF |差分| >= 6 hPa THEN WARNING「頭痛に注意」
ELSE IF |差分| >= 4 hPa THEN INFO「気圧傾向」

追加条件:
  IF 現在の気圧 < 1000 hPa THEN 「低気圧」を付記
```
- **しきい値根拠**:
  - 4hPa/6h: [研究](https://zutool.jp/column/lifestyle/post-26643) - 自律神経への影響が出始める
  - 6hPa/6h: 研究 - 標準気圧1013hPaから6〜10hPa低下で頭痛発症率が最も高い
  - 10hPa/6h: 気象庁の「急速に発達する低気圧」基準（12時間で10hPa以上）

### 必要なNetatmoモジュール

| アラート | 必要モジュール |
|---------|--------------|
| 雨 | NAModule3（雨センサー） |
| 風 | NAModule2（風センサー） |
| 気温変化 | NAModule1（屋外モジュール） |
| 気圧変化 | NAMain（メインステーション） |

## 防犯通知（日本語）

`#home-security` チャンネルには以下のような日本語通知が送信されます：

### SwitchBot

| デバイス | 通知例 |
|---------|--------|
| スマートロック | 🔓 ロックPro 24が解錠されました / 🔒 施錠されました |
| 開閉センサー | 🚪 開閉センサー3が開きました / 閉まりました |
| モーションセンサー | 👁 動きを検知しました |
| ドアベル | 🔔 テレビドアホン 30が押されました |

### Google Nest

| イベント | 通知例 |
|---------|--------|
| ドアベルチャイム | 🔔 玄関が押されました |
| 人物検知 | 🚶 玄関で人物を検知しました |
| 動体検知 | 👁 玄関で動きを検知しました |
| 音声検知 | 🔊 リビングで音声を検知しました |

**クリッププレビュー添付:**

Nest Aware契約時、イベント通知にクリッププレビュー動画（MP4）が添付されます。

## アーキテクチャ

```mermaid
flowchart TB
    subgraph main["main.py (Monitor)"]
        direction TB

        subgraph input["データ収集"]
            sbPolling["SwitchBot Polling<br/>30分間隔"]
            naPolling["Netatmo Polling<br/>10分間隔"]
            nestPolling["Nest Polling<br/>5分間隔"]
            nestPubsub["Nest Pub/Sub<br/>リアルタイム"]
            webhook["Webhook Server<br/>port 8080<br/>リアルタイム受信"]
        end

        cf["Cloudflare<br/>Quick Tunnel"] --> webhook

        sbPolling --> db
        naPolling --> db
        nestPolling --> db
        nestPubsub --> security
        webhook --> db

        db["database.py (SQLite)<br/>状態保存 / 変更検出<br/>SwitchBot時系列 / Netatmo時系列"]

        db --> security["#home-security<br/>防犯通知（日本語）"]
        db --> atmos["#atmos-update<br/>環境変化通知"]
        db --> atmosGraph["#atmos-graph<br/>5分ごとグラフ"]
        db --> dashboard["Webダッシュボード<br/>port 7777<br/>30秒自動更新"]
    end

    subgraph external["外部API"]
        sbAPI["SwitchBot API<br/>v1.1"]
        naAPI["Netatmo API<br/>OAuth2"]
        nestAPI["Google Nest SDM API<br/>OAuth2"]
        pubsub["Cloud Pub/Sub"]
    end

    sbAPI --> sbPolling
    naAPI --> naPolling
    nestAPI --> nestPolling
    pubsub --> nestPubsub
```

## Supervisorでサービス化

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

## ネットワークWatchdog（自動再起動）

Raspberry Piでネットワークが長時間不通になると、cloudflaredやPub/Subの再接続が復旧せずハングすることがあります。`network_watchdog.sh` はcronで定期的にネットワーク疎通を確認し、一定時間不通が続いた場合にRaspberry Piを自動で再起動します。

### 動作の仕組み

| 経過時間 | 動作 |
|---------|------|
| 0〜5分 | ping失敗 → 失敗カウント 1/3 |
| 5〜10分 | ping失敗 → 失敗カウント 2/3 |
| 10〜15分 | ping失敗 → 失敗カウント 3/3 → **自動reboot** |
| (途中で復帰) | ping成功 → カウントリセット |

- 3つのDNSサーバー（8.8.8.8, 1.1.1.1, 9.9.9.9）に対してpingし、**全て失敗**した場合のみ不通と判定
- ログは `/var/log/network_watchdog.log` に記録
- 閾値やチェック間隔はスクリプト冒頭の変数で調整可能

### セットアップ

#### 1. スクリプトに実行権限を付与

```bash
chmod +x /home/pi/switchbot-hub/network_watchdog.sh
```

#### 2. piユーザーがパスワードなしでrebootできるようにする

```bash
sudo visudo
```

以下の行を追加:

```
pi ALL=(ALL) NOPASSWD: /sbin/reboot
```

#### 3. cronに登録（root権限）

```bash
sudo crontab -e
```

以下を追加:

```
*/5 * * * * /home/pi/switchbot-hub/network_watchdog.sh
```

#### 4. ログファイルの準備

```bash
sudo touch /var/log/network_watchdog.log
sudo chown pi:pi /var/log/network_watchdog.log
```

### 設定のカスタマイズ

スクリプト冒頭の変数を編集することで動作を調整できます:

| 変数 | デフォルト | 説明 |
|------|-----------|------|
| `MAX_FAILURES` | 3 | 再起動までの連続失敗回数（cron間隔 × この値 = 再起動までの時間） |
| `CHECK_HOSTS` | 8.8.8.8, 1.1.1.1, 9.9.9.9 | チェック対象ホスト |
| `PING_TIMEOUT` | 5 | pingタイムアウト（秒） |
| `PING_COUNT` | 2 | ping回数 |

## API制限について

### SwitchBot
- **1日10,000リクエスト** の制限
- Webhookはサーバー側からのPush通知なのでAPI制限にカウントされない
- ポーリング対象を減らせばAPI使用量を大幅に削減可能

### Netatmo
- **APIリクエスト制限あり**（公式ドキュメント参照）
- デフォルト10分間隔でのポーリングを推奨
- アクセストークンは3時間で期限切れ（自動更新）

### Google Nest
- **Device Access API**: 制限あり（具体的な数値は非公開）
- Pub/Subでリアルタイムイベント受信推奨（ポーリング不要）
- アクセストークンは1時間で期限切れ（自動更新）
- クリッププレビューのダウンロードには**Nest Aware契約**が必要

## ファイル構成

```
switchbot-hub/
├── main.py                 # メインエントリーポイント
├── switchbot_api.py        # SwitchBot API v1.1クライアント
├── netatmo_api.py          # Netatmo Weather Station APIクライアント
├── netatmo_auth.py         # Netatmo OAuth2認証ヘルパー
├── google_nest_api.py      # Google Nest SDM APIクライアント
├── google_nest_auth.py     # Google Nest OAuth2認証ヘルパー
├── google_nest_pubsub.py   # Pub/Sub リアルタイムイベント受信
├── database.py             # SQLite状態管理・時系列データ
├── slack_notifier.py       # Slack通知（複数チャンネル対応）
├── garbage_notifier.py     # ゴミ収集リマインダー通知
├── webhook_server.py       # HTTPサーバー（Webhook受信）
├── cloudflare_tunnel.py    # Cloudflare Tunnel管理
├── chart_generator.py      # QuickChart.ioでグラフ生成
├── local_chart_generator.py # matplotlibでローカルグラフ生成（Raspberry Pi向け）
├── dashboard_server.py     # Webダッシュボード HTTPサーバー
├── network_resilience.py   # ネットワークレジリエンス（ヘルスチェック・サーキットブレーカー）
├── network_watchdog.sh     # ネットワーク不通時の自動再起動スクリプト
├── garbage_images/         # ゴミ種類ごとの画像
├── config.json.example     # 設定サンプル
└── config.json             # 設定ファイル（要作成）
```

## ライセンス

MIT
