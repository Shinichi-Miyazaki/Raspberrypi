import os
import csv
import time
import datetime
import argparse
import random
import traceback
import RPi.GPIO as GPIO
import socket
import subprocess
import logging

# --- Adafruit CircuitPython DHT 用 -----------------------------------------
import board                       # ← NEW
import adafruit_dht                # ← NEW
# ---------------------------------------------------------------------------

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
import matplotlib.pyplot as plt
import pandas as pd

# reconnect_wifiモジュールをインポート
from reconnect_wifi import is_connected, restart_wifi

# =============================================================================
# ロギング設定
# =============================================================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('temp_humid_notifier.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

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

# ネットワーク診断用設定
ROUTER_IP = '192.168.1.1'          # ルーターのIPアドレス（環境に合わせて変更）
DNS_SERVERS = ['8.8.8.8', '8.8.4.4']  # GoogleのDNSサーバー
TEST_DOMAINS = ['api.slack.com', 'www.google.com']  # 疎通確認用ドメイン
# =============================================================================

# 保留メッセージとアラート用のキュー
pending_messages = []
pending_alerts = []

# ネットワーク状態追跡
network_status = {
    'last_check': None,
    'last_successful': None,
    'failures': 0,
    'dns_failures': 0,
    'internet_failures': 0,
    'wifi_failures': 0,
    'last_error': None,
    'recovery_attempts': 0
}

def diagnose_network_issue():
    """
    ネットワーク接続問題の原因を診断し、結果を返す

    Returns:
        dict: 診断結果と推奨される対処法
    """
    result = {
        'wifi_connected': False,
        'router_reachable': False,
        'internet_reachable': False,
        'dns_working': False,
        'slack_reachable': False,
        'error_type': None,
        'recommendation': None,
        'details': {}
    }

    # 1. WiFi接続確認
    try:
        wifi_status = subprocess.run(['iwconfig', 'wlan0'],
                                    capture_output=True,
                                    text=True,
                                    check=False)

        if "ESSID:" in wifi_status.stdout and "Not-Associated" not in wifi_status.stdout:
            result['wifi_connected'] = True
            # WiFi信号強度を抽出
            import re
            signal_match = re.search(r'Signal level=(-\d+) dBm', wifi_status.stdout)
            if signal_match:
                signal_level = int(signal_match.group(1))
                result['details']['wifi_signal'] = signal_level
                if signal_level < -70:
                    result['details']['wifi_quality'] = 'poor'
                    result['recommendation'] = 'WiFiの信号強度が弱いです。アクセスポイントに近づくか、アンテナの向きを調整してください。'
                else:
                    result['details']['wifi_quality'] = 'good'
        else:
            result['error_type'] = 'wifi_disconnected'
            result['recommendation'] = 'WiFiが切断されています。ネットワーク設定を確認してください。'
            network_status['wifi_failures'] += 1
            return result
    except Exception as e:
        logger.error(f"WiFi状態確認中にエラー: {e}")
        result['error_type'] = 'wifi_check_error'
        result['recommendation'] = 'WiFi状態の確認中にエラーが発生しました。'
        return result

    # 2. ルーターへの疎通確認
    try:
        ping_router = subprocess.run(['ping', '-c', '1', '-W', '2', ROUTER_IP],
                                    capture_output=True,
                                    check=False)
        if ping_router.returncode == 0:
            result['router_reachable'] = True
        else:
            result['error_type'] = 'router_unreachable'
            result['recommendation'] = 'ルーターに接続できません。WiFi接続は確立していますが、ローカルネットワークに問題があります。'
            return result
    except Exception as e:
        logger.error(f"ルータ疎通確認中にエラー: {e}")

    # 3. インターネット接続確認
    try:
        ping_internet = subprocess.run(['ping', '-c', '1', '-W', '3', '8.8.8.8'],
                                      capture_output=True,
                                      check=False)
        if ping_internet.returncode == 0:
            result['internet_reachable'] = True
        else:
            result['error_type'] = 'internet_unreachable'
            result['recommendation'] = 'インターネットに接続できません。ルーターのインターネット接続を確認してください。'
            network_status['internet_failures'] += 1
            return result
    except Exception as e:
        logger.error(f"インターネット疎通確認中にエラー: {e}")

    # 4. DNS解決確認
    try:
        for domain in TEST_DOMAINS:
            try:
                socket.getaddrinfo(domain, 80)
                result['dns_working'] = True
                break
            except socket.gaierror:
                continue

        if not result['dns_working']:
            result['error_type'] = 'dns_failure'
            result['recommendation'] = 'DNSの解決に失敗しています。DNSサーバーを確認・変更してください。'
            network_status['dns_failures'] += 1

            # DNSの代替サーバーが設定されていない場合はGoogleのDNSサーバーを指定するコマンドを提示
            try:
                with open('/etc/resolv.conf', 'r') as f:
                    resolv_conf = f.read()
                    if not any(dns in resolv_conf for dns in DNS_SERVERS):
                        result['recommendation'] += f" /etc/resolv.confにGoogle DNSを追加することを検討してください。"
            except:
                pass

            return result
    except Exception as e:
        logger.error(f"DNS確認中にエラー: {e}")

    # 5. Slackサーバーへの疎通確認
    try:
        try:
            socket.getaddrinfo('api.slack.com', 443)
            result['slack_reachable'] = True
        except socket.gaierror:
            result['error_type'] = 'slack_unreachable'
            result['recommendation'] = 'Slackサーバーに接続できません。一時的なSlackのサービス障害かもしれません。'
            return result
    except Exception as e:
        logger.error(f"Slack疎通確認中にエラー: {e}")

    # すべてOKの場合
    if (result['wifi_connected'] and result['router_reachable'] and
        result['internet_reachable'] and result['dns_working'] and result['slack_reachable']):
        result['recommendation'] = 'ネットワーク状態は良好です。'

    return result

