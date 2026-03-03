#!/bin/bash
# network_watchdog.sh - ネットワーク不通が一定時間続いたらRaspberry Piを再起動する
#
# 使い方:
#   sudo crontab -e で以下を追加:
#   */5 * * * * /home/pi/switchbot-hub/network_watchdog.sh
#
# 動作:
#   1. 複数のホストにpingして疎通確認
#   2. 全て失敗 → 失敗カウントをファイルに記録
#   3. 連続N回失敗（デフォルト: 3回 = 15分）→ sudo reboot
#   4. 1つでも成功 → カウントをリセット

# === 設定 ===
# 連続失敗回数の閾値（cron間隔 × この値 = 再起動までの時間）
# 例: 5分間隔 × 3回 = 15分間ネットワーク不通で再起動
MAX_FAILURES=3

# チェック対象ホスト（複数指定で誤検知を防止）
CHECK_HOSTS=("8.8.8.8" "1.1.1.1" "9.9.9.9")

# ping タイムアウト（秒）
PING_TIMEOUT=5

# ping 回数
PING_COUNT=2

# 失敗カウントファイル
STATE_FILE="/tmp/network_watchdog_failures"

# ログファイル
LOG_FILE="/var/log/network_watchdog.log"

# === ログ関数 ===
log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') - $1" >> "$LOG_FILE"
}

# === メイン処理 ===

# いずれかのホストにpingが通るか確認
network_ok=false
for host in "${CHECK_HOSTS[@]}"; do
    if ping -c "$PING_COUNT" -W "$PING_TIMEOUT" "$host" > /dev/null 2>&1; then
        network_ok=true
        break
    fi
done

if $network_ok; then
    # ネットワーク正常 → カウントリセット
    if [ -f "$STATE_FILE" ]; then
        prev_count=$(cat "$STATE_FILE" 2>/dev/null || echo "0")
        if [ "$prev_count" -gt 0 ] 2>/dev/null; then
            log "ネットワーク復帰 (失敗カウント ${prev_count} → 0)"
        fi
    fi
    echo "0" > "$STATE_FILE"
else
    # ネットワーク不通 → カウント増加
    current=$(cat "$STATE_FILE" 2>/dev/null || echo "0")
    # 数値でない場合は0にリセット
    if ! [ "$current" -ge 0 ] 2>/dev/null; then
        current=0
    fi
    new_count=$((current + 1))
    echo "$new_count" > "$STATE_FILE"

    log "ネットワーク不通を検知 (連続 ${new_count}/${MAX_FAILURES} 回)"

    if [ "$new_count" -ge "$MAX_FAILURES" ]; then
        log "連続 ${new_count} 回のネットワーク不通を検知。再起動を実行します。"
        # カウントをリセット（再起動後に即再起動しないように）
        echo "0" > "$STATE_FILE"
        sync
        sudo reboot
    fi
fi
