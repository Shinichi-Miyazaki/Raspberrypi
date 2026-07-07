"""
温湿度センサークライアント（Pi側・全デバイス共通）。

DHT22センサーで温湿度を10分ごとに測定し、
  1. ローカルCSVに追記する（送信バッファ兼、NAS障害時の予備）
  2. 未送信分をNAS（Synology共有フォルダ）へ送信する

このプログラムはSlackに直接通知しない。アラート判定・週次レポートは
NAS上のデータを読むコレクター（collector/collector.py）が担当する。
そのためこのPiはSlackトークン等の秘密情報を持たない
（Pi侵害時の被害を最小化する設計）。

起動方法:
    # 通常運用: NASの共有フォルダをSMBマウントした先を指定する（OPERATIONS.md参照）
    python3 temp_humid_notifier.py --device-name 246 \
        --nas-target /mnt/sensor_data/incoming

    # SFTP送信を使う場合（user@host:/path 形式。SSH鍵の設定が別途必要）
    python3 temp_humid_notifier.py --device-name 246 \
        --nas-target sensor-uploader@192.168.1.10:/sensor_data/incoming

    # テストモード（センサー不要・任意のローカルフォルダで動作確認）
    python3 temp_humid_notifier.py --test-mode --device-name test246 \
        --nas-target /tmp/fake_nas/incoming
"""

import argparse
import atexit
import csv
import datetime
import logging
import os
import random
import re
import shutil
import signal
import socket
import subprocess
import threading
import time
import traceback

import board
import adafruit_dht

# =============================================================================
# 設定パラメータ（必要に応じて変更）
# =============================================================================

DHT_PIN = board.D4                  # BCM4ピン（物理ピン7）に接続されたDHT22

CHECK_INTERVAL_SEC = 600            # センサー測定間隔（秒）= 10分

CSV_FILENAME = 'temperature_log.csv'
UPLOAD_STATE_FILENAME = 'upload_state.txt'   # 送信済み行数を記録するファイル
DEFAULT_SAVE_DIR = '/home/harry.one/Desktop/data'
DEFAULT_SSH_KEY = '~/.ssh/nas_upload_key'    # NAS送信専用のSSH秘密鍵
TRANSFER_TIMEOUT_SEC = 60           # SFTP送信のタイムアウト（秒）

# テストモード用ダミーデータのパラメータ
TEST_TEMP_BASE = 20.0
TEST_HUMID_BASE = 50.0
TEST_DATA_VARIATION = True          # Trueにすると毎回少しランダムなデータが生成される

# 多重起動防止用PIDファイルのパス（Linuxの /tmp 以下に置く）
PID_FILE = '/tmp/temp_humid_notifier.pid'

# =============================================================================


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
# GPIO / センサー管理
# =============================================================================

# グローバル変数でデバイスを保持する。
# atexit や finally ブロックからクリーンアップするために必要。
_dht_device = None


def _cleanup_sensor() -> None:
    """
    DHT22センサーのリソースを解放する。

    プログラムの終了方法（正常終了・例外・Ctrl+C・SIGTERM）を問わず、
    必ず呼ばれるよう atexit.register と try/finally の両方で登録する。

    dht_device.exit() を呼ばないと、次回起動時に
    「unable to set line to input」エラーが出てGPIOが使えなくなり、
    Raspberry Piの再起動が必要になる。
    """
    global _dht_device
    if _dht_device is not None:
        try:
            _dht_device.exit()
            logger.info("DHT22センサー接続を終了しました")
        except Exception as e:
            logger.warning(f"センサー終了時のエラー（無視して続行）: {e}")
        # 二重呼び出しを防ぐために None に戻す
        _dht_device = None


# atexitに登録：正常終了・例外終了いずれでも呼ばれる
atexit.register(_cleanup_sensor)


