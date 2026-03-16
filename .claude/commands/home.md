---
description: スマートホームデバイスの操作・状態確認
---

# スマートホーム操作スキル

ユーザーのリクエスト: $ARGUMENTS

## 手順

1. まず `/api/home/status` で全デバイスの状態を取得して、どのデバイスがあるか把握する
2. ユーザーのリクエストに応じて適切なAPIを呼び出す
3. 結果を人間が読める形で返す

## API サーバー

ベースURL: `http://localhost:9000`

## エンドポイント一覧

### ヘルスチェック
```bash
curl -s http://localhost:9000/api/health
```

### 全デバイス状態取得
```bash
curl -s http://localhost:9000/api/home/status
```

### SwitchBot

デバイス一覧:
```bash
curl -s http://localhost:9000/api/switchbot/devices
```

デバイスステータス:
```bash
curl -s http://localhost:9000/api/switchbot/devices/{device_id}/status
```

コマンド送信:
```bash
curl -s -X POST http://localhost:9000/api/switchbot/devices/{device_id}/command \
  -H 'Content-Type: application/json' \
  -d '{"command": "コマンド名", "parameter": "パラメータ", "commandType": "command"}'
```

#### エアコン制御（IR赤外線リモコン経由）
```bash
# parameter形式: "温度,モード,ファン速度,電源"
# モード: 1=auto, 2=cool, 3=dry, 4=fan, 5=heat
# ファン速度: 1=auto, 2=low, 3=medium, 4=high
curl -s -X POST http://localhost:9000/api/switchbot/devices/{device_id}/command \
  -H 'Content-Type: application/json' \
  -d '{"command": "setAll", "parameter": "25,2,1,on", "commandType": "command"}'
```

#### カーテン制御
```bash
# position: 0=全開, 100=全閉
curl -s -X POST http://localhost:9000/api/switchbot/devices/{device_id}/command \
  -H 'Content-Type: application/json' \
  -d '{"command": "setPosition", "parameter": "0,ff,50", "commandType": "command"}'
```

#### プラグ/Bot ON/OFF
```bash
curl -s -X POST http://localhost:9000/api/switchbot/devices/{device_id}/command \
  -H 'Content-Type: application/json' \
  -d '{"command": "turnOn", "parameter": "default", "commandType": "command"}'
```

### Hue（照明）

ライト一覧:
```bash
curl -s http://localhost:9000/api/hue/lights
```

ライト制御:
```bash
# on: true/false, bri: 0-254, ct: 153-500 (色温度mirek)
curl -s -X PUT http://localhost:9000/api/hue/lights/{light_id} \
  -H 'Content-Type: application/json' \
  -d '{"on": true, "bri": 254}'
```

グループ（部屋）一覧:
```bash
curl -s http://localhost:9000/api/hue/groups
```

グループ制御:
```bash
curl -s -X PUT http://localhost:9000/api/hue/groups/{group_id} \
  -H 'Content-Type: application/json' \
  -d '{"on": true, "bri": 200}'
```

シーン一覧:
```bash
curl -s http://localhost:9000/api/hue/scenes
```

シーン適用:
```bash
curl -s -X PUT http://localhost:9000/api/hue/scenes/{scene_id} \
  -H 'Content-Type: application/json' \
  -d '{"group_id": "1"}'
```

### Netatmo（環境データ）
```bash
curl -s http://localhost:9000/api/netatmo/environment
```

### Google Nest（カメラ）

カメラ一覧:
```bash
curl -s http://localhost:9000/api/nest/cameras
```

カメラ個別状態:
```bash
curl -s http://localhost:9000/api/nest/cameras/{camera_id}
```

## 使用例

- 「リビングの電気を消して」→ まず /api/hue/lights でライト一覧を取得、リビングのライトIDを特定、PUT で off にする
- 「今の室温を教えて」→ /api/netatmo/environment で全センサーデータを取得、温度を返す
- 「エアコンを25度の冷房にして」→ /api/switchbot/devices でIRデバイス一覧を取得、エアコンのIDを特定、POST でsetAllコマンド
- 「カーテンを半分開けて」→ /api/switchbot/devices でカーテンデバイスを特定、POST でsetPositionコマンド (position=50)
- 「全部の状態を教えて」→ /api/home/status で一括取得

## 注意事項

- APIサーバーが起動していない場合は、ユーザーに起動を促す
- デバイス名は日本語の場合があるので、部分一致で探す
- エラーが返ってきた場合は、エラーメッセージを分かりやすく伝える
- 操作前に確認が必要な場合（例: 全てのライトを消す）は、ユーザーに確認を取る