def handle_network_issue():
    """
    ネットワーク問題を診断し、問題の種類に応じた対処を行う

    Returns:
        bool: 問題が解決したかどうか
    """
    current_time = datetime.datetime.now()

    # 前回の確認から一定時間経過していない場合はスキップ
    if (network_status['last_check'] and
        (current_time - network_status['last_check']).total_seconds() < 60):
        return False

    network_status['last_check'] = current_time
    network_status['failures'] += 1

    # 診断実行
    logger.info("ネットワーク問題を診断しています...")
    diagnosis = diagnose_network_issue()

    logger.info(f"診断結果: {diagnosis['error_type']}")
    logger.info(f"推奨対処: {diagnosis['recommendation']}")

    network_status['last_error'] = diagnosis['error_type']

    # 問題の種類に応じた対処
    if diagnosis['error_type'] == 'wifi_disconnected':
        logger.info("WiFi接続が切断されています。再接続を試みます...")
        if restart_wifi():
            logger.info("WiFi再接続に成功しました")
            network_status['recovery_attempts'] += 1
            return True
        else:
            logger.error("WiFi再接続に失敗しました")
            return False

    elif diagnosis['error_type'] == 'dns_failure':
        logger.info("DNS解決に問題があります。DNSキャッシュをクリアして代替DNSを設定します...")
        try:
            # DNSキャッシュクリア (Linuxのnscdが実行されている場合)
            subprocess.run(['sudo', 'systemctl', 'restart', 'nscd'],
                          check=False, capture_output=True)
        except:
            pass

        # 一時的にGoogle DNSを使用
        try:
            dns_config = f"nameserver {DNS_SERVERS[0]}\nnameserver {DNS_SERVERS[1]}\n"
            with open('/tmp/resolv.conf.temp', 'w') as f:
                f.write(dns_config)
            subprocess.run(['sudo', 'cp', '/tmp/resolv.conf.temp', '/etc/resolv.conf'],
                          check=False, capture_output=True)
            logger.info("一時的にGoogle DNSを設定しました")
            network_status['recovery_attempts'] += 1
            return True
        except Exception as e:
            logger.error(f"DNS設定変更中にエラー: {e}")
            return False

    elif diagnosis['error_type'] == 'internet_unreachable' or diagnosis['error_type'] == 'router_unreachable':
        # ネットワークインターフェースの再起動を試みる
        logger.info("ネットワークインターフェースを再起動します...")
        try:
            subprocess.run(['sudo', 'ifconfig', 'wlan0', 'down'], check=False)
            time.sleep(2)
            subprocess.run(['sudo', 'ifconfig', 'wlan0', 'up'], check=False)
            time.sleep(5)

            # ネットワークサービスも再起動
            if network_status['failures'] > 2:
                logger.info("ネットワークサービスを再起動します...")
                subprocess.run(['sudo', 'systemctl', 'restart', 'networking'], check=False)
                time.sleep(10)

            network_status['recovery_attempts'] += 1
            return is_connected()  # 接続確認
        except Exception as e:
            logger.error(f"ネットワークインターフェース再起動中にエラー: {e}")
            return False

    # すべての対処が失敗、または他の問題の場合
    if not diagnosis['error_type']:
        network_status['failures'] = 0  # 問題なし
        return True

    return False


