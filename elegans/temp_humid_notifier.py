import Adafruit_DHT
import time
import datetime
import csv
import os
import argparse
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

# 設定パラメータ
SENSOR = Adafruit_DHT.DHT22
PIN = 4
SLACK_TOKEN = 'xoxb-your-token'  # Bot User OAuth Token
SLACK_CHANNEL = '#sensor-notify'  # 実際のチャンネル名

# 閾値設定
TEMP_MAX = 30
TEMP_MIN = 10
HUMIDITY_MAX = 80
HUMIDITY_MIN = 30

def parse_args():
    parser = argparse.ArgumentParser(description='温湿度モニタリングシステム')
    parser.add_argument('--save-dir',
                       default="/home/pi/sensor_logs",
                       help='ログファイルの保存先ディレクトリ')
    return parser.parse_args()

def verify_slack_connection(client):
    try:
        auth_test = client.auth_test()
        print(f"Slack認証成功: {auth_test['user']}")

        # チャンネル確認
        target_channel = SLACK_CHANNEL.replace('#', '')
        channels = client.conversations_list()
        channel_names = [channel['name'] for channel in channels['channels']]

        if target_channel not in channel_names:
            print(f"エラー: チャンネル {SLACK_CHANNEL} が見つかりません")
            return False

        # テストメッセージ
        client.chat_postMessage(
            channel=SLACK_CHANNEL,
            text="センサーシステム起動: 接続テスト成功"
        )
        return True

    except Exception as e:
        print(f"Slack接続エラー: {str(e)}")
        return False

def read_sensor():
    humidity, temperature = Adafruit_DHT.read_retry(SENSOR, PIN)
    if humidity is not None and temperature is not None:
        return round(humidity, 3), round(temperature, 3)
    return None, None

def save_to_csv(csv_path, humidity, temperature):
    timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with open(csv_path, 'a', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([timestamp, temperature, humidity])

def check_thresholds(temperature, humidity):
    alerts = []
    if temperature > TEMP_MAX:
        alerts.append(f"警告: 温度上昇 ({temperature}°C)")
    elif temperature < TEMP_MIN:
        alerts.append(f"警告: 温度低下 ({temperature}°C)")
    if humidity > HUMIDITY_MAX:
        alerts.append(f"警告: 湿度上昇 ({humidity}%)")
    elif humidity < HUMIDITY_MIN:
        alerts.append(f"警告: 湿度低下 ({humidity}%)")
    return alerts

def main():
    args = parse_args()
    os.makedirs(args.save_dir, exist_ok=True)
    csv_path = os.path.join(args.save_dir, 'temperature_log.csv')

    # Slackクライアント初期化
    client = WebClient(token=SLACK_TOKEN)

    # Slack接続確認
    if not verify_slack_connection(client):
        print("Slack接続に失敗しました")
        return

    # CSVファイル初期化
    if not os.path.exists(csv_path):
        with open(csv_path, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['timestamp', 'temperature', 'humidity'])

    print("センサー監視を開始します")
    while True:
        humidity, temperature = read_sensor()

        if humidity is not None and temperature is not None:
            # データ保存
            save_to_csv(csv_path, humidity, temperature)

            # 現在値表示
            print(f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] "
                  f"温度: {temperature}°C, 湿度: {humidity}%")

            # アラートチェック
            alerts = check_thresholds(temperature, humidity)
            for alert in alerts:
                try:
                    client.chat_postMessage(channel=SLACK_CHANNEL, text=alert)
                except SlackApiError as e:
                    print(f"Slack送信エラー: {e.response['error']}")

        time.sleep(5)  # 5秒間隔で測定

if __name__ == "__main__":
    main()