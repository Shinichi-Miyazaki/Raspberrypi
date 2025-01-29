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

def create_graph(file_name, start_time=None, end_time=None):
    """CSVのログからグラフを生成し、画像ファイルを返す。

    Args:
        file_name (str): 保存先の画像ファイル名
        start_time (datetime): この時刻以降のデータを使用（指定しない場合は全期間）
        end_time (datetime): この時刻までのデータを使用（指定しない場合は全期間）
    """
    df = pd.read_csv(CSV_FILE, names=['timestamp', 'temperature', 'humidity'], skiprows=1)
    df['timestamp'] = pd.to_datetime(df['timestamp'])

    # start_time, end_time があれば絞り込む
    if start_time:
        df = df[df['timestamp'] >= start_time]
    if end_time:
        df = df[df['timestamp'] <= end_time]

    if df.empty:
        return None

    plt.figure(figsize=(12, 6))
    plt.plot(df['timestamp'], df['temperature'], label='Temperature (°C)', color='r')
    plt.plot(df['timestamp'], df['humidity'], label='Humidity (%)', color='b')
    plt.legend()
    plt.title('Temperature and Humidity')
    plt.xlabel('Time')
    plt.xticks(rotation=45)
    plt.tight_layout()

    plt.savefig(file_name)
    plt.close()
    return file_name

def filter_and_save_csv(raw_csv_path, filtered_csv_path, start_time, end_time):
    """start_time～end_timeの範囲を抽出して、別のCSVに書き出す"""
    # ログを読み込み
    df = pd.read_csv(raw_csv_path, names=['timestamp', 'temperature', 'humidity'], skiprows=1)
    df['timestamp'] = pd.to_datetime(df['timestamp'])

    # 時間で絞り込み
    df_filtered = df[(df['timestamp'] >= start_time) & (df['timestamp'] <= end_time)]

    if df_filtered.empty:
        return False

    # CSVに書き出す
    df_filtered.to_csv(filtered_csv_path, index=False)
    return True

def main():
    # CSVファイルが存在しない場合は作成
    if not os.path.exists(CSV_FILE):
        with open(CSV_FILE, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['timestamp', 'temperature', 'humidity'])

    start_time = datetime.datetime.now()
    first_report_sent = False  # 10分後の初回レポート送信フラグ

    while True:
        humidity, temperature = read_sensor()
        if humidity is not None and temperature is not None:
            # 温湿度をCSVに保存
            save_to_csv(humidity, temperature)

            # 取得した温湿度をリアルタイムに画面表示
            print(f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] "
                  f"温度: {temperature}°C, 湿度: {humidity}%")

            # アラートのチェック
            alerts = check_alerts(temperature, humidity)
            for alert in alerts:
                send_slack_message(alert)

            # 起動後10分経過時に、一度だけグラフを作成＆CSVの該当範囲を送信
            if not first_report_sent:
                elapsed_seconds = (datetime.datetime.now() - start_time).total_seconds()
                if elapsed_seconds >= 600:  # 600秒=10分
                    # 10分間(起動から現在時刻まで)のグラフを作成
                    ten_min_graph = create_graph(
                        file_name='10min_graph.png',
                        start_time=start_time,
                        end_time=datetime.datetime.now()
                    )
                    # 10分間のraw data CSVを抽出
                    csv_output_path = '10min_data.csv'
                    csv_ok = filter_and_save_csv(
                        raw_csv_path=CSV_FILE,
                        filtered_csv_path=csv_output_path,
                        start_time=start_time,
                        end_time=datetime.datetime.now()
                    )
                    # Slackへアップロード
                    if ten_min_graph:
                        try:
                            client.files_upload(
                                channels=SLACK_CHANNEL,
                                file=ten_min_graph,
                                title='10分間の温湿度変化 (グラフ)'
                            )
                            send_slack_message("最初の10分間の温湿度変化グラフを送信しました。")
                        except SlackApiError as e:
                            print(f"Error sending file: {e.response['error']}")
                    if csv_ok:
                        try:
                            client.files_upload(
                                channels=SLACK_CHANNEL,
                                file=csv_output_path,
                                title='10分間の温湿度変化 (生データ CSV)'
                            )
                        except SlackApiError as e:
                            print(f"Error sending CSV file: {e.response['error']}")
                    first_report_sent = True

            # 1週間ごとにグラフを作成して送信（元のロジック）
            if datetime.datetime.now().weekday() == 6 and datetime.datetime.now().hour == 0:
                weekly_graph = create_graph(
                    file_name='weekly_graph.png',
                    # 週の始まりを決めて抽出したい場合は、start_time引数に先週の日付を指定する等
                    # ここではすべての期間を対象
                )
                if weekly_graph:
                    try:
                        client.files_upload(
                            channels=SLACK_CHANNEL,
                            file=weekly_graph,
                            title='Weekly Temperature and Humidity Report'
                        )
                    except SlackApiError as e:
                        print(f"Error sending file: {e.response['error']}")

        time.sleep(5)  # 5秒ごとに温湿度を読み取って表示（お好みで調整）

if __name__ == "__main__":
    main()