def _init_sensor() -> bool:
    """
    DHT22センサーを初期化する。

    Returns:
        True: 初期化成功、False: 初期化失敗
    """
    global _dht_device
    logger.info(f"DHT22センサーを初期化します (ピン: {DHT_PIN})...")
    try:
        # use_pulseio=False は adafruit_circuitpython_dht との相性が悪いため省略
        _dht_device = adafruit_dht.DHT22(DHT_PIN)
        logger.info("DHT22センサーの初期化に成功しました")
        return True
    except Exception as e:
        logger.error(f"DHT22センサーの初期化に失敗しました: {e}")
        logger.error(
            "  【よくある原因と対処法】\n"
            "  1. 前回の実行でGPIOが解放されていない（異常終了が原因）\n"
            "       → sudo python3 gpio_reset.py を実行してください\n"
            "  2. 多重起動している\n"
            "       → ps aux | grep temp_humid で確認し、sudo kill <PID> で終了\n"
            "  3. センサーの配線が外れている\n"
            "       → DHT22のDATAピンがGPIO4（物理ピン7）に接続されているか確認"
        )
        _dht_device = None
        return False


def _read_sensor() -> tuple:
    """
    DHT22センサーから温湿度を10秒のタイムアウト付きで読み取る。

    DHT22は稀に .temperature の呼び出しで無限ブロックすることがある。
    threading でタイムアウトを設けることでプログラムの凍結を防ぐ。

    Returns:
        (humidity, temperature) のタプル。取得失敗時は (None, None)
    """
    global _dht_device
    if _dht_device is None:
        return None, None

    # スレッド間で結果・例外を共有するための辞書
    result = {'temperature': None, 'humidity': None, 'error': None}

    def do_read():
        try:
            result['temperature'] = _dht_device.temperature
            result['humidity'] = _dht_device.humidity
        except Exception as e:
            result['error'] = e

    thread = threading.Thread(target=do_read, daemon=True)
    thread.start()
    thread.join(timeout=10)  # 10秒で読み取りをあきらめる

    if thread.is_alive():
        # タイムアウト：GPIOが応答していない
        logger.warning("センサー読み取りが10秒でタイムアウトしました。再試行します...")
        return None, None

    if result['error'] is not None:
        e = result['error']
        if isinstance(e, RuntimeError):
            # 読み取り失敗はDHT22では頻繁に起こる正常な一時エラー
            logger.debug(f"DHT 取得失敗（一時的エラー）: {e}")
        else:
            # その他の重大エラーはセンサーをリセットして再初期化を試みる
            logger.error(f"DHT 重大エラー: {e}")
            try:
                _dht_device.exit()
            except Exception:
                pass
            _dht_device = None
            time.sleep(2)
            _init_sensor()
        return None, None

    temperature = result['temperature']
    humidity = result['humidity']
    if humidity is not None and temperature is not None:
        return round(humidity, 3), round(temperature, 3)

    logger.warning("センサーからのデータ取得に失敗しました。再試行します...")
    return None, None


def _generate_test_data() -> tuple:
    """テストモード用のダミーデータを生成する"""
    temperature = TEST_TEMP_BASE
    humidity = TEST_HUMID_BASE

    if TEST_DATA_VARIATION:
        temperature += random.uniform(-0.5, 0.5)
        humidity += random.uniform(-2.0, 2.0)

    return round(humidity, 3), round(temperature, 3)


# =============================================================================
# CSV記録
# =============================================================================

def save_to_csv(csv_path: str, humidity: float, temperature: float) -> None:
    """測定値をCSVファイルに追記する"""
    timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    try:
        with open(csv_path, 'a', newline='') as f:
            csv.writer(f).writerow([timestamp, temperature, humidity])
    except Exception as e:
        logger.error(f"CSV書き込みエラー: {e}")


# =============================================================================
# NASへのデータ送信
# =============================================================================

def _load_uploaded_row_count(state_path: str) -> int:
    """送信済みのデータ行数をステートファイルから読む。無ければ0（＝全行未送信）"""
    try:
        if os.path.exists(state_path):
            with open(state_path) as f:
                return int(f.read().strip())
    except Exception as e:
        logger.warning(f"送信状態ファイルの読み込みに失敗しました（最初から再送します）: {e}")
    return 0


def _save_uploaded_row_count(state_path: str, count: int) -> None:
    """送信済みのデータ行数をステートファイルに保存する"""
    try:
        with open(state_path, 'w') as f:
            f.write(str(count))
    except Exception as e:
        logger.error(f"送信状態ファイルの保存に失敗しました: {e}")