def send_with_retry(func, max_retries=3, *args, **kwargs):
    """
    ネットワークエラーが発生した場合に再試行するラッパー関数

    Parameters:
        func: 実行する関数（Slack APIコールなど）
        max_retries: 最大再試行回数
        *args, **kwargs: 関数に渡す引数

    Returns:
        成功した場合は関数の戻り値、失敗した場合はNone
    """
    retries = 0

    while retries < max_retries:
        try:
            # ネットワーク接続を確認
            if not is_connected():
                logger.warning(f"ネットワーク接続がありません。再接続を試みます (試行 {retries+1}/{max_retries})...")

                # 接続問題を診断して対処
                if handle_network_issue():
                    logger.info("ネットワーク問題が解決しました")
                else:
                    logger.error("ネットワーク問題の解決に失敗しました")
                    time.sleep(30)  # 次の試行まで待機
                    retries += 1
                    continue

                time.sleep(5)  # 再接続後少し待機

            # 関数を実行
            return func(*args, **kwargs)

        except (socket.gaierror, socket.timeout) as e:
            logger.error(f"DNS/ネットワーク解決エラー: {e} - 再試行 {retries+1}/{max_retries}")

            # 接続問題を診断して対処
            handle_network_issue()
            time.sleep(10 * (retries + 1))  # エラー後の待機時間（再試行ごとに増加）
            retries += 1

        except SlackApiError as e:
            # Slack APIエラーはリトライしない場合もある
            if hasattr(e, 'response') and e.response.get('error') in ['channel_not_found', 'invalid_auth']:
                logger.error(f"Slack APIエラー (再試行しません): {e.response.get('error')}")
                return None

            logger.error(f"Slack APIエラー: {e} - 再試行 {retries+1}/{max_retries}")
            time.sleep(5 * (retries + 1))
            retries += 1

        except Exception as e:
            logger.error(f"予期せぬエラー: {e}")
            traceback.print_exc()
            return None

    logger.error(f"最大試行回数 ({max_retries}) に達しました。操作を中止します")

    # 長時間接続できない場合のレポート生成
    if network_status['failures'] > 5:
        generate_network_report()

    return None

def generate_network_report():
    """
    ネットワーク問題のレポートを生成し、ログに記録する
    """
    try:
        report = ["========== ネットワーク診断レポート =========="]
        report.append(f"診断時刻: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        report.append(f"接続失敗回数: {network_status['failures']}")
        report.append(f"DNS解決失敗: {network_status['dns_failures']}")
        report.append(f"インターネット接続失敗: {network_status['internet_failures']}")
        report.append(f"WiFi接続失敗: {network_status['wifi_failures']}")
        report.append(f"復旧試行回数: {network_status['recovery_attempts']}")
        report.append(f"最後のエラー: {network_status['last_error']}")

        # iwconfig結果
        try:
            iwconfig = subprocess.run(['iwconfig', 'wlan0'], capture_output=True, text=True, check=False)
            report.append("\n----- WiFi状態 (iwconfig) -----")
            report.append(iwconfig.stdout)
        except:
            report.append("WiFi状態の取得に失敗しました")

        # ifconfig結果
        try:
            ifconfig = subprocess.run(['ifconfig', 'wlan0'], capture_output=True, text=True, check=False)
            report.append("\n----- ネットワークインターフェース状態 (ifconfig) -----")
            report.append(ifconfig.stdout)
        except:
            report.append("ネットワークインターフェース状態の取得に失敗しました")

        # ルート情報
        try:
            route = subprocess.run(['ip', 'route'], capture_output=True, text=True, check=False)
            report.append("\n----- ルーティング情報 (ip route) -----")
            report.append(route.stdout)
        except:
            report.append("ルーティング情報の取得に失敗しました")

        # DNS設定
        try:
            with open('/etc/resolv.conf', 'r') as f:
                resolv_conf = f.read()
                report.append("\n----- DNS設定 (/etc/resolv.conf) -----")
                report.append(resolv_conf)
        except:
            report.append("DNS設定の取得に失敗しました")

        # ping結果
        try:
            ping_google = subprocess.run(['ping', '-c', '1', '-W', '2', '8.8.8.8'],
                                        capture_output=True, text=True, check=False)
            report.append("\n----- Google DNSへのping -----")
            report.append(ping_google.stdout)
        except:
            report.append("pingの実行に失敗しました")

        # まとめたレポートをログに出力
        report_text = "\n".join(report)
        logger.info(report_text)

        # レポートをファイルに保存
        with open('network_report.txt', 'w') as f:
            f.write(report_text)

    except Exception as e:
        logger.error(f"ネットワークレポート生成中にエラー: {e}")

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='温湿度モニタリングシステム')
    parser.add_argument('--save-dir',
                        default=SAVE_DIR,
                        help=f'ログファイルの保存先ディレクトリ（デフォルト: {SAVE_DIR}）')
    parser.add_argument('--debug', action='store_true',
                        help='デバッグモードを有効化')
    return parser.parse_args()

