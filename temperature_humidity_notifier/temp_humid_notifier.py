import os
import csv
import time
import datetime
import argparse
import random
import traceback
import RPi.GPIO as GPIO

# --- Adafruit CircuitPython DHT 用 -----------------------------------------
import board                       # ← NEW
import adafruit_dht                # ← NEW
# ---------------------------------------------------------------------------

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
import matplotlib.pyplot as plt
import pandas as pd

# =============================================================================
# 設定パラメータ（必要に応じて変更）
# =============================================================================
DHT_PIN = board.D4                 # ← BCM4 に相当。board.D4 へ変更
SLACK_TOKEN = ''                   # Slack Bot User OAuth Token
SLACK_CHANNEL = ''                 # チャンネル名（"#xxxx" もしくは "CXXXXXXXX"）
channel_id = ''                    # ファイル送信時に使う場合セットしておく
TEMP_MAX = 23
TEMP_MIN = 17
HUMIDITY_MAX = 70
HUMIDITY_MIN = 40
CHECK_INTERVAL = 600               # (秒)
SHORT_REPORT_INTERVAL = 30         # (分)
LONG_REPORT_INTERVAL = 1           # (日)
CSV_FILENAME = 'temperature_log.csv'
ALERT_COOLDOWN = 43200             # (秒)
SAVE_DIR = ''

# テストモード
TEST_MODE = True
TEST_DATA_VARIATION = True
TEST_TEMP_BASE = 20.0
TEST_HUMID_BASE = 50.0
TEST_GENERATE_ALERTS = True
# =============================================================================


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='温湿度モニタリングシステム')
    parser.add_argument('--save-dir',
                        default=SAVE_DIR,
                        help=f'ログファイルの保存先ディレクトリ（デフォルト: {SAVE_DIR}）')
    return parser.parse_args()


def verify_slack_connection(client: WebClient) -> bool:
    try:
        auth_test = client.auth_test()
        print(f"Slack認証成功: {auth_test['user']}")
        client.chat_postMessage(channel=SLACK_CHANNEL,
                                text=f"センサーシステム起動: 接続テスト成功 "
                                     f"{'[テストモード]' if TEST_MODE else ''}")
        return True
    except Exception as e:
        print(f"Slack接続エラー: {e}")
        return False


# --- DHT22 センサーを一度だけ初期化 ----------------------------------------
if not TEST_MODE:
    # Raspberry Pi 4 では use_pulseio=False が推奨
    # という風にいわれているが、どうやらadafruit_circuitpython_dht とは相性が悪いようなので、ないほうが良い
    dht_device = adafruit_dht.DHT22(DHT_PIN,)
else:
    dht_device = None                                                  # テスト用ダミー
# ---------------------------------------------------------------------------


def read_sensor():
    """
    (humidity, temperature) を返す。
    取得失敗時は (None, None)。
    """
    if TEST_MODE:
        temperature = TEST_TEMP_BASE
        humidity = TEST_HUMID_BASE

        if TEST_DATA_VARIATION:
            temperature += random.uniform(-0.5, 0.5)
            humidity += random.uniform(-2.0, 2.0)
            if TEST_GENERATE_ALERTS and random.random() < 0.1:
                if random.random() < 0.5:
                    temperature = TEMP_MAX + 2 if random.random() < 0.5 else TEMP_MIN - 2
                else:
                    humidity = HUMIDITY_MAX + 5 if random.random() < 0.5 else HUMIDITY_MIN - 5

        return round(humidity, 3), round(temperature, 3)

    # --- 実機読み取り -------------------------------------------------------
    try:
        temperature = dht_device.temperature         # °C
        humidity = dht_device.humidity               # %
        if humidity is not None and temperature is not None:
            return round(humidity, 3), round(temperature, 3)
        print("センサーからのデータ取得に失敗しました。再試行します...")
        return None, None
    except RuntimeError as e:
        # 読み取り失敗はよく起こるのでログだけ
        print(f"DHT 取得失敗: {e}")
        return None, None
    except Exception as e:
        # その他クリティカルな例外はセンサーをリセット
        print(f"DHT 重大エラー: {e}")
        dht_device.exit()
        time.sleep(2)
        return None, None
    # ----------------------------------------------------------------------


def save_to_csv(csv_path, humidity, temperature):
    timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    try:
        with open(csv_path, 'a', newline='') as f:
            csv.writer(f).writerow([timestamp, temperature, humidity])
    except Exception as e:
        print(f"CSV書き込みエラー: {e}")


