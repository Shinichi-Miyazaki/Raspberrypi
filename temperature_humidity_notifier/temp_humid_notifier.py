import adafruit_dht
import time
import datetime
import csv
import os
import argparse
import random
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
import matplotlib.pyplot as plt
import pandas as pd
import traceback

# =============================================================================
# 設定パラメータ（必要に応じて変更）
# =============================================================================
SENSOR = adafruit_dht.DHT22    # 利用するセンサーの種類
PIN = 4                        # センサーを接続しているGPIOピン番号（BCM番号）
SLACK_TOKEN = ''  # SlackのBot User OAuth Token
SLACK_CHANNEL = ''  # Slackの通知送信先チャンネル
channel_id = ""
TEMP_MAX = 23                  # 温度の上限しきい値(°C)
TEMP_MIN = 17                  # 温度の下限しきい値(°C)
HUMIDITY_MAX = 70              # 湿度の上限しきい値(%)
HUMIDITY_MIN = 40              # 湿度の下限しきい値(%)
CHECK_INTERVAL = 30            # センサー測定間隔 (秒)
SHORT_REPORT_INTERVAL = 30     # 定期的に送信する短報告の間隔(分)
LONG_REPORT_INTERVAL = 1       # 定期的に送信する週報告の間隔(日)
CSV_FILENAME = 'temperature_log.csv'  # センサー情報を記録するCSVファイル名
ALERT_COOLDOWN = 43200         # 警告の再通知間隔（秒）
SAVE_DIR = ""  # ログファイルの保存先ディレクトリ


# テストモード設定
TEST_MODE = True               # テストモードを有効にする場合はTrue、実際のセンサーを使う場合はFalse
TEST_DATA_VARIATION = True     # テストデータをランダムに変化させる場合はTrue、固定値の場合はFalse
TEST_TEMP_BASE = 20.0          # テストモード時の基本温度 (°C)
TEST_HUMID_BASE = 50.0         # テストモード時の基本湿度 (%)
TEST_GENERATE_ALERTS = True    # テストモード時にアラートを生成するための異常値を定期的に発生させる
# =============================================================================

def parse_args():
    """
    コマンドライン引数のパースを行います。
      --save-dir : センサーのログデータやグラフを保存するディレクトリを指定
    """
    parser = argparse.ArgumentParser(description='温湿度モニタリングシステム')
    parser.add_argument(
        '--save-dir',
        default=SAVE_DIR,
        help=f'ログファイルの保存先ディレクトリ（デフォルト: {SAVE_DIR}）'
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
            text=f"センサーシステム起動: 接続テスト成功 {'[テストモード]' if TEST_MODE else ''}"
        )
        return True

    except Exception as e:
        print(f"Slack接続エラー: {str(e)}")
        return False

def read_sensor():
    """
    センサーを読み取り、湿度(humidity)と温度(temperature)を取得する。
    テストモードの場合は、疑似的なデータを生成する。
    取得に成功した場合は(湿度, 温度)のタプルを返すが、失敗した場合は(None, None)を返す。
    """
    if TEST_MODE:
        # テストモードでのデータ生成
        # まず基本値で初期化
        temperature = TEST_TEMP_BASE
        humidity = TEST_HUMID_BASE

        if TEST_DATA_VARIATION:
            # 実際のセンサーの挙動を模倣するためにランダムな変動を加える
            temp_variation = random.uniform(-0.5, 0.5)
            humid_variation = random.uniform(-2.0, 2.0)
            temperature += temp_variation
            humidity += humid_variation

            # アラートを生成するための異常値を時々発生させる
            if TEST_GENERATE_ALERTS and random.random() < 0.1:  # 10%の確率で異常値
                if random.random() < 0.5:
                    # 高温または低温
                    temperature = TEMP_MAX + 2.0 if random.random() < 0.5 else TEMP_MIN - 2.0
                else:
                    # 高湿度または低湿度
                    humidity = HUMIDITY_MAX + 5.0 if random.random() < 0.5 else HUMIDITY_MIN - 5.0

        return round(humidity, 3), round(temperature, 3)
    else:
        # 実際のセンサーからデータを読み取る
        try:
            humidity, temperature = adafruit_dht.read_retry(SENSOR, PIN)
            if humidity is not None and temperature is not None:
                return round(humidity, 3), round(temperature, 3)
            print("センサーからのデータ取得に失敗しました。再試行します...")
            return None, None
        except Exception as e:
            print(f"センサー読み取りエラー: {str(e)}")
            return None, None

