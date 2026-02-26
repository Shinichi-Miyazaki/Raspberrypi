"""
温湿度モニタリングシステム - メインエントリーポイント。

センサー読み取り・Slack通知・ネットワーク管理・レポート生成の
各モジュールを組み合わせて動作する制御ファイル。

起動方法:
    python3 temp_humid_notifier.py                        # 通常起動
    python3 temp_humid_notifier.py --test-mode            # テストモード（センサー不要）
    python3 temp_humid_notifier.py --save-dir /home/pi/logs  # 保存先指定
    python3 temp_humid_notifier.py --debug                # デバッグログ有効
"""

import argparse
import atexit
import csv
import datetime
import logging
import os
import signal
import time
import traceback

# .envファイルが存在すれば環境変数として読み込む（python-dotenv）
# pip install python-dotenv でインストール可能。ファイルがなくてもエラーにならない
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from slack_sdk import WebClient

from config import load_config
from network import NetworkManager
from notifier import SlackNotifier
from reporter import send_long_report, send_short_report
from sensor import SensorReader

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
# ユーティリティ関数
# =============================================================================

def parse_args() -> argparse.Namespace:
    """コマンドライン引数をパースして返す"""
    parser = argparse.ArgumentParser(description='温湿度モニタリングシステム')
    parser.add_argument(
        '--save-dir',
        default='.',
        help='ログファイルの保存先ディレクトリ（デフォルト: カレントディレクトリ）'
    )
    parser.add_argument(
        '--debug',
        action='store_true',
        help='デバッグモードを有効化'
    )
    parser.add_argument(
        '--test-mode',
        action='store_true',
        help='テストモードを有効化（実センサー不要）'
    )
    return parser.parse_args()


def check_already_running(pid_file: str) -> None:
    """
    多重起動チェック。既に同じスクリプトが動いていたらエラーで終了する。
    Thonnyで止めずに再実行したとき、GPIO4が「already in use」になるのを防ぐ。
    """
    def remove_pid_file() -> None:
        """終了時にPIDファイルを削除するクリーンアップ処理"""
        try:
            if os.path.exists(pid_file):
                os.remove(pid_file)
        except Exception:
            pass

    if os.path.exists(pid_file):
        with open(pid_file) as f:
            old_pid = f.read().strip()
        # /proc/<PID> が存在すればプロセスはまだ生きている
        if os.path.exists(f'/proc/{old_pid}'):
            logger.error(
                f"既にプロセスが動いています (PID: {old_pid})。\n"
                f"  → Thonnyの場合: 「Stop」ボタンで前の実行を止めてから再実行してください。\n"
                f"  → ターミナルの場合: sudo kill {old_pid}\n"
                f"  → PIDファイル: {pid_file}"
            )
            raise SystemExit(1)
        else:
            # プロセスが死んでいるのにPIDファイルが残っていた（異常終了の残骸）
            logger.warning(f"古いPIDファイルを削除します (PID: {old_pid} は既に終了済み)")

    # 自分のPIDをファイルに書き込む
    with open(pid_file, 'w') as f:
        f.write(str(os.getpid()))

    # 正常終了・例外・Ctrl+C どのケースでも削除されるよう登録
    atexit.register(remove_pid_file)

    # ThonnyやsystemdのSIGTERM（強制停止）にも対応
    def handle_sigterm(sig, frame) -> None:
        logger.info("SIGTERMを受信しました。終了処理を行います...")
        remove_pid_file()
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, handle_sigterm)


def save_to_csv(csv_path: str, humidity: float, temperature: float) -> None:
    """測定値をCSVファイルに追記する"""
    timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    try:
        with open(csv_path, 'a', newline='') as f:
            csv.writer(f).writerow([timestamp, temperature, humidity])
    except Exception as e:
        logger.error(f"CSV書き込みエラー: {e}")


# =============================================================================
# メイン処理
# =============================================================================

