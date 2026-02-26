"""
温湿度モニタリングシステムの設定モジュール。

全設定パラメータをdataclassで一元管理し、CLIフラグ・環境変数から生成する。
"""

import argparse
import os
from dataclasses import dataclass, field
from typing import Any, List, Tuple

# board モジュールはRaspberry Pi（adafruit-blinka）専用のため、
# テスト環境やWindows環境ではインポートに失敗する。その場合は None にフォールバック
try:
    import board as _board
    _DHT_PIN = _board.D4
except (ImportError, NotImplementedError):
    _DHT_PIN = None


@dataclass
class SensorConfig:
    """DHT22センサーのハードウェア設定"""
    dht_pin: Any = None  # board.D4 相当のピンオブジェクト

    def __post_init__(self) -> None:
        if self.dht_pin is None:
            self.dht_pin = _DHT_PIN


@dataclass
class ThresholdConfig:
    """温湿度の閾値とアラート抑制設定"""
    temp_max: float = 23.0
    temp_min: float = 17.0
    humidity_max: float = 70.0
    humidity_min: float = 40.0
    # アラート送信後、同じ種類のアラートを抑制する時間（秒）。デフォルト12時間
    alert_cooldown_sec: int = 43200


@dataclass
class ScheduleConfig:
    """測定・レポート送信の間隔設定"""
    check_interval_sec: int = 600         # センサー測定間隔（秒）
    short_report_interval_min: int = 30   # 短期レポート間隔（分）
    long_report_interval_days: int = 1    # 長期レポート間隔（日）


@dataclass
class SlackConfig:
    """Slack通知の接続設定"""
    token: str = ''
    channel: str = ''


@dataclass
class PathConfig:
    """ファイルパス関連の設定"""
    save_dir: str = '.'
    csv_filename: str = 'temperature_log.csv'
    # 多重起動防止用PIDファイル（Linuxの/tmp以下に置く）
    pid_file: str = '/tmp/temp_humid_notifier.pid'


@dataclass
class TestConfig:
    """テストモード用の設定"""
    enabled: bool = False
    data_variation: bool = True
    temp_base: float = 20.0
    humid_base: float = 50.0
    generate_alerts: bool = True


@dataclass
class NetworkConfig:
    """ネットワーク診断用の設定"""
    router_ip: str = '192.168.10.1'
    dns_servers: List[str] = field(default_factory=lambda: ['8.8.8.8', '8.8.4.4'])
    test_domains: List[str] = field(default_factory=lambda: ['api.slack.com', 'www.google.com'])


def load_config(
    args: argparse.Namespace,
) -> Tuple[SensorConfig, ThresholdConfig, ScheduleConfig, SlackConfig, PathConfig, TestConfig, NetworkConfig]:
    """
    CLIフラグと環境変数をもとに全設定オブジェクトを生成して返す。

    Parameters:
        args: argparse でパースしたコマンドライン引数。
              --test-mode と --save-dir を参照する。

    Returns:
        (SensorConfig, ThresholdConfig, ScheduleConfig, SlackConfig,
         PathConfig, TestConfig, NetworkConfig) のタプル
    """
    # テストモードは CLIフラグ または 環境変数 TEST_MODE=1 で有効化
    test_mode_enabled = args.test_mode or (os.environ.get('TEST_MODE', '0') == '1')

    # 保存先ディレクトリは --save-dir フラグで指定（デフォルト '.'）
    save_dir = args.save_dir if args.save_dir else '.'

    sensor_config = SensorConfig()
    threshold_config = ThresholdConfig()
    schedule_config = ScheduleConfig()
    slack_config = SlackConfig(
        token=os.environ.get('SLACK_TOKEN', ''),
        channel=os.environ.get('SLACK_CHANNEL', ''),
    )
    path_config = PathConfig(save_dir=save_dir)
    test_config = TestConfig(enabled=test_mode_enabled)
    network_config = NetworkConfig()

    return (
        sensor_config,
        threshold_config,
        schedule_config,
        slack_config,
        path_config,
        test_config,
        network_config,
    )