def save_to_csv(csv_path, humidity, temperature):
    """
    CSVファイルに、タイムスタンプと温度、湿度の情報を追記保存する。
      csv_path : 書き込み先のCSVファイルパス
      humidity : 湿度
      temperature : 温度
    """
    try:
        timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        with open(csv_path, 'a', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([timestamp, temperature, humidity])
    except Exception as e:
        print(f"CSVファイル書き込みエラー: {str(e)}")

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
        if (alert_states['temp_high']['last_sent'] is None or
            (current_time - alert_states['temp_high']['last_sent']).total_seconds() > ALERT_COOLDOWN):
            alerts.append(f"警告: 温度上昇 ({temperature}°C) 以後12時間は警告を出しません。")
            alert_states['temp_high']['last_sent'] = current_time
    else:
        alert_states['temp_high']['active'] = False

    if temperature < TEMP_MIN:
        if (alert_states['temp_low']['last_sent'] is None or
            (current_time - alert_states['temp_low']['last_sent']).total_seconds() > ALERT_COOLDOWN):
            alerts.append(f"警告: 温度低下 ({temperature}°C) 以後12時間は警告を出しません。")
            alert_states['temp_low']['last_sent'] = current_time
    else:
        alert_states['temp_low']['active'] = False

    if humidity > HUMIDITY_MAX:
        if (alert_states['humidity_high']['last_sent'] is None or
            (current_time - alert_states['humidity_high']['last_sent']).total_seconds() > ALERT_COOLDOWN):
            alerts.append(f"警告: 湿度上昇 ({humidity}%) 以後12時間は警告を出しません。")
            alert_states['humidity_high']['last_sent'] = current_time
    else:
        alert_states['humidity_high']['active'] = False

    if humidity < HUMIDITY_MIN:
        if (alert_states['humidity_low']['last_sent'] is None or
            (current_time - alert_states['humidity_low']['last_sent']).total_seconds() > ALERT_COOLDOWN):
            alerts.append(f"警告: 湿度低下 ({humidity}%) add water to humidifier 以後12時間は警告を出しません。")
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

        # データが空の場合はエラーを返す
        if df.empty:
            print("グラフ作成用のデータがありません")
            return False

        # グラフの作成
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8))

        # 温度のプロット（赤線）
        ax1.plot(df['timestamp'], df['temperature'], 'r-')
        ax1.set_title('Temperature (°C)')
        ax1.grid(True)
        ax1.set_ylim([TEMP_MIN-5, TEMP_MAX+5])  # 見やすい範囲に調整

        # 湿度のプロット（青線）
        ax2.plot(df['timestamp'], df['humidity'], 'b-')
        ax2.set_title('Humidity (%)')
        ax2.grid(True)
        ax2.set_ylim([HUMIDITY_MIN-10, HUMIDITY_MAX+10])  # 見やすい範囲に調整

        # レイアウトを調整して保存
        plt.tight_layout()
        plt.savefig(output_path)
        plt.close()
        return True

    except Exception as e:
        print(f"グラフ作成エラー: {str(e)}")
        traceback.print_exc()
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
        # ファイルの存在確認
        if not os.path.exists(graph_path):
            print(f"エラー: グラフファイルが存在しません: {graph_path}")
            return False
        if not os.path.exists(csv_path):
            print(f"エラー: CSVファイルが存在しません: {csv_path}")
            return False

        print(f"グラフファイルサイズ: {os.path.getsize(graph_path)} bytes")
        print(f"CSVファイルサイズ: {os.path.getsize(csv_path)} bytes")

        print(f"使用するチャンネル: {SLACK_CHANNEL}")
        print(f"チャンネルID: {channel_id}")

        # テストメッセージ
        response = client.chat_postMessage(
            channel=channel_id,
            text=f"ファイル送信テスト: {title_prefix}"
        )

        # ファイル送信でもチャンネルIDを使用
        client.files_upload_v2(
            channels=[channel_id],  # チャンネルIDをリストとして渡す
            file=graph_path,
            title=f"{title_prefix} - グラフ"
        )

        client.files_upload_v2(
            channels=[channel_id],
            file=csv_path,
            title=f"{title_prefix} - データ"
        )
        return True
    except SlackApiError as e:
        print(f"ファイル送信エラー: {e.response['error']}")
        print(f"詳細エラー情報: {e.response}")
        return False
    except Exception as e:
        print(f"ファイル送信中に予期せぬエラーが発生しました: {str(e)}")
        traceback.print_exc()
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
    try:
        args = parse_args()
        os.makedirs(args.save_dir, exist_ok=True)
        csv_path = os.path.join(args.save_dir, CSV_FILENAME)

        # Slackクライアントの初期化
        client = WebClient(token=SLACK_TOKEN)
        # Slack接続テスト
        if not verify_slack_connection(client):
            print("Slackへの接続に失敗しました。SLACK_TOKENとSLACK_CHANNELの設定を確認してください。")
            return

        # 初回実行時にCSVファイルがなければヘッダーを追加
        if not os.path.exists(csv_path):
            with open(csv_path, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(['timestamp', 'temperature', 'humidity'])
            print(f"CSVファイルを作成しました: {csv_path}")

        # レポート送信の基準時間などを変数に保持
        start_time = datetime.datetime.now()
        ten_min_report_sent = False
        last_weekly_report = start_time

        if TEST_MODE:
            print("テストモードでセンサー監視を開始します")
            client.chat_postMessage(
                channel=SLACK_CHANNEL,
                text="テストモードでセンサー監視を開始します（実際のセンサーは使用しません）"
            )
        else:
            print("センサー監視を開始します")

        error_count = 0  # センサー読み取りエラーのカウント
        max_errors = 5   # 連続エラーの許容回数

        while True:
            current_time = datetime.datetime.now()
            elapsed_minutes = (current_time - start_time).total_seconds() / 60

            # 10分経過時のレポート送信
            if elapsed_minutes >= SHORT_REPORT_INTERVAL and not ten_min_report_sent:
                graph_path = os.path.join(args.save_dir, '10min_graph.png')
                temp_csv = os.path.join(args.save_dir, '10min_data.csv')

                print(f"{SHORT_REPORT_INTERVAL}分レポートを作成中...")
                if create_graph(csv_path, graph_path, start_time, current_time):
                    try:
                        pd.read_csv(csv_path, header=0).to_csv(temp_csv, index=False)
                        send_slack_files(client, graph_path, temp_csv, f"{SHORT_REPORT_INTERVAL}分間レポート")
                        print(f"{SHORT_REPORT_INTERVAL}分レポートをSlackに送信しました")
                    except Exception as e:
                        print(f"レポート送信中にエラーが発生しました: {str(e)}")
                        traceback.print_exc()

                ten_min_report_sent = True

            # 週次レポート
            days_since_last_report = (current_time - last_weekly_report).days
            if days_since_last_report >= LONG_REPORT_INTERVAL:
                graph_path = os.path.join(args.save_dir, 'weekly_graph.png')
                temp_csv = os.path.join(args.save_dir, 'weekly_data.csv')

                print(f"{LONG_REPORT_INTERVAL}日レポートを作成中...")
                # 直近の期間のみを対象にグラフとCSVを作成する
                if create_graph(csv_path, graph_path, last_weekly_report, current_time):
                    try:
                        df_weekly = pd.read_csv(csv_path, header=0)
                        df_weekly['timestamp'] = pd.to_datetime(df_weekly['timestamp'], errors='coerce')
                        # 前回のレポート以降のみ取得
                        mask = (df_weekly['timestamp'] >= last_weekly_report) & (df_weekly['timestamp'] <= current_time)
                        df_weekly = df_weekly.loc[mask]
                        df_weekly.to_csv(temp_csv, index=False)
                        send_slack_files(client, graph_path, temp_csv, f"{LONG_REPORT_INTERVAL}日間レポート")
                        print(f"{LONG_REPORT_INTERVAL}日レポートをSlackに送信しました")
                    except Exception as e:
                        print(f"レポート送信中にエラーが発生しました: {str(e)}")
                        traceback.print_exc()

                # 次回レポート作成の基準を更新
                last_weekly_report = current_time

            # 通常の測定処理
            humidity, temperature = read_sensor()
            if humidity is not None and temperature is not None:
                save_to_csv(csv_path, humidity, temperature)
                print(f"[{current_time.strftime('%Y-%m-%d %H:%M:%S')}] 温度: {temperature}°C, 湿度: {humidity}%")

                # エラーカウントをリセット
                error_count = 0

                # しきい値チェックとアラート送信
                alerts = check_thresholds(temperature, humidity)
                for alert in alerts:
                    try:
                        client.chat_postMessage(
                            channel=SLACK_CHANNEL,
                            text=f"{alert} {' [テストモード]' if TEST_MODE else ''}"
                        )
                        print(f"アラートをSlackに送信しました: {alert}")
                    except SlackApiError as e:
                        print(f"Slack送信エラー: {e.response['error']}")
                    except Exception as e:
                        print(f"アラート送信中に予期せぬエラーが発生しました: {str(e)}")
                        traceback.print_exc()
            else:
                # センサー読み取りエラーの処理
                error_count += 1
                if error_count >= max_errors:
                    error_message = f"センサーの読み取りに連続で失敗しています ({error_count}回)。センサーの接続を確認してください。"
                    print(error_message)
                    try:
                        client.chat_postMessage(channel=SLACK_CHANNEL, text=error_message)
                    except Exception:
                        pass

                    # テストモードの場合は、エラー後も続行する（テストデータを使用）
                    if not TEST_MODE:
                        error_count = 0  # エラーカウントをリセット

                print(f"センサー読み取りエラー ({error_count}/{max_errors})")

            time.sleep(CHECK_INTERVAL)

    except KeyboardInterrupt:
        print("\n監視を終了します。")
    except Exception as e:
        error_message = f"予期せぬエラーが発生しました: {str(e)}"
        print(error_message)
        traceback.print_exc()
        try:
            client = WebClient(token=SLACK_TOKEN)
            client.chat_postMessage(channel=SLACK_CHANNEL, text=error_message)
        except:
            pass

if __name__ == "__main__":
    main()