# 重複通知抑制用タイムスタンプのみ保持
alert_states = {
    'temp_high': None,
    'temp_low': None,
    'humidity_high': None,
    'humidity_low': None
}


def check_thresholds(temperature, humidity):
    current = datetime.datetime.now()
    alerts = []

    def ok_to_send(key):
        last = alert_states[key]
        return last is None or (current - last).total_seconds() > ALERT_COOLDOWN

    if temperature > TEMP_MAX and ok_to_send('temp_high'):
        alerts.append(f"警告: 温度上昇 ({temperature}°C) 以後12時間は警告を出しません。")
        alert_states['temp_high'] = current

    if temperature < TEMP_MIN and ok_to_send('temp_low'):
        alerts.append(f"警告: 温度低下 ({temperature}°C) 以後12時間は警告を出しません。")
        alert_states['temp_low'] = current

    if humidity > HUMIDITY_MAX and ok_to_send('humidity_high'):
        alerts.append(f"警告: 湿度上昇 ({humidity}%) 以後12時間は警告を出しません。")
        alert_states['humidity_high'] = current

    if humidity < HUMIDITY_MIN and ok_to_send('humidity_low'):
        alerts.append(f"警告: 湿度低下 ({humidity}%) add water to humidifier 以後12時間は警告を出しません。")
        alert_states['humidity_low'] = current

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

        # 使用するチャンネルを決定 (channel_idが空の場合はSLACK_CHANNELを使用)
        target_channel = channel_id if channel_id else SLACK_CHANNEL
        print(f"使用するチャンネル: {target_channel}")

        # ファイル送信
        client.files_upload_v2(
            channels=[target_channel],  # チャンネルIDをリストとして渡す
            file=graph_path,
            title=f"{title_prefix} - グラフ"
        )

        client.files_upload_v2(
            channels=[target_channel],
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

        # 長期レポートの初期時間を現在時間から1日前に設定して早く送信できるようにする
        last_weekly_report = start_time - datetime.timedelta(days=LONG_REPORT_INTERVAL - 0.1)

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

            # 週次レポート - 修正部分
            time_since_last_report = (current_time - last_weekly_report).total_seconds()
            days_since_last_report = time_since_last_report / (24 * 3600)  # 秒数から日数を計算

            if days_since_last_report >= LONG_REPORT_INTERVAL:
                graph_path = os.path.join(args.save_dir, 'weekly_graph.png')
                temp_csv = os.path.join(args.save_dir, 'weekly_data.csv')

                print(f"{LONG_REPORT_INTERVAL}日レポートを作成中... ({days_since_last_report:.2f}日経過)")
                # 直近の期間のみを対象にグラフとCSVを作成する
                report_start_time = last_weekly_report
                if create_graph(csv_path, graph_path, report_start_time, current_time):
                    try:
                        df_weekly = pd.read_csv(csv_path, header=0)
                        df_weekly['timestamp'] = pd.to_datetime(df_weekly['timestamp'], errors='coerce')
                        # 前回のレポート以降のみ取得
                        mask = (df_weekly['timestamp'] >= report_start_time) & (df_weekly['timestamp'] <= current_time)
                        df_weekly = df_weekly.loc[mask]

                        # データが存在する場合のみCSVを作成して送信
                        if not df_weekly.empty:
                            df_weekly.to_csv(temp_csv, index=False)

                            # channel_idが空文字列の場合はSLACK_CHANNELを使用
                            target_channel = channel_id if channel_id else SLACK_CHANNEL
                            client.chat_postMessage(
                                channel=target_channel,
                                text=f"{LONG_REPORT_INTERVAL}日間レポートを送信します"
                            )

                            send_slack_files(client, graph_path, temp_csv, f"{LONG_REPORT_INTERVAL}日間レポート")
                            print(f"{LONG_REPORT_INTERVAL}日レポートをSlackに送信しました")
                        else:
                            print("レポート期間内にデータがありません")
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
    finally:
        # プログラム終了時の後処理
        print("リソースをクリーンアップしています...")

        # DHTデバイスが初期化されている場合は終了処理
        if not TEST_MODE and dht_device is not None:
            try:
                dht_device.exit()
                print("DHT22センサー接続を終了しました")
            except:
                pass

        # GPIO設定をクリーンアップ
        try:
            GPIO.cleanup()
            print("GPIOリソースをクリーンアップしました")
        except:
            pass

if __name__ == "__main__":
    main()