def _is_remote_target(nas_target: str) -> bool:
    """--nas-target が user@host:/path 形式（SFTP送信）かどうかを判定する"""
    return re.match(r'^[^/@\s]+@[^:@\s]+:', nas_target) is not None


def _transfer_via_sftp(local_path: str, nas_target: str, device_name: str,
                       remote_filename: str, ssh_key: str) -> bool:
    """
    チャンクCSVをSFTPでNASに送信する。

    sftpのバッチモードを使い、デバイス用ディレクトリの作成（既にあれば無視）と
    ファイルのputを1接続で行う。scpではなくsftpを使うのは、
    リモート側にディレクトリを作成できるのがsftpだけのため。

    Returns:
        True: 送信成功、False: 失敗
    """
    # user@host:/base/path を接続先とリモートパスに分解する
    host_part, base_path = nas_target.split(':', 1)
    remote_dir = f"{base_path.rstrip('/')}/{device_name}"

    # バッチコマンド。-mkdir の先頭の「-」は「失敗しても続行」の意味
    # （2回目以降はディレクトリが既に存在してエラーになるため）
    batch_commands = f"-mkdir {remote_dir}\nput {local_path} {remote_dir}/{remote_filename}\n"

    try:
        completed = subprocess.run(
            [
                'sftp',
                '-i', os.path.expanduser(ssh_key),
                '-o', 'BatchMode=yes',            # パスワードを聞かれたら失敗させる（無人運用のため）
                '-o', 'ConnectTimeout=15',
                '-b', '-',                        # バッチコマンドを標準入力から渡す
                host_part,
            ],
            input=batch_commands,
            capture_output=True,
            text=True,
            timeout=TRANSFER_TIMEOUT_SEC,
        )
    except FileNotFoundError:
        logger.error("sftpコマンドが見つかりません。openssh-clientをインストールしてください")
        return False
    except subprocess.TimeoutExpired:
        logger.error(f"NASへの送信が{TRANSFER_TIMEOUT_SEC}秒でタイムアウトしました")
        return False

    if completed.returncode != 0:
        logger.error(
            f"NASへの送信に失敗しました (exit={completed.returncode}): "
            f"{completed.stderr.strip()}"
        )
        return False
    return True


def _transfer_via_local_copy(local_path: str, nas_target: str, device_name: str,
                             remote_filename: str) -> bool:
    """
    チャンクCSVをディレクトリにコピーする。

    --nas-target に通常のディレクトリパスを渡した場合に使われる。
    通常運用ではNASのSMBマウント先（/mnt/sensor_data/incoming）を指定する。
    テスト時は任意のローカルフォルダも指定できる。
    """
    # 送信先ベースフォルダ（incoming）はNAS上にのみ存在する。
    # マウントが外れていると /mnt/sensor_data は空になり incoming が見えないため、
    # ここで検出できる。無い場合に作ってしまうと、SDカード上の隠れたフォルダに
    # 書き込まれて「送信成功」と誤記録される事故になるので、作らずに失敗させる
    if not os.path.isdir(nas_target):
        logger.error(
            f"送信先フォルダが見つかりません: {nas_target}\n"
            "  NASのマウントを確認してください: ls /mnt/sensor_data\n"
            "  マウントし直す場合: sudo mount -a"
        )
        return False

    destination_dir = os.path.join(nas_target, device_name)
    try:
        os.makedirs(destination_dir, exist_ok=True)
        shutil.copy2(local_path, os.path.join(destination_dir, remote_filename))
        return True
    except Exception as e:
        logger.error(f"ローカルコピーに失敗しました: {e}")
        return False


