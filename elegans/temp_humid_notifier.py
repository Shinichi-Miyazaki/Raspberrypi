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

# =============================================================================
# 設定パラメータ（必要に応じて変更）
# =============================================================================
SENSOR = Adafruit_DHT.DHT22    # 利用するセンサーの種類
PIN = 4                        # センサーを接続しているGPIOピン番号（BCM番号）
SLACK_TOKEN = 'xoxb-your-token'  # SlackのBot User OAuth Token
SLACK_CHANNEL = '#sensor-notify'  # Slackの通知送信先チャンネル
TEMP_MAX = 30                  # 温度の上限しきい値(°C)
TEMP_MIN = 10                  # 温度の下限しきい値(°C)
HUMIDITY_MAX = 80              # 湿度の上限しきい値(%)
HUMIDITY_MIN = 30              # 湿度の下限しきい値(%)
CHECK_INTERVAL = 30            # センサー測定間隔 (秒)
SHORT_REPORT_INTERVAL = 10     # 定期的に送信する短報告の間隔(分)
LONG_REPORT_INTERVAL = 7       # 定期的に送信する週報告の間隔(日)
CSV_FILENAME = 'temperature_log.csv'  # センサー情報を記録するCSVファイル名
CHANNEL_ID = "XXXXXXX"          # SlackのチャンネルID（チャンネル名ではない）
ALERT_COOLDOWN = 18000  # 警告の再通知間隔（秒）
# =============================================================================

def parse_args():
    """
    コマンドライン引数のパースを行います。
      --save-dir : センサーのログデータやグラフを保存するディレクトリを指定
    """
    parser = argparse.ArgumentParser(description='温湿度モニタリングシステム')
    parser.add_argument(
        '--save-dir',
        default="/home/si/sensor_logs",
        help='ログファイルの保存先ディレクトリ（デフォルト: /home/si/sensor_logs）'
    )
    return parser.parse_args()

def verify_slack_connection(client):
    """
    Slackとの接続テストを行い、問題なければTrue、失敗ならFalseを返す。
    また、チャンネルが存在しない場合や、Tokenが不正な場合等はエラーメッセージを表示する。
    """
    try:
        auth_test = client.auth_test()
        print(f"Slack認証成功: {auth_test['user']}")

        # 接続テスト用のメッセージを送信
        client.chat_postMessage(
            channel=SLACK_CHANNEL,
            text="センサーシステム起動: 接続テスト成功"
        )
        return True

    except Exception as e:
        print(f"Slack接続エラー: {str(e)}")
        return False

def read_sensor():
    """
    センサーを読み取り、湿度(humidity)と温度(temperature)を取得する。
    取得に成功した場合は(湿度, 温度)のタプルを返すが、失敗した場合は(None, None)を返す。
    """
    humidity, temperature = Adafruit_DHT.read_retry(SENSOR, PIN)
    if humidity is not None and temperature is not None:
        return round(humidity, 3), round(temperature, 3)
    return None, None

def save_to_csv(csv_path, humidity, temperature):
    """
    CSVファイルに、タイムスタンプと温度、湿度の情報を追記保存する。
      csv_path : 書き込み先のCSVファイルパス
      humidity : 湿度
      temperature : 温度
    """
    timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with open(csv_path, 'a', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([timestamp, temperature, humidity])
# グローバル変数として警告状態を管理する辞書を追加
alert_states = {
    'temp_high': {'active': False, 'last_sent': None},
    'temp_low': {'active': False, 'last_sent': None},
    'humidity_high': {'active': False, 'last_sent': None},
    'humidity_low': {'active': False, 'last_sent': None}
}


def check_thresholds(temperature, humidity):
    """
    温度・湿度のしきい値を監視し、異常があればアラートメッセージを返す。
    一定時間内の重複した警告はスキップする。
    """
    current_time = datetime.datetime.now()
    alerts = []

    if temperature > TEMP_MAX:
        if not alert_states['temp_high']['active'] or \
            (alert_states['temp_high']['last_sent'] and
            (current_time - alert_states['temp_high']['last_sent']).total_seconds() > ALERT_COOLDOWN):
            alerts.append(f"警告: 温度上昇 ({temperature}°C)")
            alert_states['temp_high']['active'] = True
            alert_states['temp_high']['last_sent'] = current_time
    else:
        alert_states['temp_high']['active'] = False

    # 他の条件も同様に処理
    if humidity < HUMIDITY_MIN:
        if not alert_states['humidity_low']['active'] or \
            (alert_states['humidity_low']['last_sent'] and
            (current_time - alert_states['humidity_low']['last_sent']).total_seconds() > ALERT_COOLDOWN):
            alerts.append(f"警告: 湿度低下 ({humidity}%) add water to humidifier")
            alert_states['humidity_low']['active'] = True
            alert_states['humidity_low']['last_sent'] = current_time
    else:
        alert_states['humidity_low']['active'] = False

    return alerts
def create_graph(csv_path, output_path, start_time=None, end_time=None):
    """
    ログCSVを読み込み、指定された期間内の温度・湿度の推移をグラフ化してファイル出力する。
      csv_path : 読み込むCSVファイルのパス
      output_path : グラフ画像の保存先パス
      start_time : グラフに含めるデータの開始時刻 (datetime型)
      end_time : グラフに含めるデータの終了時刻 (datetime型)
    処理が成功すればTrueを、失敗すればFalseを返す。
    """
    try:
        # CSVをヘッダー付きで読み込む
        df = pd.read_csv(csv_path, header=0)
        # timestamp列を日時型に変換。読み込みエラーの行はNaTになる（errors='coerce'）
        df['timestamp'] = pd.to_datetime(df['timestamp'], errors='coerce')

        # start_timeやend_timeが指定された場合はその範囲でフィルタ
        if start_time:
            df = df[df['timestamp'] >= start_time]
        if end_time:
            df = df[df['timestamp'] <= end_time]

        # グラフの作成
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8))

        # 温度のプロット（赤線）
        ax1.plot(df['timestamp'], df['temperature'], 'r-')
        ax1.set_title('Temperature (°C)')
        ax1.grid(True)

        # 湿度のプロット（青線）
        ax2.plot(df['timestamp'], df['humidity'], 'b-')
        ax2.set_title('Humidity (%)')
        ax2.grid(True)

        # レイアウトを調整して保存
        plt.tight_layout()
        plt.savefig(output_path)
        plt.close()
        return True

    except Exception as e:
        print(f"グラフ作成エラー: {str(e)}")
        return False

