import Adafruit_DHT
import time
import datetime
import csv
import os
import matplotlib.pyplot as plt
import pandas as pd
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

# 設定
SENSOR = Adafruit_DHT.DHT22
PIN = 4
CSV_FILE = 'temperature_log.csv'
SLACK_TOKEN = 'あなたのSlackトークン'
SLACK_CHANNEL = '#センサー通知'

# 閾値設定
TEMP_MAX = 30
TEMP_MIN = 10
HUMIDITY_MAX = 80
HUMIDITY_MIN = 30

# Slackクライアントの初期化
client = WebClient(token=SLACK_TOKEN)


def read_sensor():
    humidity, temperature = Adafruit_DHT.read_retry(SENSOR, PIN)
    return humidity, temperature


def save_to_csv(humidity, temperature):
    timestamp = datetime.datetime.now()
    with open(CSV_FILE, 'a', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([timestamp, temperature, humidity])


def check_alerts(temperature, humidity):
    alerts = []
    if temperature > TEMP_MAX:
        alerts.append(f"警告: 温度が高すぎます ({temperature}°C)")
    elif temperature < TEMP_MIN:
        alerts.append(f"警告: 温度が低すぎます ({temperature}°C)")
    if humidity > HUMIDITY_MAX:
        alerts.append(f"警告: 湿度が高すぎます ({humidity}%)")
    elif humidity < HUMIDITY_MIN:
        alerts.append(f"警告: 湿度が低すぎます ({humidity}%)")
    return alerts


def send_slack_message(message):
    try:
        client.chat_postMessage(channel=SLACK_CHANNEL, text=message)
    except SlackApiError as e:
        print(f"Error sending message: {e.response['error']}")


def create_weekly_graph():
    df = pd.read_csv(CSV_FILE, names=['timestamp', 'temperature', 'humidity'])
    df['timestamp'] = pd.to_datetime(df['timestamp'])

    plt.figure(figsize=(12, 6))
    plt.plot(df['timestamp'], df['temperature'], label='Temperature (°C)')
    plt.plot(df['timestamp'], df['humidity'], label='Humidity (%)')
    plt.legend()
    plt.title('Weekly Temperature and Humidity')
    plt.xlabel('Date')
    plt.xticks(rotation=45)
    plt.tight_layout()

    graph_file = 'weekly_graph.png'
    plt.savefig(graph_file)
    return graph_file


def main():
    # CSVファイルが存在しない場合は作成
    if not os.path.exists(CSV_FILE):
        with open(CSV_FILE, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['timestamp', 'temperature', 'humidity'])

    while True:
        humidity, temperature = read_sensor()
        if humidity is not None and temperature is not None:
            save_to_csv(humidity, temperature)

            # アラートのチェック
            alerts = check_alerts(temperature, humidity)
            for alert in alerts:
                send_slack_message(alert)

            # 1週間ごとにグラフを作成して送信
            if datetime.datetime.now().weekday() == 6 and datetime.datetime.now().hour == 0:
                graph_file = create_weekly_graph()
                client.files_upload(
                    channels=SLACK_CHANNEL,
                    file=graph_file,
                    title='Weekly Temperature and Humidity Report'
                )

        time.sleep(300)  # 5分待機


if __name__ == "__main__":
    main()