def upload_unsent_data(csv_path: str, save_dir: str, device_name: str,
                       nas_target: str, ssh_key: str) -> None:
    """
    ローカルCSVの未送信行をチャンクCSVにまとめてNASへ送信する。

    仕組み:
      - 送信済みのデータ行数をステートファイルに記録しておき、それ以降の行だけを送る
      - チャンクのファイル名は「デバイス名_日時.csv」で毎回一意 → リモートを上書きしない
      - 送信に失敗しても行数を進めないため、次の測定サイクルでまとめて再送される
        （ローカルCSVが残っている限りデータは欠損しない）
      - 初回起動時は全行が未送信扱いになるので、既存データの移行も自動で行われる
    """
    state_path = os.path.join(save_dir, UPLOAD_STATE_FILENAME)
    uploaded_count = _load_uploaded_row_count(state_path)

    # ローカルCSVを読み、未送信のデータ行を抜き出す
    try:
        with open(csv_path, newline='') as f:
            rows = list(csv.reader(f))
    except Exception as e:
        logger.error(f"送信用のCSV読み込みに失敗しました: {e}")
        return

    header, data_rows = rows[0], rows[1:]
    unsent_rows = data_rows[uploaded_count:]
    if not unsent_rows:
        logger.debug("未送信のデータはありません")
        return

    # 未送信分をチャンクCSVとして書き出す
    # マイクロ秒まで含めるのは、同一秒内の連続送信でファイル名が衝突しないようにするため
    timestamp_label = datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    remote_filename = f"{device_name}_{timestamp_label}.csv"
    chunk_path = os.path.join(save_dir, 'outbox_chunk.csv')
    try:
        with open(chunk_path, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(header)
            writer.writerows(unsent_rows)
    except Exception as e:
        logger.error(f"送信用チャンクの作成に失敗しました: {e}")
        return

    # 送信（リモート形式ならSFTP、ディレクトリパスならローカルコピー）
    if _is_remote_target(nas_target):
        success = _transfer_via_sftp(chunk_path, nas_target, device_name, remote_filename, ssh_key)
    else:
        success = _transfer_via_local_copy(chunk_path, nas_target, device_name, remote_filename)

    if success:
        _save_uploaded_row_count(state_path, uploaded_count + len(unsent_rows))
        logger.info(f"NASへ{len(unsent_rows)}行を送信しました: {remote_filename}")
    else:
        logger.warning("送信に失敗したため、次の測定サイクルで再送します")


# =============================================================================
# 多重起動防止
# =============================================================================

def check_already_running() -> None:
    """
    多重起動チェック。既に同じスクリプトが動いていたらエラーで終了する。
    Thonnyで止めずに再実行したとき、GPIO4が「already in use」になるのを防ぐ。
    """
    def remove_pid_file() -> None:
        try:
            if os.path.exists(PID_FILE):
                os.remove(PID_FILE)
        except Exception:
            pass

    if os.path.exists(PID_FILE):
        with open(PID_FILE) as f:
            old_pid = f.read().strip()
        # /proc/<PID> が存在すればプロセスはまだ生きている（Linux専用の確認方法）
        if os.path.exists(f'/proc/{old_pid}'):
            logger.error(
                f"既にプロセスが動いています (PID: {old_pid})。\n"
                f"  → Thonnyの場合: 「Stop」ボタンで前の実行を止めてから再実行してください。\n"
                f"  → ターミナルの場合: sudo kill {old_pid}\n"
                f"  → PIDファイル: {PID_FILE}"
            )
            raise SystemExit(1)
        else:
            # プロセスが死んでいるのにPIDファイルが残っていた（異常終了の残骸）
            logger.warning(f"古いPIDファイルを削除します (PID: {old_pid} は既に終了済み)")

    with open(PID_FILE, 'w') as f:
        f.write(str(os.getpid()))

    atexit.register(remove_pid_file)


# =============================================================================
# コマンドライン引数
# =============================================================================

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='温湿度センサークライアント')
    parser.add_argument(
        '--device-name',
        default=socket.gethostname(),
        help='このデバイスの識別名（例: 246）。NAS上のフォルダ名・ファイル名に使われる'
             '（デフォルト: ホスト名）'
    )
    parser.add_argument(
        '--nas-target',
        required=True,
        help='データ送信先。user@host:/path 形式ならSFTP送信、'
             'ディレクトリパスならローカルコピー（テスト用）。'
             '例: sensor-uploader@192.168.1.10:/sensor_data/incoming'
    )
    parser.add_argument(
        '--ssh-key',
        default=DEFAULT_SSH_KEY,
        help=f'NAS送信用のSSH秘密鍵のパス（デフォルト: {DEFAULT_SSH_KEY}）'
    )
    parser.add_argument(
        '--save-dir',
        default=DEFAULT_SAVE_DIR,
        help=f'ログファイルの保存先ディレクトリ（デフォルト: {DEFAULT_SAVE_DIR}）'
    )
    parser.add_argument(
        '--test-mode',
        action='store_true',
        help='テストモードを有効化（実センサー不要）'
    )
    parser.add_argument(
        '--debug',
        action='store_true',
        help='デバッグログを有効化'
    )
    return parser.parse_args()


