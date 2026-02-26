"""
ネットワーク診断・自動復旧モジュール。

WiFi接続、ルーター疎通、DNS解決、インターネット接続、Slack到達性を
段階的に診断し、問題の種類に応じた自動復旧を試みる。
"""

import datetime
import logging
import re
import socket
import subprocess
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

from reconnect_wifi import is_connected, restart_wifi

from config import NetworkConfig

logger = logging.getLogger(__name__)


@dataclass
class NetworkState:
    """ネットワーク診断・復旧の状態を保持するデータクラス"""
    last_check: Optional[datetime.datetime] = None
    last_successful: Optional[datetime.datetime] = None
    failures: int = 0
    dns_failures: int = 0
    internet_failures: int = 0
    wifi_failures: int = 0
    last_error: Optional[str] = None
    recovery_attempts: int = 0


class NetworkManager:
    """ネットワーク診断・自動復旧を管理するクラス"""

    def __init__(self, config: NetworkConfig) -> None:
        """
        Parameters:
            config: NetworkConfig（router_ip, dns_servers, test_domains を持つ）
        """
        self.state = NetworkState()
        self._config = config

    def diagnose(self) -> Dict[str, Any]:
        """
        ネットワーク接続問題の原因を段階的に診断し結果を返す。

        WiFi → ルーター → インターネット → DNS → Slack の順にチェックし、
        最初に見つかった問題の段階で診断を打ち切って結果を返す。

        Returns:
            診断結果の辞書。主なキー:
            - wifi_connected, router_reachable, internet_reachable,
              dns_working, slack_reachable: 各段階の到達状態 (bool)
            - error_type: 検出された問題の種別 (str or None)
            - recommendation: 推奨対処メッセージ (str or None)
            - details: WiFi信号強度などの追加情報 (dict)
        """
        result: Dict[str, Any] = {
            'wifi_connected': False,
            'router_reachable': False,
            'internet_reachable': False,
            'dns_working': False,
            'slack_reachable': False,
            'error_type': None,
            'recommendation': None,
            'details': {},
        }

        # --- 1. WiFi接続確認 ---
        try:
            wifi_status = subprocess.run(
                ['iwconfig', 'wlan0'],
                capture_output=True, text=True, check=False,
            )
            if "ESSID:" in wifi_status.stdout and "Not-Associated" not in wifi_status.stdout:
                result['wifi_connected'] = True

                # 信号強度を取得して品質を判定
                signal_match = re.search(r'Signal level=(-\d+) dBm', wifi_status.stdout)
                if signal_match:
                    signal_level = int(signal_match.group(1))
                    result['details']['wifi_signal'] = signal_level
                    if signal_level < -70:
                        result['details']['wifi_quality'] = 'poor'
                        result['recommendation'] = (
                            'WiFiの信号強度が弱いです。'
                            'アクセスポイントに近づくか、アンテナの向きを調整してください。'
                        )
                    else:
                        result['details']['wifi_quality'] = 'good'
            else:
                result['error_type'] = 'wifi_disconnected'
                result['recommendation'] = 'WiFiが切断されています。ネットワーク設定を確認してください。'
                self.state.wifi_failures += 1
                return result
        except Exception as e:
            logger.error(f"WiFi状態確認中にエラー: {e}")
            result['error_type'] = 'wifi_check_error'
            result['recommendation'] = 'WiFi状態の確認中にエラーが発生しました。'
            return result

        # --- 2. ルーターへの疎通確認 ---
        try:
            ping_router = subprocess.run(
                ['ping', '-c', '1', '-W', '2', self._config.router_ip],
                capture_output=True, check=False,
            )
            if ping_router.returncode == 0:
                result['router_reachable'] = True
            else:
                result['error_type'] = 'router_unreachable'
                result['recommendation'] = (
                    'ルーターに接続できません。'
                    'WiFi接続は確立していますが、ローカルネットワークに問題があります。'
                )
                return result
        except Exception as e:
            logger.error(f"ルータ疎通確認中にエラー: {e}")

        # --- 3. インターネット接続確認 ---
        try:
            ping_internet = subprocess.run(
                ['ping', '-c', '1', '-W', '3', '8.8.8.8'],
                capture_output=True, check=False,
            )
            if ping_internet.returncode == 0:
                result['internet_reachable'] = True
            else:
                result['error_type'] = 'internet_unreachable'
                result['recommendation'] = (
                    'インターネットに接続できません。'
                    'ルーターのインターネット接続を確認してください。'
                )
                self.state.internet_failures += 1
                return result
        except Exception as e:
            logger.error(f"インターネット疎通確認中にエラー: {e}")

        # --- 4. DNS解決確認 ---
        try:
            for domain in self._config.test_domains:
                try:
                    socket.getaddrinfo(domain, 80)
                    result['dns_working'] = True
                    break
                except socket.gaierror:
                    continue

            if not result['dns_working']:
                result['error_type'] = 'dns_failure'
                result['recommendation'] = (
                    'DNSの解決に失敗しています。DNSサーバーを確認・変更してください。'
                )
                self.state.dns_failures += 1

                # /etc/resolv.conf にGoogle DNSが設定されていなければ助言を追加
                try:
                    with open('/etc/resolv.conf', 'r') as f:
                        resolv_conf = f.read()
                        if not any(dns in resolv_conf for dns in self._config.dns_servers):
                            result['recommendation'] += (
                                ' /etc/resolv.confにGoogle DNSを追加することを検討してください。'
                            )
                except Exception as e:
                    logger.warning(f"resolv.conf の読み取りに失敗: {e}")

                return result
        except Exception as e:
            logger.error(f"DNS確認中にエラー: {e}")

        # --- 5. Slackサーバーへの疎通確認 ---
        try:
            socket.getaddrinfo('api.slack.com', 443)
            result['slack_reachable'] = True
        except socket.gaierror:
            result['error_type'] = 'slack_unreachable'
            result['recommendation'] = (
                'Slackサーバーに接続できません。一時的なSlackのサービス障害かもしれません。'
            )
            return result
        except Exception as e:
            logger.error(f"Slack疎通確認中にエラー: {e}")

        # すべてのチェックを通過した場合
        if all([
            result['wifi_connected'],
            result['router_reachable'],
            result['internet_reachable'],
            result['dns_working'],
            result['slack_reachable'],
        ]):
            result['recommendation'] = 'ネットワーク状態は良好です。'

        return result

    def handle_issue(self) -> bool:
        """
        ネットワーク問題を診断し、種類に応じた自動復旧を試みる。

        前回チェックから60秒未満の場合はスキップする（連続呼び出し防止）。

        Returns:
            True: 問題なし、または復旧に成功した場合
            False: 復旧に失敗した場合、またはスキップした場合
        """
        current_time = datetime.datetime.now()

        # 前回チェックから60秒未満ならスキップ
        if (self.state.last_check
                and (current_time - self.state.last_check).total_seconds() < 60):
            return False

        self.state.last_check = current_time
        self.state.failures += 1

        logger.info("ネットワーク問題を診断しています...")
        diagnosis = self.diagnose()

        logger.info(f"診断結果: {diagnosis['error_type']}")
        logger.info(f"推奨対処: {diagnosis['recommendation']}")

        self.state.last_error = diagnosis['error_type']

        # --- WiFi切断: 再接続を試行 ---
        if diagnosis['error_type'] == 'wifi_disconnected':
            logger.info("WiFi接続が切断されています。再接続を試みます...")
            if restart_wifi():
                logger.info("WiFi再接続に成功しました")
                self.state.recovery_attempts += 1
                return True
            else:
                logger.error("WiFi再接続に失敗しました")
                return False

        # --- DNS障害: キャッシュクリア＋Google DNS設定 ---
        if diagnosis['error_type'] == 'dns_failure':
            logger.info("DNS解決に問題があります。DNSキャッシュをクリアして代替DNSを設定します...")
            try:
                subprocess.run(
                    ['sudo', 'systemctl', 'restart', 'nscd'],
                    check=False, capture_output=True,
                )
            except Exception as e:
                logger.warning(f"nscd再起動に失敗（未インストールの可能性あり）: {e}")

            try:
                dns_servers = self._config.dns_servers
                dns_config = ''.join(f"nameserver {s}\n" for s in dns_servers)
                with open('/tmp/resolv.conf.temp', 'w') as f:
                    f.write(dns_config)
                subprocess.run(
                    ['sudo', 'cp', '/tmp/resolv.conf.temp', '/etc/resolv.conf'],
                    check=False, capture_output=True,
                )
                logger.info("一時的にGoogle DNSを設定しました")
                self.state.recovery_attempts += 1
                return True
            except Exception as e:
                logger.error(f"DNS設定変更中にエラー: {e}")
                return False

        # --- インターネット/ルーター到達不能: NIC再起動 ---
        if diagnosis['error_type'] in ('internet_unreachable', 'router_unreachable'):
            logger.info("ネットワークインターフェースを再起動します...")
            try:
                subprocess.run(['sudo', 'ifconfig', 'wlan0', 'down'], check=False)
                time.sleep(2)
                subprocess.run(['sudo', 'ifconfig', 'wlan0', 'up'], check=False)
                time.sleep(5)

                # 失敗が連続している場合はネットワークサービス自体を再起動
                if self.state.failures > 2:
                    logger.info("ネットワークサービスを再起動します...")
                    subprocess.run(
                        ['sudo', 'systemctl', 'restart', 'networking'],
                        check=False,
                    )
                    time.sleep(10)

                self.state.recovery_attempts += 1
                return is_connected()
            except Exception as e:
                logger.error(f"ネットワークインターフェース再起動中にエラー: {e}")
                return False

        # エラーなし → 問題は解消済み。失敗カウンタをリセット
        if not diagnosis['error_type']:
            self.state.failures = 0
            return True

        return False

    def generate_report(self) -> None:
        """ネットワーク診断レポートをログに記録し network_report.txt に保存する。"""
        try:
            report_lines = ["========== ネットワーク診断レポート =========="]
            report_lines.append(
                f"診断時刻: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            )
            report_lines.append(f"接続失敗回数: {self.state.failures}")
            report_lines.append(f"DNS解決失敗: {self.state.dns_failures}")
            report_lines.append(f"インターネット接続失敗: {self.state.internet_failures}")
            report_lines.append(f"WiFi接続失敗: {self.state.wifi_failures}")
            report_lines.append(f"復旧試行回数: {self.state.recovery_attempts}")
            report_lines.append(f"最後のエラー: {self.state.last_error}")

            # WiFi状態
            try:
                iwconfig = subprocess.run(
                    ['iwconfig', 'wlan0'],
                    capture_output=True, text=True, check=False,
                )
                report_lines.append("\n----- WiFi状態 (iwconfig) -----")
                report_lines.append(iwconfig.stdout)
            except Exception as e:
                report_lines.append(f"WiFi状態の取得に失敗しました: {e}")

            # ネットワークインターフェース状態
            try:
                ifconfig = subprocess.run(
                    ['ifconfig', 'wlan0'],
                    capture_output=True, text=True, check=False,
                )
                report_lines.append("\n----- ネットワークインターフェース状態 (ifconfig) -----")
                report_lines.append(ifconfig.stdout)
            except Exception as e:
                report_lines.append(f"ネットワークインターフェース状態の取得に失敗しました: {e}")

            # ルーティング情報
            try:
                route = subprocess.run(
                    ['ip', 'route'],
                    capture_output=True, text=True, check=False,
                )
                report_lines.append("\n----- ルーティング情報 (ip route) -----")
                report_lines.append(route.stdout)
            except Exception as e:
                report_lines.append(f"ルーティング情報の取得に失敗しました: {e}")

            # DNS設定
            try:
                with open('/etc/resolv.conf', 'r') as f:
                    resolv_conf = f.read()
                    report_lines.append("\n----- DNS設定 (/etc/resolv.conf) -----")
                    report_lines.append(resolv_conf)
            except Exception as e:
                report_lines.append(f"DNS設定の取得に失敗しました: {e}")

            # Google DNSへのping
            try:
                ping_google = subprocess.run(
                    ['ping', '-c', '1', '-W', '2', '8.8.8.8'],
                    capture_output=True, text=True, check=False,
                )
                report_lines.append("\n----- Google DNSへのping -----")
                report_lines.append(ping_google.stdout)
            except Exception as e:
                report_lines.append(f"pingの実行に失敗しました: {e}")

            report_text = "\n".join(report_lines)
            logger.info(report_text)

            with open('network_report.txt', 'w') as f:
                f.write(report_text)

        except Exception as e:
            logger.error(f"ネットワークレポート生成中にエラー: {e}")

    def should_run_periodic_check(self, interval_sec: int = 3600) -> bool:
        """
        前回チェックから interval_sec 秒以上経過していれば True を返す。

        定期的なネットワーク状態チェックのタイミング判定に使う。
        初回（まだ一度もチェックしていない場合）は常に True。

        Parameters:
            interval_sec: チェック間隔（秒）。デフォルト3600秒（1時間）
        """
        if self.state.last_check is None:
            return True
        elapsed = (datetime.datetime.now() - self.state.last_check).total_seconds()
        return elapsed >= interval_sec
