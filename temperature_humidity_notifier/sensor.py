"""
DHT22センサーの読み取りを管理するモジュール。

実機モードではDHT22から温湿度を取得し、テストモードではダミーデータを生成する。
"""

import logging
import random
import time
from typing import Optional, Tuple

from config import SensorConfig, TestConfig, ThresholdConfig

logger = logging.getLogger(__name__)


class SensorReader:
    """DHT22センサーの読み取りを管理するクラス"""

    def __init__(
        self,
        sensor_config: SensorConfig,
        test_config: TestConfig,
        threshold_config: ThresholdConfig,
    ) -> None:
        """
        Parameters:
            sensor_config: センサーのハードウェア設定（DHT_PINを含む）
            test_config: テストモード設定（ダミーデータ生成パラメータを含む）
            threshold_config: 閾値設定（テストモードのアラート生成で使用）
        """
        self._pin = sensor_config.dht_pin
        self._test_config = test_config
        self._threshold_config = threshold_config
        self._dht_device = None

        # テストモードでは実センサーを初期化しない
        if not test_config.enabled:
            self._init_device()

    def _init_device(self) -> None:
        """DHT22デバイスを初期化する"""
        import adafruit_dht
        # use_pulseio=False はRaspberry Pi 3 + adafruit_circuitpython_dht の組み合わせで
        # ImportError や動作不安定が報告されているため省略（デフォルトのpulsioモードを使用）
        self._dht_device = adafruit_dht.DHT22(self._pin)
        logger.info("DHT22センサーを初期化しました")

    def read(self) -> Tuple[Optional[float], Optional[float]]:
        """
        センサーから温湿度を読み取る。

        Returns:
            (humidity, temperature) のタプル。取得失敗時は (None, None)
        """
        if self._test_config.enabled:
            return self._generate_test_data()
        return self._read_from_device()

    def _generate_test_data(self) -> Tuple[float, float]:
        """テストモード用のダミーデータを生成する"""
        temperature = self._test_config.temp_base
        humidity = self._test_config.humid_base

        if self._test_config.data_variation:
            temperature += random.uniform(-0.5, 0.5)
            humidity += random.uniform(-2.0, 2.0)

            # 10%の確率でアラートを発火させるデータを生成する
            if self._test_config.generate_alerts and random.random() < 0.1:
                if random.random() < 0.5:
                    # 温度を閾値外に設定（上限超過 or 下限未満をランダムに選択）
                    if random.random() < 0.5:
                        temperature = self._threshold_config.temp_max + 2
                    else:
                        temperature = self._threshold_config.temp_min - 2
                else:
                    # 湿度を閾値外に設定（上限超過 or 下限未満をランダムに選択）
                    if random.random() < 0.5:
                        humidity = self._threshold_config.humidity_max + 5
                    else:
                        humidity = self._threshold_config.humidity_min - 5

        return round(humidity, 3), round(temperature, 3)

    def _read_from_device(self) -> Tuple[Optional[float], Optional[float]]:
        """実際のDHT22センサーからデータを読み取る"""
        try:
            temperature = self._dht_device.temperature   # °C
            humidity = self._dht_device.humidity          # %
            if humidity is not None and temperature is not None:
                return round(humidity, 3), round(temperature, 3)
            logger.warning("センサーからのデータ取得に失敗しました。再試行します...")
            return None, None
        except RuntimeError as e:
            # 読み取り失敗はDHT22では頻繁に起こるのでデバッグログのみ
            logger.debug(f"DHT 取得失敗: {e}")
            return None, None
        except Exception as e:
            # その他クリティカルな例外はセンサーをリセットして再初期化
            logger.error(f"DHT 重大エラー: {e}")
            try:
                self._dht_device.exit()
            except Exception:
                pass
            time.sleep(2)
            self._init_device()
            return None, None

    def cleanup(self) -> None:
        """センサーリソースを解放する"""
        if self._dht_device is not None:
            try:
                self._dht_device.exit()
                logger.info("DHT22センサー接続を終了しました")
            except Exception as e:
                logger.warning(f"DHT22センサー終了時にエラー: {e}")