# =============================================================================
# メイン処理
# =============================================================================

def main() -> None:
    """
    メイン関数。プログラム全体の制御フローを担う。

      1. コマンドライン引数のパース
      2. 多重起動チェック
      3. センサー初期化（テストモード時はスキップ）
      4. 10分ごとに測定 → ローカルCSVに追記 → 未送信分をNASへ送信
    """
    args = parse_args()
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    # 多重起動チェック（GPIO「already in use」の防止）
    check_already_running()

    # SIGTERMハンドラを登録（systemdやkillコマンドによる終了でもGPIOを解放する）
    def handle_sigterm(sig, frame) -> None:
        logger.info("SIGTERMを受信しました。終了処理を行います...")
        _cleanup_sensor()
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, handle_sigterm)

    # センサーを初期化（テストモードでは実センサーを使わない）
    if not args.test_mode:
        if not _init_sensor():
            raise SystemExit(1)

    # 保存先ディレクトリを準備
    os.makedirs(args.save_dir, exist_ok=True)
    csv_path = os.path.join(args.save_dir, CSV_FILENAME)

    # 初回実行時にCSVファイルがなければヘッダー行を作成
    if not os.path.exists(csv_path):
        with open(csv_path, 'w', newline='') as f:
            csv.writer(f).writerow(['timestamp', 'temperature', 'humidity'])
        logger.info(f"CSVファイルを作成しました: {csv_path}")

    mode_label = "テストモードで" if args.test_mode else ""
    logger.info(
        f"{mode_label}センサー監視を開始します "
        f"[デバイス名: {args.device_name}, 送信先: {args.nas_target}]"
    )

    error_count = 0
    max_consecutive_errors = 5

    try:
        while True:
            current_time = datetime.datetime.now()

            # センサー読み取りとCSV記録
            if args.test_mode:
                humidity, temperature = _generate_test_data()
            else:
                humidity, temperature = _read_sensor()

            if humidity is not None and temperature is not None:
                save_to_csv(csv_path, humidity, temperature)
                logger.info(
                    f"[{current_time.strftime('%Y-%m-%d %H:%M:%S')}] "
                    f"温度: {temperature}°C, 湿度: {humidity}%"
                )
                error_count = 0
            else:
                # 通知はしない（データが止まればコレクター側の欠測アラートが検出する）
                error_count += 1
                logger.warning(f"センサー読み取りエラー ({error_count}/{max_consecutive_errors})")
                if error_count >= max_consecutive_errors:
                    logger.error(
                        f"センサーの読み取りに連続で失敗しています ({error_count}回)。"
                        "配線とセンサーの状態を確認してください。"
                    )
                    error_count = 0  # ログの出しすぎを防ぐためリセット

            # 未送信データをNASへ送信（失敗しても次サイクルで自動再送）
            upload_unsent_data(csv_path, args.save_dir, args.device_name,
                               args.nas_target, args.ssh_key)

            logger.info(f"次の測定まで {CHECK_INTERVAL_SEC} 秒待機します...")
            time.sleep(CHECK_INTERVAL_SEC)

    except KeyboardInterrupt:
        logger.info("\n監視を終了します。")
    except Exception as e:
        logger.error(f"予期せぬエラーが発生しました: {e}")
        traceback.print_exc()
    finally:
        # どのような終了方法でもセンサーを正しく解放する
        # atexit でも呼ばれるが、二重呼び出しは _cleanup_sensor 内でガードしている
        _cleanup_sensor()


if __name__ == "__main__":
    main()
