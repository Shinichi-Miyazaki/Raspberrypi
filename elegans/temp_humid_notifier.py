import Adafruit_DHT
import time
import datetime
import csv
import os
import argparse
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
import matplotlib.pyplot as plt
import pandas as pd

SENSOR = Adafruit_DHT.DHT22
PIN = 4
SLACK_TOKEN = 'xoxb-your-token'
SLACK_CHANNEL = '#sensor-notify'
TEMP_MAX = 30
TEMP_MIN = 10
HUMIDITY_MAX = 80
HUMIDITY_MIN = 30
CHECK_INTERVAL = 30
SHORT_REPORT_INTERVAL = 10  # minutes
LONG_REPORT_INTERVAL = 7    # days
CSV_FILENAME = 'temperature_log.csv'

def parse_args():
    parser = argparse.ArgumentParser(description='温湿度モニタリングシステム')
    parser.add_argument(
        '--save-dir',
        default="/home/si/sensor_logs",
        help='ログファイルの保存先ディレクトリ'
    )
    return parser.parse_args()

def verify_slack_connection(client):
    try:
        auth_test = client.auth_test()
        print(f"Slack認証成功: {auth_test['user']}")
        client.chat_postMessage(channel=SLACK_CHANNEL, text="センサーシステム起動: 接続テスト成功")
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
        alerts.append(f"警告: 湿度低下 ({humidity}%) add water to humidifier")
    return alerts

def create_graph(csv_path, output_path, start_time=None, end_time=None):
    try:
        df = pd.read_csv(csv_path, header=0)
        df['timestamp'] = pd.to_datetime(df['timestamp'], errors='coerce')
        if start_time:
            df = df[df['timestamp'] >= start_time]
        if end_time:
            df = df[df['timestamp'] <= end_time]

        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8))
        ax1.plot(df['timestamp'], df['temperature'], 'r-')
        ax1.set_title('Temperature (°C)')
        ax1.grid(True)

        ax2.plot(df['timestamp'], df['humidity'], 'b-')
        ax2.set_title('Humidity (%)')
        ax2.grid(True)

        plt.tight_layout()
        plt.savefig(output_path)
        plt.close()
        return True
    except Exception as e:
        print(f"グラフ作成エラー: {str(e)}")
        return False

def send_slack_files(client, graph_path, csv_path, title_prefix):
    try:
        client.files_upload_v2(
            channels=SLACK_CHANNEL,
            file=graph_path,
            title=f"{title_prefix} - グラフ"
        )
        client.files_upload_v2(
            channels=SLACK_CHANNEL,
            file=csv_path,
            title=f"{title_prefix} - データ"
        )
        return True
    except SlackApiError as e:
        print(f"ファイル送信エラー: {e.response['error']}")
        return False

def main():
    args = parse_args()
    os.makedirs(args.save_dir, exist_ok=True)
    csv_path = os.path.join(args.save_dir, CSV_FILENAME)

    client = WebClient(token=SLACK_TOKEN)
    if not verify_slack_connection(client):
        return

    # CSVファイルの初期化
    if not os.path.exists(csv_path):
        with open(csv_path, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['timestamp', 'temperature', 'humidity'])

    start_time = datetime.datetime.now()
    ten_min_report_sent = False
    last_weekly_report = start_time

    print("センサー監視を開始します")
    while True:
        current_time = datetime.datetime.now()
        elapsed_minutes = (current_time - start_time).total_seconds() / 60

        # 短期レポート
        if elapsed_minutes >= SHORT_REPORT_INTERVAL and not ten_min_report_sent:
            graph_path = os.path.join(args.save_dir, '10min_graph.png')
            temp_csv = os.path.join(args.save_dir, '10min_data.csv')
            if create_graph(csv_path, graph_path, start_time, current_time):
                df_tmp = pd.read_csv(csv_path, header=0)
                df_tmp.to_csv(temp_csv, index=False)
                send_slack_files(client, graph_path, temp_csv, "10分間レポート")
            ten_min_report_sent = True

        # 週次レポート (7日おき)
        days_since_last_report = (current_time - last_weekly_report).days
        if days_since_last_report >= LONG_REPORT_INTERVAL:
            graph_path = os.path.join(args.save_dir, 'weekly_graph.png')
            temp_csv = os.path.join(args.save_dir, 'weekly_data.csv')
            if create_graph(csv_path, graph_path, last_weekly_report, current_time):
                df_weekly = pd.read_csv(csv_path, header=0)
                df_weekly['timestamp'] = pd.to_datetime(df_weekly['timestamp'], errors='coerce')
                mask = (
                    (df_weekly['timestamp'] >= last_weekly_report) &
                    (df_weekly['timestamp'] <= current_time)
                )
                df_weekly = df_weekly.loc[mask]
                df_weekly.to_csv(temp_csv, index=False)
                send_slack_files(client, graph_path, temp_csv, "週間レポート")

            last_weekly_report = current_time

        humidity, temperature = read_sensor()
        if humidity is not None and temperature is not None:
            save_to_csv(csv_path, humidity, temperature)
            print(f"[{current_time.strftime('%Y-%m-%d %H:%M:%S')}] 温度: {temperature}°C, 湿度: {humidity}%")
            alerts = check_thresholds(temperature, humidity)
            for alert in alerts:
                try:
                    client.chat_postMessage(channel=SLACK_CHANNEL, text=alert)
                except SlackApiError as e:
                    print(f"Slack送信エラー: {e.response['error']}")

        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()
