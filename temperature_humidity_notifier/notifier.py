"""
Slack通知モジュール。

メッセージ送信・ファイルアップロード・アラート判定・リトライ処理を
SlackNotifier クラスに集約する。
"""

import datetime
import logging
import os
import socket
import time
import traceback
from typing import Callable, Optional

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from reconnect_wifi import is_connected

logger = logging.getLogger(__name__)


class SlackNotifier:
    """Slack通知の送信・リトライ・保留管理を担うクラス"""

    def __init__(self, client: WebClient, config, test_mode: bool = False) -> None:
        """
        Parameters:
            client: Slack WebClient インスタンス
            config: SlackConfig（token, channel 属性を持つ）
            test_mode: テストモードフラグ
        """
        self._client = client
        self._config = config
        self._test_mode = test_mode
        self._pending_messages: list[str] = []
        # アラート重複送信防止用：各アラート種別の最終送信時刻
        self._alert_last_sent: dict[str, Optional[datetime.datetime]] = {
            'temp_high': None,
            'temp_low': None,
            'humidity_high': None,
            'humidity_low': None,
        }

    # ------------------------------------------------------------------
    # 公開メソッド
    # ------------------------------------------------------------------

    def verify_connection(self) -> bool:
        """起動時にSlack接続を確認し、テストメッセージを送信する。

        Returns:
            True: 接続成功、False: 接続失敗
        """
        if not self._config.token:
            logger.error(
                "SLACK_TOKEN が設定されていません。\n"
                "  → 設定方法: export SLACK_TOKEN='xoxb-xxxx'\n"
                "  → トークンは Slack API (https://api.slack.com/apps) の\n"
                "    「OAuth & Permissions」→「Bot User OAuth Token」で確認できます。"
            )
            return False

        if not self._config.channel:
            logger.error(
                "SLACK_CHANNEL が設定されていません。\n"
                "  → 設定方法: export SLACK_CHANNEL='#your-channel-name'\n"
                "  → チャンネル名（#から始まる）またはチャンネルID（Cから始まる）を指定します。"
            )
            return False

        try:
            # 認証テスト
            auth_result = self._send_with_retry(
                lambda: self._client.auth_test()
            )
            if not auth_result:
                return False
            logger.info(f"Slack認証成功: {auth_result['user']}")

            # テストメッセージ送信
            test_label = " [テストモード]" if self._test_mode else ""
            msg_result = self._send_with_retry(
                lambda: self._client.chat_postMessage(
                    channel=self._config.channel,
                    text=f"センサーシステム起動: 接続テスト成功{test_label}",
                )
            )
            return msg_result is not None

        except Exception as e:
            logger.error(f"Slack接続エラー: {e}")
            return False

    def send(self, message: str) -> bool:
        """Slackにメッセージを送信する。失敗した場合は保留キューに追加する。

        Returns:
            True: 送信成功、False: 送信失敗（保留キューに追加済み）
        """
        # 先に保留メッセージの送信を試みる
        self._flush_pending()

        result = self._send_with_retry(
            lambda: self._client.chat_postMessage(
                channel=self._config.channel,
                text=message,
            )
        )
        if result is None:
            logger.info(f"メッセージを保留キューに追加します: {message}")
            self._pending_messages.append(message)
            return False
        return True

    def send_files(self, graph_path: str, csv_path: str, title_prefix: str) -> bool:
        """グラフ画像とCSVファイルをSlackにアップロードする。

        Returns:
            True: 両ファイルとも送信成功、False: いずれかが失敗
        """
        # ファイルの存在確認
        if not os.path.exists(graph_path):
            logger.error(f"エラー: グラフファイルが存在しません: {graph_path}")
            return False
        if not os.path.exists(csv_path):
            logger.error(f"エラー: CSVファイルが存在しません: {csv_path}")
            return False

        logger.info(f"グラフファイルサイズ: {os.path.getsize(graph_path)} bytes")
        logger.info(f"CSVファイルサイズ: {os.path.getsize(csv_path)} bytes")

        target_channel = self._config.channel
        logger.info(f"使用するチャンネル: {target_channel}")

        try:
            # グラフファイル送信
            graph_result = self._send_with_retry(
                lambda: self._client.files_upload_v2(
                    channels=[target_channel],
                    file=graph_path,
                    title=f"{title_prefix} - グラフ",
                )
            )
            if not graph_result:
                logger.error("グラフファイルの送信に失敗しました")
                return False

            # CSVファイル送信
            csv_result = self._send_with_retry(
                lambda: self._client.files_upload_v2(
                    channels=[target_channel],
                    file=csv_path,
                    title=f"{title_prefix} - データ",
                )
            )
            if not csv_result:
                logger.error("CSVファイルの送信に失敗しました")
                return False

            return True

        except Exception as e:
            logger.error(f"ファイル送信中に予期せぬエラーが発生しました: {e}")
            traceback.print_exc()
            return False

    def check_and_alert(self, temperature: float, humidity: float, threshold_config) -> None:
        """閾値チェックを行い、超過していればSlackにアラートを送信する。

        Parameters:
            temperature: 測定温度（°C）
            humidity: 測定湿度（%）
            threshold_config: ThresholdConfig（temp_max, temp_min, humidity_max,
                              humidity_min, alert_cooldown_sec 属性を持つ）
        """
        cooldown = threshold_config.alert_cooldown_sec
        alerts: list[str] = []

        if temperature > threshold_config.temp_max and self._is_alert_cooldown_passed('temp_high', cooldown):
            alerts.append(
                f"警告: 温度上昇 {temperature}°C (上限: {threshold_config.temp_max}°C) "
                "以後12時間は警告を出しません。"
            )
            self._alert_last_sent['temp_high'] = datetime.datetime.now()

        if temperature < threshold_config.temp_min and self._is_alert_cooldown_passed('temp_low', cooldown):
            alerts.append(
                f"警告: 温度低下 {temperature}°C (下限: {threshold_config.temp_min}°C) "
                "以後12時間は警告を出しません。"
            )
            self._alert_last_sent['temp_low'] = datetime.datetime.now()

        if humidity > threshold_config.humidity_max and self._is_alert_cooldown_passed('humidity_high', cooldown):
            alerts.append(
                f"警告: 湿度上昇 {humidity}% (上限: {threshold_config.humidity_max}%) "
                "以後12時間は警告を出しません。"
            )
            self._alert_last_sent['humidity_high'] = datetime.datetime.now()

        if humidity < threshold_config.humidity_min and self._is_alert_cooldown_passed('humidity_low', cooldown):
            alerts.append(
                f"警告: 湿度低下 {humidity}% (下限: {threshold_config.humidity_min}%) "
                "加湿器に水を補充してください。 以後12時間は警告を出しません。"
            )
            self._alert_last_sent['humidity_low'] = datetime.datetime.now()

        # アラートをSlackに送信
        for alert in alerts:
            test_label = " [テストモード]" if self._test_mode else ""
            self.send(f"{alert}{test_label}")
            logger.info(f"アラートをSlackに送信しました: {alert}")

    # ------------------------------------------------------------------
    # 内部メソッド
    # ------------------------------------------------------------------

    def _flush_pending(self) -> None:
        """保留メッセージを一括送信する。送信に失敗したメッセージはキューに戻す。"""
        if not self._pending_messages:
            return

        logger.info(f"{len(self._pending_messages)}件の保留メッセージがあります。送信を試みます...")
        remaining: list[str] = []

        for pending_msg in self._pending_messages:
            result = self._send_with_retry(
                lambda msg=pending_msg: self._client.chat_postMessage(
                    channel=self._config.channel,
                    text=msg,
                ),
                max_retries=2,
            )
            if result is None:
                remaining.append(pending_msg)

        self._pending_messages = remaining

    def _send_with_retry(self, func: Callable, max_retries: int = 3) -> Optional[object]:
        """ネットワークエラー時に最大 max_retries 回再試行するラッパー。

        元の send_with_retry(func, max_retries=3, *args, **kwargs) では
        max_retries の後に *args があるため、キーワード引数として渡しても
        位置引数に吸い込まれるバグがあった。修正後は func を引数なしで呼べる
        クロージャとして受け取り、*args / **kwargs を廃止した。

        Parameters:
            func: 引数なしで呼び出せるクロージャ（lambdaなど）
            max_retries: 最大再試行回数

        Returns:
            成功時は func の戻り値、全リトライ失敗時は None
        """
        retries = 0

        while retries < max_retries:
            try:
                # ネットワーク接続を確認
                if not is_connected():
                    logger.warning(
                        f"ネットワーク接続がありません。再接続を試みます "
                        f"(試行 {retries + 1}/{max_retries})..."
                    )
                    time.sleep(30)
                    retries += 1
                    continue

                return func()

            except (socket.gaierror, socket.timeout) as e:
                logger.error(
                    f"DNS/ネットワーク解決エラー: {e} - "
                    f"再試行 {retries + 1}/{max_retries}"
                )
                time.sleep(10 * (retries + 1))
                retries += 1

            except SlackApiError as e:
                error_code = e.response.get('error') if hasattr(e, 'response') else None

                # リトライしても解決しないエラーは即終了
                if error_code == 'invalid_auth':
                    logger.error(
                        "Slack認証エラー (invalid_auth): トークンが無効です。\n"
                        "  → SLACK_TOKEN を確認してください: echo $SLACK_TOKEN\n"
                        "  → Slack API (https://api.slack.com/apps) でトークンを再発行してください。"
                    )
                    return None
                elif error_code == 'channel_not_found':
                    logger.error(
                        f"Slackチャンネルが見つかりません (channel_not_found): "
                        f"'{self._config.channel}'\n"
                        "  → SLACK_CHANNEL の値を確認してください: echo $SLACK_CHANNEL\n"
                        "  → チャンネル名（例: #general）またはチャンネルID（例: C012AB3CD）が"
                        "正しいか確認してください。"
                    )
                    return None
                elif error_code == 'not_in_channel':
                    logger.error(
                        f"BotがSlackチャンネルに参加していません (not_in_channel): "
                        f"'{self._config.channel}'\n"
                        "  → Slackでチャンネルを開き、メッセージ入力欄に "
                        "'/invite @ボット名' と入力して招待してください。"
                    )
                    return None
                elif error_code == 'missing_scope':
                    logger.error(
                        "Botに必要な権限がありません (missing_scope)。\n"
                        "  → Slack API (https://api.slack.com/apps) の"
                        "「OAuth & Permissions」→「Scopes」で\n"
                        "    'chat:write' と 'files:write' が追加されているか確認してください。\n"
                        "  → スコープ追加後はトークンを再発行（Reinstall App）してください。"
                    )
                    return None

                # 上記以外のSlack APIエラーはリトライ
                logger.error(
                    f"Slack APIエラー: {e} - 再試行 {retries + 1}/{max_retries}"
                )
                time.sleep(5 * (retries + 1))
                retries += 1

            except Exception as e:
                logger.error(f"予期せぬエラー: {e}")
                traceback.print_exc()
                return None

        logger.error(
            f"Slack送信の最大試行回数 ({max_retries}回) に達しました。送信を中止します。\n"
            "  → WiFi接続を確認: iwconfig wlan0\n"
            "  → インターネット疎通を確認: ping -c 3 8.8.8.8\n"
            "  → Slackサーバーへの疎通を確認: ping -c 3 api.slack.com"
        )
        return None

    def _is_alert_cooldown_passed(self, alert_key: str, cooldown_sec: int) -> bool:
        """アラートのクールダウン期間を過ぎているかチェックする。

        Parameters:
            alert_key: アラート種別キー（例: 'temp_high'）
            cooldown_sec: クールダウン秒数

        Returns:
            True: 送信可能（初回 or クールダウン経過済み）
        """
        last = self._alert_last_sent[alert_key]
        if last is None:
            return True
        return (datetime.datetime.now() - last).total_seconds() > cooldown_sec