def verify_slack_connection(client: WebClient) -> bool:
    """
    Slackへの接続を確認し、接続テストメッセージを送信する
    send_with_retry関数を使用して堅牢性を向上
    """
    def do_auth_test():
        auth_test = client.auth_test()
        logger.info(f"Slack認証成功: {auth_test['user']}")
        return auth_test

    def send_test_message():
        return client.chat_postMessage(
            channel=SLACK_CHANNEL,
            text=f"センサーシステム起動: 接続テスト成功 {'[テストモード]' if TEST_MODE else ''}"
        )

    try:
        # 認証テスト
        auth_result = send_with_retry(do_auth_test)
        if not auth_result:
            return False

        # テストメッセージ送信
        msg_result = send_with_retry(send_test_message)
        return msg_result is not None

    except Exception as e:
        logger.error(f"Slack接続エラー: {e}")
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
        logger.warning("センサーからのデータ取得に失敗しました。再試行します...")
        return None, None
    except RuntimeError as e:
        # 読み取り失敗はよく起こるのでログだけ
        logger.debug(f"DHT 取得失敗: {e}")
        return None, None
    except Exception as e:
        # その他クリティカルな例外はセンサーをリセット
        logger.error(f"DHT 重大エラー: {e}")
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
        logger.error(f"CSV書き込みエラー: {e}")


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
            logger.warning("グラフ作成用のデータがありません")
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
        logger.error(f"グラフ作成エラー: {str(e)}")
        traceback.print_exc()
        return False

def send_slack_files(client, graph_path, csv_path, title_prefix):
    """
    Slackのファイルアップロード機能を使って、グラフ画像とCSVファイルをアップロードする。
    send_with_retry関数を使用して堅牢性を向上
    """
    try:
        # ファイルの存在確認
        if not os.path.exists(graph_path):
            logger.error(f"エラー: グラフファイルが存在しません: {graph_path}")
            return False
        if not os.path.exists(csv_path):
            logger.error(f"エラー: CSVファイルが存在しません: {csv_path}")
            return False

        logger.info(f"グラフファイルサイズ: {os.path.getsize(graph_path)} bytes")
        logger.info(f"CSVファイルサイズ: {os.path.getsize(csv_path)} bytes")

        # 使用するチャンネルを決定 (channel_idが空の場合はSLACK_CHANNELを使用)
        target_channel = channel_id if channel_id else SLACK_CHANNEL
        logger.info(f"使用するチャンネル: {target_channel}")

        # グラフファイル送信（send_with_retryを使用）
        def upload_graph():
            return client.files_upload_v2(
                channels=[target_channel],  # チャンネルIDをリストとして渡す
                file=graph_path,
                title=f"{title_prefix} - グラフ"
            )

        # CSVファイル送信（send_with_retryを使用）
        def upload_csv():
            return client.files_upload_v2(
                channels=[target_channel],
                file=csv_path,
                title=f"{title_prefix} - データ"
            )

        # ファイル送信を実行
        graph_result = send_with_retry(upload_graph)
        if not graph_result:
            logger.error("グラフファイルの送信に失敗しました")
            return False

        csv_result = send_with_retry(upload_csv)
        if not csv_result:
            logger.error("CSVファイルの送信に失敗しました")
            return False

        return True
    except Exception as e:
        logger.error(f"ファイル送信中に予期せぬエラーが発生しました: {str(e)}")
        traceback.print_exc()
        return False