def main() -> None:
    """
    メイン関数。プログラム全体の制御フローを担う。

      1. コマンドライン引数のパース・設定ロード
      2. 多重起動チェック
      3. センサー・ネットワーク・Slack各モジュールの初期化
      4. 定期的にセンサーを読み込み、温湿度を記録してアラートを送信
      5. 一定時間ごとにグラフ＋CSVレポートをSlackに送信
    """
    args = parse_args()
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    # 全設定を一括ロード
    (
        sensor_cfg,
        threshold_cfg,
        schedule_cfg,
        slack_cfg,
        path_cfg,
        test_cfg,
        network_cfg,
    ) = load_config(args)

    # 多重起動チェック（GPIO「already in use」の防止）
    check_already_running(path_cfg.pid_file)

    # 保存先ディレクトリを準備
    os.makedirs(path_cfg.save_dir, exist_ok=True)
    csv_path = os.path.join(path_cfg.save_dir, path_cfg.csv_filename)

    # センサーを初期化（テストモードでは実センサーを使わない）
    sensor = SensorReader(sensor_cfg, test_cfg, threshold_cfg)

    # ネットワークマネージャを初期化
    network = NetworkManager(network_cfg)

    # Slackクライアントとノーティファイアを初期化
    slack_client = WebClient(token=slack_cfg.token)
    notifier = SlackNotifier(slack_client, slack_cfg, test_cfg.enabled)

    # 起動時のネットワーク状態を確認
    logger.info("起動時のネットワーク状態を確認しています...")
    diagnosis = network.diagnose()
    if diagnosis['error_type']:
        logger.warning(f"ネットワークに問題があります: {diagnosis['error_type']}")
        logger.info(f"推奨対処: {diagnosis['recommendation']}")
        if network.handle_issue():
            logger.info("ネットワーク問題を解決しました")
        else:
            logger.warning("ネットワーク問題の解決に失敗しました。プログラムは続行します。")

    # Slack接続テスト
    if not notifier.verify_connection():
        logger.error(
            "Slackへの接続に失敗しました。"
            "SLACK_TOKEN と SLACK_CHANNEL の設定を確認してください。"
        )
        logger.info("接続エラーですが、データの記録を継続します。接続回復後に通知を再開します。")
    else:
        logger.info("Slack接続テスト成功")

    # 初回実行時にCSVファイルがなければヘッダー行を作成
    if not os.path.exists(csv_path):
        with open(csv_path, 'w', newline='') as f:
            csv.writer(f).writerow(['timestamp', 'temperature', 'humidity'])
        logger.info(f"CSVファイルを作成しました: {csv_path}")

    # メインループの開始時刻と状態変数の初期化
    start_time = datetime.datetime.now()
    short_report_sent = False
    # 長期レポートを0.1日後に早めに送信できるよう、基準時刻を少し前にずらす
    last_long_report_time = start_time - datetime.timedelta(
        days=schedule_cfg.long_report_interval_days - 0.1
    )

    if test_cfg.enabled:
        logger.info("テストモードでセンサー監視を開始します")
        notifier.send("テストモードでセンサー監視を開始します（実際のセンサーは使用しません）")
    else:
        logger.info("センサー監視を開始します")

    # 連続センサーエラーのカウント（上限に達したらSlackに通知）
    error_count = 0
    max_consecutive_errors = 5

    try:
        while True:
            current_time = datetime.datetime.now()
            elapsed_minutes = (current_time - start_time).total_seconds() / 60

            # 1時間ごとに定期ネットワーク診断を実行
            if network.should_run_periodic_check(interval_sec=3600):
                logger.info("定期ネットワーク診断を実行します...")
                diagnosis = network.diagnose()
                # diagnose() は last_check を更新しないので手動で記録する
                network.state.last_check = current_time
                if diagnosis['error_type']:
                    logger.warning(f"ネットワーク診断で問題を検出: {diagnosis['error_type']}")
                    network.handle_issue()
                else:
                    logger.info("ネットワーク状態は良好です")

            # 短期レポート（起動から short_report_interval_min 分後に1回だけ送信）
            if elapsed_minutes >= schedule_cfg.short_report_interval_min and not short_report_sent:
                send_short_report(
                    notifier, csv_path, path_cfg.save_dir, threshold_cfg,
                    start_time, current_time, schedule_cfg.short_report_interval_min,
                )
                short_report_sent = True

            # 長期レポート（long_report_interval_days 日ごとに送信）
            days_since_last_report = (
                (current_time - last_long_report_time).total_seconds() / (24 * 3600)
            )
            if days_since_last_report >= schedule_cfg.long_report_interval_days:
                send_long_report(
                    notifier, csv_path, path_cfg.save_dir, threshold_cfg,
                    last_long_report_time, current_time, schedule_cfg.long_report_interval_days,
                )
                last_long_report_time = current_time

            # センサー読み取りとCSV記録
            humidity, temperature = sensor.read()
            if humidity is not None and temperature is not None:
                save_to_csv(csv_path, humidity, temperature)
                logger.info(
                    f"[{current_time.strftime('%Y-%m-%d %H:%M:%S')}] "
                    f"温度: {temperature}°C, 湿度: {humidity}%"
                )
                error_count = 0
                # 閾値チェックとアラート送信
                notifier.check_and_alert(temperature, humidity, threshold_cfg)
            else:
                error_count += 1
                logger.warning(f"センサー読み取りエラー ({error_count}/{max_consecutive_errors})")
                if error_count >= max_consecutive_errors:
                    error_msg = (
                        f"センサーの読み取りに連続で失敗しています ({error_count}回)。"
                        "センサーの接続を確認してください。"
                    )
                    logger.error(error_msg)
                    notifier.send(error_msg)
                    error_count = 0  # カウントをリセットして次の通知まで待機

            time.sleep(schedule_cfg.check_interval_sec)

    except KeyboardInterrupt:
        logger.info("\n監視を終了します。")
    except Exception as e:
        error_message = f"予期せぬエラーが発生しました: {e}"
        logger.error(error_message)
        traceback.print_exc()
        try:
            notifier.send(error_message)
        except Exception:
            pass
    finally:
        # センサーのリソースを解放（GPIOクリーンアップ）
        sensor.cleanup()


if __name__ == "__main__":
    main()
