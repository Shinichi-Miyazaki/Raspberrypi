"""
レポート生成モジュール。

ログCSVからのグラフ作成と、短期・長期レポートのSlack送信を担う。
"""

from __future__ import annotations

import datetime
import logging
import os
import traceback
from typing import TYPE_CHECKING, Optional

import matplotlib.pyplot as plt
import pandas as pd

if TYPE_CHECKING:
    from notifier import SlackNotifier

logger = logging.getLogger(__name__)


def create_graph(
    csv_path: str,
    output_path: str,
    threshold_config,
    start_time: Optional[datetime.datetime] = None,
    end_time: Optional[datetime.datetime] = None,
) -> bool:
    """ログCSVを読み込み、指定期間の温度・湿度グラフをファイル出力する。

    Parameters:
        csv_path: 読み込むCSVファイルのパス
        output_path: グラフ画像の保存先パス
        threshold_config: ThresholdConfig（temp_max, temp_min, humidity_max,
                          humidity_min 属性を持つ）
        start_time: グラフに含めるデータの開始時刻
        end_time: グラフに含めるデータの終了時刻

    Returns:
        True: 成功、False: 失敗（データなし・例外）
    """
    try:
        # CSVをヘッダー付きで読み込む
        df = pd.read_csv(csv_path, header=0)
        # timestamp列を日時型に変換。読み込みエラーの行はNaTになる（errors='coerce'）
        df['timestamp'] = pd.to_datetime(df['timestamp'], errors='coerce')

        # start_time や end_time が指定された場合はその範囲でフィルタ
        if start_time:
            df = df[df['timestamp'] >= start_time]
        if end_time:
            df = df[df['timestamp'] <= end_time]

        if df.empty:
            logger.warning("グラフ作成用のデータがありません")
            return False

        temp_max = threshold_config.temp_max
        temp_min = threshold_config.temp_min
        humidity_max = threshold_config.humidity_max
        humidity_min = threshold_config.humidity_min

        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8))

        # 温度のプロット（赤線）＋閾値ライン
        ax1.plot(df['timestamp'], df['temperature'], 'r-', label='温度')
        ax1.axhline(
            y=temp_max, color='orange', linestyle='--', alpha=0.8,
            label=f'上限 ({temp_max}°C)',
        )
        ax1.axhline(
            y=temp_min, color='steelblue', linestyle='--', alpha=0.8,
            label=f'下限 ({temp_min}°C)',
        )
        ax1.set_title('Temperature (°C)')
        ax1.grid(True)
        ax1.legend(loc='upper right', fontsize=8)
        ax1.set_ylim([temp_min - 5, temp_max + 5])

        # 湿度のプロット（青線）＋閾値ライン
        ax2.plot(df['timestamp'], df['humidity'], 'b-', label='湿度')
        ax2.axhline(
            y=humidity_max, color='orange', linestyle='--', alpha=0.8,
            label=f'上限 ({humidity_max}%)',
        )
        ax2.axhline(
            y=humidity_min, color='steelblue', linestyle='--', alpha=0.8,
            label=f'下限 ({humidity_min}%)',
        )
        ax2.set_title('Humidity (%)')
        ax2.grid(True)
        ax2.legend(loc='upper right', fontsize=8)
        ax2.set_ylim([humidity_min - 10, humidity_max + 10])

        plt.tight_layout()
        plt.savefig(output_path)
        plt.close()
        return True

    except Exception as e:
        logger.error(f"グラフ作成エラー: {e}")
        traceback.print_exc()
        return False


def send_short_report(
    notifier: 'SlackNotifier',
    csv_path: str,
    save_dir: str,
    threshold_config,
    start_time: datetime.datetime,
    current_time: datetime.datetime,
    interval_minutes: int,
) -> None:
    """短期レポート（起動から interval_minutes 分経過後）のグラフとCSVをSlackに送信する。

    Parameters:
        notifier: SlackNotifier インスタンス
        csv_path: ログCSVファイルのパス
        save_dir: レポートファイルの保存先ディレクトリ
        threshold_config: ThresholdConfig
        start_time: 計測開始時刻
        current_time: 現在時刻
        interval_minutes: レポート間隔（分）
    """
    graph_path = os.path.join(save_dir, f'{interval_minutes}min_graph.png')
    temp_csv_path = os.path.join(save_dir, f'{interval_minutes}min_data.csv')

    logger.info(f"{interval_minutes}分レポートを作成中...")

    if not create_graph(csv_path, graph_path, threshold_config, start_time, current_time):
        logger.warning("短期レポートのグラフ作成に失敗しました")
        return

    try:
        # 期間内のデータをCSVとしてエクスポート
        pd.read_csv(csv_path, header=0).to_csv(temp_csv_path, index=False)
        notifier.send_files(graph_path, temp_csv_path, f"{interval_minutes}分間レポート")
        logger.info(f"{interval_minutes}分レポートをSlackに送信しました")
    except Exception as e:
        logger.error(f"短期レポート送信中にエラーが発生しました: {e}")
        traceback.print_exc()


def send_long_report(
    notifier: 'SlackNotifier',
    csv_path: str,
    save_dir: str,
    threshold_config,
    last_report_time: datetime.datetime,
    current_time: datetime.datetime,
    interval_days: int,
) -> None:
    """長期レポート（interval_days 日ごと）のグラフとCSVをSlackに送信する。

    Parameters:
        notifier: SlackNotifier インスタンス
        csv_path: ログCSVファイルのパス
        save_dir: レポートファイルの保存先ディレクトリ
        threshold_config: ThresholdConfig
        last_report_time: 前回のレポート送信時刻（この時刻以降のデータを対象にする）
        current_time: 現在時刻
        interval_days: レポート間隔（日）
    """
    graph_path = os.path.join(save_dir, 'long_report_graph.png')
    temp_csv_path = os.path.join(save_dir, 'long_report_data.csv')

    logger.info(f"{interval_days}日レポートを作成中...")

    if not create_graph(csv_path, graph_path, threshold_config, last_report_time, current_time):
        logger.warning("長期レポートのグラフ作成に失敗しました")
        return

    try:
        # 前回レポート以降のデータのみを抽出してCSVを作成
        df = pd.read_csv(csv_path, header=0)
        df['timestamp'] = pd.to_datetime(df['timestamp'], errors='coerce')
        mask = (df['timestamp'] >= last_report_time) & (df['timestamp'] <= current_time)
        df_period = df.loc[mask]

        if df_period.empty:
            logger.warning("レポート期間内にデータがありません")
            return

        df_period.to_csv(temp_csv_path, index=False)

        notifier.send(f"{interval_days}日間レポートを送信します")
        notifier.send_files(graph_path, temp_csv_path, f"{interval_days}日間レポート")
        logger.info(f"{interval_days}日レポートをSlackに送信しました")

    except Exception as e:
        logger.error(f"長期レポート送信中にエラーが発生しました: {e}")
        traceback.print_exc()