def send_slack_message(client, message):
    """
    Slackにメッセージを送信する関数。
    ネットワーク接続が切れている場合は保留キューに追加し、
    接続が回復したら送信する。
    """
    global pending_messages

    def do_send_message(text):
        return client.chat_postMessage(
            channel=SLACK_CHANNEL,
            text=text
        )

    # 保留メッセージの送信を試みる
    if pending_messages:
        logger.info(f"{len(pending_messages)}件の保留メッセージがあります。送信を試みます...")
        temp_pending = pending_messages.copy()
        pending_messages = []

        for pending_msg in temp_pending:
            result = send_with_retry(do_send_message, max_retries=2, text=pending_msg)
            if result is None:
                # 送信に失敗したメッセージは再度キューに追加
                pending_messages.append(pending_msg)

    # 現在のメッセージを送信
    result = send_with_retry(do_send_message, text=message)
    if result is None:
        logger.info(f"メッセージを保留キューに追加します: {message}")
        pending_messages.append(message)
        return False
    return True

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
        if args.debug:
            logger.setLevel(logging.DEBUG)

        os.makedirs(args.save_dir, exist_ok=True)
        csv_path = os.path.join(args.save_dir, CSV_FILENAME)

        # 起動時のネットワーク状態を確認
        logger.info("起動時のネットワーク状態を確認しています...")
        diagnosis = diagnose_network_issue()
        if diagnosis['error_type']:
            logger.warning(f"ネットワークに問題があります: {diagnosis['error_type']}")
            logger.info(f"推奨対処: {diagnosis['recommendation']}")

            # 問題を自動修正
            if handle_network_issue():
                logger.info("ネットワーク問題を解決しました")
            else:
                logger.warning("ネットワーク問題の解決に失敗しました。プログラムは続行します。")

        # Slackクライアントの初期化
        client = WebClient(token=SLACK_TOKEN)
        # Slack接続テスト
        if not verify_slack_connection(client):
            logger.error("Slackへの接続に失敗しました。SLACK_TOKENとSLACK_CHANNELの設定を確認してください。")
            logger.info("接続エラーですが、データの記録を継続します。Slackへの通知は接続が回復次第再開されます。")
        else:
            logger.info("Slack接続テスト成功")

        # 初回実行時にCSVファイルがなければヘッダーを追加
        if not os.path.exists(csv_path):
            with open(csv_path, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(['timestamp', 'temperature', 'humidity'])
            logger.info(f"CSVファイルを作成しました: {csv_path}")

        # レポート送信の基準時間などを変数に保持
        start_time = datetime.datetime.now()
        ten_min_report_sent = False

        # 長期レポートの初期時間を現在時間から1日前に設定して早く送信できるようにする
        last_weekly_report = start_time - datetime.timedelta(days=LONG_REPORT_INTERVAL - 0.1)

        if TEST_MODE:
            logger.info("テストモードでセンサー監視を開始します")
            send_slack_message(
                client,
                "テストモードでセンサー監視を開始します（実際のセンサーは使用しません）"
            )
        else:
            logger.info("センサー監視を開始します")

        error_count = 0  # センサー読み取りエラーのカウント
        max_errors = 5   # 連続エラーの許容回数

        # ネットワーク定期チェックの時間を記録
        last_network_check = datetime.datetime.now()

        while True:
            current_time = datetime.datetime.now()
            elapsed_minutes = (current_time - start_time).total_seconds() / 60

            # 1時間ごとにネットワーク状態を診断（問題がない場合も）
            if (current_time - last_network_check).total_seconds() > 3600:  # 1時間
                logger.info("定期ネットワーク診断を実行します...")
                diagnosis = diagnose_network_issue()
                if diagnosis['error_type']:
                    logger.warning(f"ネットワーク診断で問題を検出: {diagnosis['error_type']}")
                    handle_network_issue()
                else:
                    logger.info("ネットワーク状態は良好です")
                last_network_check = current_time

            # 10分経過時のレポート送信
            if elapsed_minutes >= SHORT_REPORT_INTERVAL and not ten_min_report_sent:
                graph_path = os.path.join(args.save_dir, '10min_graph.png')
                temp_csv = os.path.join(args.save_dir, '10min_data.csv')

                logger.info(f"{SHORT_REPORT_INTERVAL}分レポートを作成中...")
                if create_graph(csv_path, graph_path, start_time, current_time):
                    try:
                        pd.read_csv(csv_path, header=0).to_csv(temp_csv, index=False)
                        send_slack_files(client, graph_path, temp_csv, f"{SHORT_REPORT_INTERVAL}分間レポート")
                        logger.info(f"{SHORT_REPORT_INTERVAL}分レポートをSlackに送信しました")
                    except Exception as e:
                        logger.error(f"レポート送信中にエラーが発生しました: {str(e)}")
                        traceback.print_exc()

                ten_min_report_sent = True

            # 週次レポート
            time_since_last_report = (current_time - last_weekly_report).total_seconds()
            days_since_last_report = time_since_last_report / (24 * 3600)  # 秒数から日数を計算

            if days_since_last_report >= LONG_REPORT_INTERVAL:
                graph_path = os.path.join(args.save_dir, 'weekly_graph.png')
                temp_csv = os.path.join(args.save_dir, 'weekly_data.csv')

                logger.info(f"{LONG_REPORT_INTERVAL}日レポートを作成中... ({days_since_last_report:.2f}日経過)")
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
                            send_slack_message(
                                client,
                                f"{LONG_REPORT_INTERVAL}日間レポートを送信します"
                            )

                            send_slack_files(client, graph_path, temp_csv, f"{LONG_REPORT_INTERVAL}日間レポート")
                            logger.info(f"{LONG_REPORT_INTERVAL}日レポートをSlackに送信しました")
                        else:
                            logger.warning("レポート期間内にデータがありません")
                    except Exception as e:
                        logger.error(f"レポート送信中にエラーが発生しました: {str(e)}")
                        traceback.print_exc()

                # 次回レポート作成の基準を更新
                last_weekly_report = current_time

            # 通常の測定処理
            humidity, temperature = read_sensor()
            if humidity is not None and temperature is not None:
                save_to_csv(csv_path, humidity, temperature)
                logger.debug(f"[{current_time.strftime('%Y-%m-%d %H:%M:%S')}] 温度: {temperature}°C, 湿度: {humidity}%")

                # エラーカウントをリセット
                error_count = 0

                # しきい値チェックとアラート送信
                alerts = check_thresholds(temperature, humidity)
                for alert in alerts:
                    alert_text = f"{alert} {' [テストモード]' if TEST_MODE else ''}"
                    send_slack_message(client, alert_text)
                    logger.info(f"アラートをSlackに送信しました: {alert}")
            else:
                # センサー読み取りエラーの処理
                error_count += 1
                if error_count >= max_errors:
                    error_message = f"センサーの読み取りに連続で失敗しています ({error_count}回)。センサーの接続を確認してください。"
                    logger.error(error_message)
                    send_slack_message(client, error_message)

                    # テストモードの場合は、エラー後も続行する（テストデータを使用）
                    if not TEST_MODE:
                        error_count = 0  # エラーカウントをリセット

                logger.warning(f"センサー読み取りエラー ({error_count}/{max_errors})")

            time.sleep(CHECK_INTERVAL)

    except KeyboardInterrupt:
        logger.info("\n監視を終了します。")
    except Exception as e:
        error_message = f"予期せぬエラーが発生しました: {str(e)}"
        logger.error(error_message)
        traceback.print_exc()
        try:
            client = WebClient(token=SLACK_TOKEN)
            send_slack_message(client, error_message)
        except:
            pass
    finally:
        # プログラム終了時の後処理
        logger.info("リソースをクリーンアップしています...")

        # DHTデバイスが初期化されている場合は終了処理
        if not TEST_MODE and dht_device is not None:
            try:
                dht_device.exit()
                logger.info("DHT22センサー接続を終了しました")
            except:
                pass

        # GPIO設定をクリーンアップ
        try:
            GPIO.cleanup()
            logger.info("GPIOリソースをクリーンアップしました")
        except:
            pass

if __name__ == "__main__":
    main()