def send_slack_files(client, graph_path, csv_path, title_prefix):
    """
    Slackのファイルアップロード機能を使って、グラフ画像とCSVファイルをアップロードする。
      client : SlackのWebClientインスタンス
      graph_path : アップロードするグラフ画像のパス
      csv_path : アップロードするCSVファイルのパス
      title_prefix : Slackに表示されるファイルのタイトルのプレフィックス
    """
    try:
        # グラフ画像を送信
        client.files_upload_v2(
            channels=CHANNEL_ID,
            file=graph_path,
            title=f"{title_prefix} - グラフ"
        )
        # CSVを送信
        client.files_upload_v2(
            channels=CHANNEL_ID,
            file=csv_path,
            title=f"{title_prefix} - データ"
        )
        return True
    except SlackApiError as e:
        print(f"ファイル送信エラー: {e.response['error']}")
        return False

def main():
    """
    メイン関数。プログラム全体の制御フローを担う。
      1. コマンドライン引数のパース
      2. データ保存先ディレクトリの作成
      3. Slack接続確認
      4. CSVファイルの準備（存在しなければヘッダー行を作成）
      5. 定期的にセンサーを読み込み、温湿度を記録し、しきい値を超えたらSlackに通知
      6. 一定時間ごとにグラフやCSVのレポートファイルをSlackに送信
    """
    args = parse_args()
    os.makedirs(args.save_dir, exist_ok=True)
    csv_path = os.path.join(args.save_dir, CSV_FILENAME)

    # Slackクライアントの初期化
    client = WebClient(token=SLACK_TOKEN)
    # Slack接続テスト
    if not verify_slack_connection(client):
        return

    # 初回実行時にCSVファイルがなければヘッダーを追加
    if not os.path.exists(csv_path):
        with open(csv_path, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['timestamp', 'temperature', 'humidity'])

    # レポート送信の基準時間などを変数に保持
    start_time = datetime.datetime.now()
    ten_min_report_sent = False
    last_weekly_report = start_time

    print("センサー監視を開始します")
    while True:
        current_time = datetime.datetime.now()
        elapsed_minutes = (current_time - start_time).total_seconds() / 60

        # 10分経過時のレポート送信
        if elapsed_minutes >= SHORT_REPORT_INTERVAL and not ten_min_report_sent:
            graph_path = os.path.join(args.save_dir, '10min_graph.png')
            temp_csv = os.path.join(args.save_dir, '10min_data.csv')

            if create_graph(csv_path, graph_path, start_time, current_time):
                pd.read_csv(csv_path, header=0).to_csv(temp_csv, index=False)
                send_slack_files(client, graph_path, temp_csv, "10分間レポート")

            ten_min_report_sent = True

        # 週次レポート（7日ごとにレポートを送る想定）
        days_since_last_report = (current_time - last_weekly_report).days
        if days_since_last_report >= LONG_REPORT_INTERVAL:
            graph_path = os.path.join(args.save_dir, 'weekly_graph.png')
            temp_csv = os.path.join(args.save_dir, 'weekly_data.csv')

            # 直近の週のみを対象にグラフとCSVを作成する
            if create_graph(csv_path, graph_path, last_weekly_report, current_time):
                df_weekly = pd.read_csv(csv_path, header=0)
                df_weekly['timestamp'] = pd.to_datetime(df_weekly['timestamp'], errors='coerce')
                # 前回のレポート以降のみ取得
                mask = (df_weekly['timestamp'] >= last_weekly_report) & (df_weekly['timestamp'] <= current_time)
                df_weekly = df_weekly.loc[mask]
                df_weekly.to_csv(temp_csv, index=False)
                send_slack_files(client, graph_path, temp_csv, "週間レポート")

            # 次回レポート作成の基準を更新
            last_weekly_report = current_time

        # 通常の測定処理
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

