"""
温湿度データコレクター（コレクター役のPi 1台だけで動かす）。

NAS上の sensor_data 共有フォルダを読み書きし、以下の3つの処理を行う。
それぞれ systemd timer（または cron）で定期実行する想定。

  ingest        10分ごと: incoming/ のCSVをSQLiteに取り込み、
                温度変化率アラートと欠測アラートを判定してSlack通知
  daily         1日1回: 日次集計(min/max/avg)と、変化率閾値の統計量(μ・σ)の再計算
  weekly-report 週1回: 全デバイスのスモールマルチプルグラフを生成してSlack投稿
  status        手動実行用: 各デバイスの最終受信時刻・件数を表示（Slack設定不要）

使い方:
    python3 collector.py ingest        --base-dir /mnt/sensor_data
    python3 collector.py daily         --base-dir /mnt/sensor_data
    python3 collector.py weekly-report --base-dir /mnt/sensor_data
    python3 collector.py status        --base-dir /mnt/sensor_data
    # --no-slack を付けるとSlackに送らずログ出力のみ（動作確認用）

Slack設定は環境変数で渡す:
    SLACK_TOKEN        Bot User OAuth Token（xoxb- で始まる）
    SLACK_CHANNEL_ID   通知チャンネルのID（例: C0XXXXXXX）

NAS上のフォルダ構成（--base-dir 以下）:
    incoming/<デバイス名>/   各Piから届いたCSVチャンク（取り込み後に削除）
    db/sensor_data.sqlite3   全デバイス共通のデータベース
    config/thresholds.yaml   デバイスごとの閾値設定・統計量
    reports/weekly/          週次レポート画像のアーカイブ（月別）
    logs/collector.log       このプログラムのログ
"""

import argparse
import csv
import datetime
import glob
import logging
import os
import sqlite3
import statistics
import sys
import traceback

# =============================================================================
# 定数
# =============================================================================

DB_RELATIVE_PATH = os.path.join('db', 'sensor_data.sqlite3')
CONFIG_RELATIVE_PATH = os.path.join('config', 'thresholds.yaml')
LOG_RELATIVE_PATH = os.path.join('logs', 'collector.log')

# 変化率の計算で、測定間隔がこれより空いたペアは判定に使わない
# （Pi再起動・欠測をまたぐペアは変化率が不正確になり誤報の元になるため）
MAX_PAIR_GAP_MINUTES = 30

# 変化率アラートは最新データがこの時間より古い場合は判定しない
# （ingestは10分ごとに走るため、同じ古いペアを繰り返し判定するのを防ぐ）
RATE_ALERT_FRESHNESS_MINUTES = 30

# μ・σの再計算に使う過去データの日数と、計算に必要な最小ペア数
STATS_WINDOW_DAYS = 30
STATS_MIN_SAMPLES = 50

# thresholds.yaml に設定が無いときに使うデフォルト値
DEFAULT_SETTINGS = {
    'k': 3.0,                    # 閾値 θ = μ + k・σ の係数。誤報/見逃しに応じて手動調整する
    'alert_cooldown_hours': 6,   # 同じデバイスの変化率アラートの再送抑制時間
    'baseline_days': 7,          # 運用開始からこの日数はアラートを出さない（μ・σの助走期間）
    'missing_data_hours': 2,     # データがこの時間止まったら欠測アラート
}

logger = logging.getLogger('collector')


# =============================================================================
# 共通セットアップ
# =============================================================================

def setup_logging(base_dir: str, debug: bool) -> None:
    """ログをNAS上の logs/collector.log とコンソールの両方に出す"""
    log_path = os.path.join(base_dir, LOG_RELATIVE_PATH)
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    logging.basicConfig(
        level=logging.DEBUG if debug else logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_path),
            logging.StreamHandler(),
        ],
    )


def open_database(base_dir: str) -> sqlite3.Connection:
    """
    SQLiteデータベースを開く（無ければテーブルごと作成する）。

    このDBに書き込むのはコレクターの単一プロセスだけにすること。
    ネットワーク共有上のSQLiteは複数プロセスからの同時書き込みで壊れることがある。
    """
    db_path = os.path.join(base_dir, DB_RELATIVE_PATH)
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS readings (
            device_id   TEXT NOT NULL,
            timestamp   TEXT NOT NULL,   -- 'YYYY-MM-DD HH:MM:SS'（文字列比較で時系列順になる）
            temperature REAL,
            humidity    REAL,
            PRIMARY KEY (device_id, timestamp)
        );
        CREATE TABLE IF NOT EXISTS daily_summary (
            device_id TEXT NOT NULL,
            date      TEXT NOT NULL,     -- 'YYYY-MM-DD'
            temp_min  REAL, temp_max  REAL, temp_avg  REAL,
            humid_min REAL, humid_max REAL, humid_avg REAL,
            PRIMARY KEY (device_id, date)
        );
        CREATE TABLE IF NOT EXISTS alert_state (
            device_id TEXT NOT NULL,
            alert_key TEXT NOT NULL,     -- 'rate'（変化率）または 'missing'（欠測）
            last_sent TEXT NOT NULL,
            PRIMARY KEY (device_id, alert_key)
        );
    """)
    return conn


def load_config(base_dir: str) -> dict:
    """thresholds.yaml を読み込む。無ければデフォルト構成を返す"""
    import yaml  # PyYAMLが未インストールでも --help 等が動くよう、ここでimportする
    config_path = os.path.join(base_dir, CONFIG_RELATIVE_PATH)
    if os.path.exists(config_path):
        with open(config_path, encoding='utf-8') as f:
            config = yaml.safe_load(f) or {}
    else:
        config = {}
    config.setdefault('defaults', {})
    config.setdefault('devices', {})
    return config


def save_config(base_dir: str, config: dict) -> None:
    """thresholds.yaml を保存する（一時ファイル経由のアトミック置換）"""
    import yaml
    config_path = os.path.join(base_dir, CONFIG_RELATIVE_PATH)
    os.makedirs(os.path.dirname(config_path), exist_ok=True)
    temp_path = config_path + '.tmp'
    with open(temp_path, 'w', encoding='utf-8') as f:
        yaml.safe_dump(config, f, allow_unicode=True, sort_keys=False)
    os.replace(temp_path, config_path)


def get_setting(config: dict, device_id: str, key: str):
    """デバイス個別設定 → defaults → 組み込みデフォルト の優先順で設定値を取得する"""
    device_settings = config['devices'].get(device_id) or {}
    if key in device_settings:
        return device_settings[key]
    if key in config['defaults']:
        return config['defaults'][key]
    return DEFAULT_SETTINGS[key]


def parse_timestamp(text: str) -> datetime.datetime:
    """'YYYY-MM-DD HH:MM:SS' 形式のタイムスタンプをdatetimeに変換する"""
    return datetime.datetime.fromisoformat(text)


# =============================================================================
# Slack送信
# =============================================================================

class SlackSender:
    """
    Slack送信をまとめたクラス。

    --no-slack のときは実際には送らず、送るはずだった内容をログに出す
    （Slack未設定の環境やテストでの動作確認用）。
    """

    def __init__(self, no_slack: bool):
        self.no_slack = no_slack
        self.client = None
        self.channel_id = None
        if no_slack:
            return

        token = os.environ.get('SLACK_TOKEN', '')
        self.channel_id = os.environ.get('SLACK_CHANNEL_ID', '')
        if not token or not self.channel_id:
            logger.error(
                "環境変数 SLACK_TOKEN / SLACK_CHANNEL_ID が設定されていません。\n"
                "  systemdの場合は EnvironmentFile= で指定したファイルを確認してください。\n"
                "  Slackに送らず動作確認だけしたい場合は --no-slack を付けてください"
            )
            raise SystemExit(1)

        from slack_sdk import WebClient
        self.client = WebClient(token=token)

    def post_message(self, text: str) -> bool:
        """テキストメッセージを送信する"""
        if self.no_slack:
            logger.info(f"[dry-run] Slackメッセージ: {text}")
            return True
        try:
            self.client.chat_postMessage(channel=self.channel_id, text=text)
            return True
        except Exception as e:
            logger.error(f"Slackメッセージ送信に失敗しました: {e}")
            return False

    def upload_file(self, file_path: str, title: str, comment: str) -> bool:
        """ファイル（グラフ画像）をコメント付きで送信する"""
        if self.no_slack:
            logger.info(f"[dry-run] Slackファイル送信: {file_path}\n{comment}")
            return True
        try:
            self.client.files_upload_v2(
                channels=[self.channel_id],
                file=file_path,
                title=title,
                initial_comment=comment,
            )
            return True
        except Exception as e:
            logger.error(f"Slackファイル送信に失敗しました: {e}")
            return False


def is_cooldown_passed(conn: sqlite3.Connection, device_id: str, alert_key: str,
                       cooldown_hours: float, now: datetime.datetime) -> bool:
    """このデバイス・アラート種別のクールダウン期間を過ぎているかチェックする"""
    row = conn.execute(
        "SELECT last_sent FROM alert_state WHERE device_id = ? AND alert_key = ?",
        (device_id, alert_key),
    ).fetchone()
    if row is None:
        return True
    return (now - parse_timestamp(row[0])).total_seconds() > cooldown_hours * 3600


def record_alert_sent(conn: sqlite3.Connection, device_id: str, alert_key: str,
                      now: datetime.datetime) -> None:
    """アラート送信時刻を記録する（クールダウン管理用）"""
    conn.execute(
        "INSERT OR REPLACE INTO alert_state (device_id, alert_key, last_sent) VALUES (?, ?, ?)",
        (device_id, alert_key, now.strftime('%Y-%m-%d %H:%M:%S')),
    )
    conn.commit()


# =============================================================================
# ingest: 取り込みとアラート判定
# =============================================================================

def ingest_incoming_files(conn: sqlite3.Connection, base_dir: str) -> int:
    """
    incoming/<デバイス名>/ に届いたCSVチャンクをDBに取り込む。

    - 主キー (device_id, timestamp) への INSERT OR IGNORE により、
      Piからの再送・重複データは自然に排除される
    - 取り込みに成功したファイルは削除する（データはDBにあり、NASスナップショットが保険）
    - 壊れたファイルは拡張子 .error を付けて残し、次回以降は処理しない

    Returns:
        取り込んだ行数
    """
    pattern = os.path.join(base_dir, 'incoming', '*', '*.csv')
    total_inserted = 0

    for file_path in sorted(glob.glob(pattern)):
        # デバイス名は incoming/ 直下のフォルダ名から取る
        device_id = os.path.basename(os.path.dirname(file_path))
        try:
            with open(file_path, newline='') as f:
                rows = list(csv.reader(f))

            valid_rows = []
            for row in rows[1:]:  # 先頭はヘッダー行
                if len(row) != 3:
                    continue
                timestamp_text, temperature_text, humidity_text = row
                # 不正な行が1つでもあればファイルごと保留するのではなく、行単位でスキップする
                parse_timestamp(timestamp_text)
                valid_rows.append((device_id, timestamp_text,
                                   float(temperature_text), float(humidity_text)))

            conn.executemany(
                "INSERT OR IGNORE INTO readings (device_id, timestamp, temperature, humidity) "
                "VALUES (?, ?, ?, ?)",
                valid_rows,
            )
            conn.commit()
            total_inserted += len(valid_rows)
            os.remove(file_path)
            logger.info(f"取り込み完了: {os.path.basename(file_path)} ({len(valid_rows)}行)")

        except Exception as e:
            logger.error(f"ファイルの取り込みに失敗しました: {file_path}: {e}")
            try:
                # 壊れたファイルを毎回処理し直さないよう .error を付けて退避する
                os.replace(file_path, file_path + '.error')
            except Exception as rename_error:
                logger.error(f"エラーファイルの退避にも失敗しました: {rename_error}")

    return total_inserted


def get_all_device_ids(conn: sqlite3.Connection) -> list:
    """DBに記録のある全デバイスIDを返す"""
    return [row[0] for row in conn.execute(
        "SELECT DISTINCT device_id FROM readings ORDER BY device_id")]


def check_rate_alerts(conn: sqlite3.Connection, config: dict, slack: SlackSender,
                      now: datetime.datetime) -> None:
    """
    温度変化率アラートの判定。

    デバイスごとに直近2点の測定から ΔT/Δt（°C/分）を計算し、
    |ΔT/Δt| > θ（θ = μ + k・σ）ならSlackに通知する。
    μ・σは daily 処理が thresholds.yaml に書き込んだ統計量を使う。
    """
    for device_id in get_all_device_ids(conn):
        rows = conn.execute(
            "SELECT timestamp, temperature FROM readings "
            "WHERE device_id = ? ORDER BY timestamp DESC LIMIT 2",
            (device_id,),
        ).fetchall()
        if len(rows) < 2:
            continue

        newest_time = parse_timestamp(rows[0][0])
        older_time = parse_timestamp(rows[1][0])

        # 古いデータしか無い場合は判定しない（同じペアを繰り返し判定しないため）
        if (now - newest_time).total_seconds() > RATE_ALERT_FRESHNESS_MINUTES * 60:
            continue

        # 測定間隔が空きすぎたペアは変化率が不正確なので判定しない
        gap_minutes = (newest_time - older_time).total_seconds() / 60
        if not (0 < gap_minutes <= MAX_PAIR_GAP_MINUTES):
            continue

        # ベースライン期間中（初データから baseline_days 日以内）は記録のみで発報しない
        first_row = conn.execute(
            "SELECT MIN(timestamp) FROM readings WHERE device_id = ?", (device_id,)
        ).fetchone()
        baseline_days = get_setting(config, device_id, 'baseline_days')
        if (now - parse_timestamp(first_row[0])).days < baseline_days:
            logger.debug(f"{device_id}: ベースライン期間中のためアラート判定をスキップ")
            continue

        # μ・σが未計算（daily がまだ動いていない）なら判定できない
        device_settings = config['devices'].get(device_id) or {}
        mu = device_settings.get('mu')
        sigma = device_settings.get('sigma')
        if mu is None or sigma is None:
            logger.debug(f"{device_id}: μ・σが未計算のためアラート判定をスキップ")
            continue

        rate = (rows[0][1] - rows[1][1]) / gap_minutes  # °C/分
        k = get_setting(config, device_id, 'k')
        threshold = mu + k * sigma

        if abs(rate) <= threshold:
            continue

        cooldown_hours = get_setting(config, device_id, 'alert_cooldown_hours')
        if not is_cooldown_passed(conn, device_id, 'rate', cooldown_hours, now):
            logger.info(f"{device_id}: 変化率超過を検出しましたがクールダウン中のため送信しません")
            continue

        direction = "上昇" if rate > 0 else "下降"
        message = (
            f":rotating_light: [{device_id}] 温度が急{direction}しています\n"
            f"変化率: {rate:+.3f}°C/分（閾値: ±{threshold:.3f}°C/分, k={k}）\n"
            f"直近の測定: {rows[1][1]}°C ({older_time:%H:%M}) → {rows[0][1]}°C ({newest_time:%H:%M})\n"
            f"以後{cooldown_hours}時間はこのデバイスの変化率アラートを送信しません"
        )
        if slack.post_message(message):
            record_alert_sent(conn, device_id, 'rate', now)
            logger.info(f"{device_id}: 変化率アラートを送信しました (rate={rate:+.3f}°C/分)")


def check_missing_data_alerts(conn: sqlite3.Connection, config: dict, slack: SlackSender,
                              now: datetime.datetime) -> None:
    """
    欠測アラートの判定。

    最終データが missing_data_hours（デフォルト2時間）以上前のデバイスを通知する。
    センサー故障・Piの停止・NASへの送信失敗のいずれもこの1本で検出できる。
    通知はデバイスごとに1日1回まで。
    """
    for device_id in get_all_device_ids(conn):
        row = conn.execute(
            "SELECT MAX(timestamp) FROM readings WHERE device_id = ?", (device_id,)
        ).fetchone()
        last_time = parse_timestamp(row[0])
        missing_hours = get_setting(config, device_id, 'missing_data_hours')

        elapsed_hours = (now - last_time).total_seconds() / 3600
        if elapsed_hours < missing_hours:
            continue

        # 1日1回まで（クールダウン24時間）
        if not is_cooldown_passed(conn, device_id, 'missing', 24, now):
            continue

        message = (
            f":warning: [{device_id}] データが {last_time:%m/%d %H:%M} から届いていません"
            f"（約{elapsed_hours:.1f}時間）\n"
            f"Piの電源・センサー配線・NASへの接続を確認してください。"
            f"手順書（OPERATIONS.md）の「トラブル対応」を参照。"
        )
        if slack.post_message(message):
            record_alert_sent(conn, device_id, 'missing', now)
            logger.info(f"{device_id}: 欠測アラートを送信しました")


def run_ingest(base_dir: str, slack: SlackSender) -> None:
    """ingest サブコマンド本体"""
    conn = open_database(base_dir)
    try:
        config = load_config(base_dir)
        now = datetime.datetime.now()

        inserted = ingest_incoming_files(conn, base_dir)
        logger.info(f"取り込み処理完了: {inserted}行")

        check_rate_alerts(conn, config, slack, now)
        check_missing_data_alerts(conn, config, slack, now)
    finally:
        conn.close()


# =============================================================================
# daily: 日次集計と統計量の再計算
# =============================================================================

def update_daily_summary(conn: sqlite3.Connection) -> None:
    """
    完了した日（今日より前）の日次集計を計算する。

    INSERT OR REPLACE で毎回全期間を再計算する（データ量は10年で200万行程度と
    小さいため、差分管理より単純さを優先。遅延取り込みで過去の日が更新されても
    自動的に集計へ反映される利点もある）。
    """
    conn.execute("""
        INSERT OR REPLACE INTO daily_summary
            (device_id, date, temp_min, temp_max, temp_avg, humid_min, humid_max, humid_avg)
        SELECT device_id, date(timestamp),
               MIN(temperature), MAX(temperature), ROUND(AVG(temperature), 3),
               MIN(humidity), MAX(humidity), ROUND(AVG(humidity), 3)
        FROM readings
        WHERE date(timestamp) < date('now', 'localtime')
        GROUP BY device_id, date(timestamp)
    """)
    conn.commit()


def compute_rate_statistics(conn: sqlite3.Connection, device_id: str,
                            now: datetime.datetime) -> tuple:
    """
    過去 STATS_WINDOW_DAYS 日の測定から |ΔT/Δt| の平均μと標準偏差σを計算する。

    Returns:
        (mu, sigma, サンプル数)。サンプル数が不足していれば (None, None, 数)
    """
    window_start = (now - datetime.timedelta(days=STATS_WINDOW_DAYS)).strftime('%Y-%m-%d %H:%M:%S')
    rows = conn.execute(
        "SELECT timestamp, temperature FROM readings "
        "WHERE device_id = ? AND timestamp >= ? ORDER BY timestamp",
        (device_id, window_start),
    ).fetchall()

    absolute_rates = []
    for (time1, temp1), (time2, temp2) in zip(rows, rows[1:]):
        gap_minutes = (parse_timestamp(time2) - parse_timestamp(time1)).total_seconds() / 60
        if 0 < gap_minutes <= MAX_PAIR_GAP_MINUTES:
            absolute_rates.append(abs((temp2 - temp1) / gap_minutes))

    if len(absolute_rates) < STATS_MIN_SAMPLES:
        return None, None, len(absolute_rates)

    return statistics.mean(absolute_rates), statistics.stdev(absolute_rates), len(absolute_rates)


def run_daily(base_dir: str, slack: SlackSender) -> None:
    """daily サブコマンド本体"""
    conn = open_database(base_dir)
    try:
        config = load_config(base_dir)
        now = datetime.datetime.now()

        update_daily_summary(conn)
        logger.info("日次集計を更新しました")

        # デバイスごとにμ・σを再計算してthresholds.yamlを更新する。
        # k や cooldown などの手動設定値はそのまま残し、統計量だけを書き換える
        for device_id in get_all_device_ids(conn):
            mu, sigma, sample_count = compute_rate_statistics(conn, device_id, now)
            device_settings = config['devices'].setdefault(device_id, {})
            if mu is None:
                logger.warning(
                    f"{device_id}: 変化率のサンプル数が不足しています "
                    f"({sample_count}/{STATS_MIN_SAMPLES})。μ・σは更新しません"
                )
                continue
            device_settings['mu'] = round(mu, 5)
            device_settings['sigma'] = round(sigma, 5)
            device_settings['stats_updated'] = now.strftime('%Y-%m-%d')
            device_settings['stats_samples'] = sample_count
            logger.info(f"{device_id}: μ={mu:.5f}, σ={sigma:.5f} (n={sample_count}) に更新")

        save_config(base_dir, config)
    finally:
        conn.close()


# =============================================================================
# weekly-report: 週次スモールマルチプルレポート
# =============================================================================

def create_weekly_graph(readings_by_device: dict, output_path: str,
                        start_time: datetime.datetime, end_time: datetime.datetime) -> bool:
    """
    全デバイスの温度・湿度をスモールマルチプル（行=デバイス、列=温度/湿度）で
    1枚の画像に描画する。

    設置場所ごとに平常時のレンジが異なるため、Y軸はパネルごとに独立させる
    （重ね書きにしない・共通Y軸にしないのは要件による設計判断）。
    グラフ内の文字は、日本語フォントの無い環境での文字化けを防ぐため英語のみ。
    """
    # matplotlibはコレクターでしか使わないため、ここでimportする。
    # Aggバックエンドは画面の無い環境（systemd実行）用
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates

    try:
        device_ids = sorted(readings_by_device.keys())
        n_devices = len(device_ids)
        fig, axes = plt.subplots(
            n_devices, 2,
            figsize=(12, 2.6 * n_devices + 0.8),
            squeeze=False, sharex=True,
        )

        for row_index, device_id in enumerate(device_ids):
            rows = readings_by_device[device_id]
            times = [parse_timestamp(r[0]) for r in rows]
            temperatures = [r[1] for r in rows]
            humidities = [r[2] for r in rows]

            temp_ax = axes[row_index][0]
            temp_ax.plot(times, temperatures, color='tab:red', linewidth=0.9)
            temp_ax.set_title(f"{device_id} - Temperature (C)", fontsize=10)
            temp_ax.grid(True, alpha=0.4)

            humid_ax = axes[row_index][1]
            humid_ax.plot(times, humidities, color='tab:blue', linewidth=0.9)
            humid_ax.set_title(f"{device_id} - Humidity (%)", fontsize=10)
            humid_ax.grid(True, alpha=0.4)

            for ax in (temp_ax, humid_ax):
                ax.set_xlim([start_time, end_time])
                ax.xaxis.set_major_formatter(mdates.DateFormatter('%m/%d'))

        fig.suptitle(
            f"Weekly Report  {start_time:%Y-%m-%d} - {end_time:%Y-%m-%d}",
            fontsize=13,
        )
        fig.tight_layout(rect=[0, 0, 1, 0.97])
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        fig.savefig(output_path, dpi=110)
        plt.close(fig)
        return True

    except Exception as e:
        logger.error(f"グラフ作成エラー: {e}")
        traceback.print_exc()
        return False


def build_weekly_comment(conn: sqlite3.Connection, device_ids_with_data: list,
                         all_device_ids: list,
                         start_time: datetime.datetime, end_time: datetime.datetime) -> str:
    """週次レポートに添えるコメント（各デバイスの週間min/max/avgと欠測注記）を作る"""
    lines = [f"週間レポート ({start_time:%m/%d} 〜 {end_time:%m/%d})"]

    for device_id in all_device_ids:
        if device_id not in device_ids_with_data:
            lines.append(f"- {device_id}: 今週のデータなし（要確認）")
            continue
        row = conn.execute(
            "SELECT MIN(temp_min), MAX(temp_max), ROUND(AVG(temp_avg), 1), "
            "       MIN(humid_min), MAX(humid_max), ROUND(AVG(humid_avg), 1) "
            "FROM daily_summary WHERE device_id = ? AND date >= ? AND date <= ?",
            (device_id, start_time.strftime('%Y-%m-%d'), end_time.strftime('%Y-%m-%d')),
        ).fetchone()
        if row is None or row[0] is None:
            lines.append(f"- {device_id}: 集計データなし")
            continue
        lines.append(
            f"- {device_id}: 温度 {row[0]}〜{row[1]}°C (平均 {row[2]}°C), "
            f"湿度 {row[3]}〜{row[4]}% (平均 {row[5]}%)"
        )
    return "\n".join(lines)


def run_weekly_report(base_dir: str, slack: SlackSender) -> None:
    """weekly-report サブコマンド本体"""
    conn = open_database(base_dir)
    try:
        end_time = datetime.datetime.now()
        start_time = end_time - datetime.timedelta(days=7)

        # 最新の集計をコメントに使えるよう、レポート前に日次集計を更新しておく
        update_daily_summary(conn)

        all_device_ids = get_all_device_ids(conn)
        if not all_device_ids:
            slack.post_message("週間レポート: データが1件もありません。システムの状態を確認してください。")
            logger.warning("週次レポート: DBにデータがありません")
            return

        # 期間内のデータをデバイスごとに取得する
        readings_by_device = {}
        for device_id in all_device_ids:
            rows = conn.execute(
                "SELECT timestamp, temperature, humidity FROM readings "
                "WHERE device_id = ? AND timestamp >= ? ORDER BY timestamp",
                (device_id, start_time.strftime('%Y-%m-%d %H:%M:%S')),
            ).fetchall()
            if rows:
                readings_by_device[device_id] = rows

        if not readings_by_device:
            slack.post_message("週間レポート: 今週のデータがありません。全デバイスの状態を確認してください。")
            logger.warning("週次レポート: 期間内のデータがありません")
            return

        # グラフ画像はNAS上の月別フォルダにアーカイブとして直接生成する
        output_path = os.path.join(
            base_dir, 'reports', 'weekly',
            f"{end_time:%Y-%m}", f"weekly_{end_time:%Y%m%d}.png",
        )
        if not create_weekly_graph(readings_by_device, output_path, start_time, end_time):
            return

        comment = build_weekly_comment(
            conn, list(readings_by_device.keys()), all_device_ids, start_time, end_time)
        if slack.upload_file(output_path, "Weekly Report", comment):
            logger.info(f"週次レポートを送信しました: {output_path}")
    finally:
        conn.close()


# =============================================================================
# エントリポイント
# =============================================================================

def run_status(base_dir: str) -> None:
    """
    各デバイスの受信状況を画面に表示する（読み取り専用の動作確認コマンド）。

    Slackには何も送らず、DBにも書き込まない。手動実行専用なので、
    ログファイルではなく print で直接表示する。
    """
    now = datetime.datetime.now()
    print(f"===== 受信状況 ({now.strftime('%Y-%m-%d %H:%M:%S')}) =====")

    # DBに入っている各デバイスの最終データと件数
    conn = open_database(base_dir)
    try:
        summary_rows = conn.execute(
            "SELECT device_id, COUNT(*), MAX(timestamp) "
            "FROM readings GROUP BY device_id ORDER BY device_id"
        ).fetchall()
        if not summary_rows:
            print("データベースにデータがまだ1件もありません。")
            print("  センサーPiの送信と、collector-ingest の実行を確認してください。")
        for device_id, row_count, last_timestamp in summary_rows:
            temperature, humidity = conn.execute(
                "SELECT temperature, humidity FROM readings "
                "WHERE device_id = ? AND timestamp = ?",
                (device_id, last_timestamp)
            ).fetchone()
            elapsed_minutes = int((now - parse_timestamp(last_timestamp)).total_seconds() // 60)
            # 欠測アラートと同じ2時間を目安に注意表示を付ける
            warning_label = "  <-- 2時間以上データが届いていません（要確認）" if elapsed_minutes >= 120 else ""
            print(
                f"  {device_id}: 最終 {last_timestamp} ({elapsed_minutes}分前) "
                f"温度 {temperature}C / 湿度 {humidity}% / 累計 {row_count}行{warning_label}"
            )
    finally:
        conn.close()

    # incoming に残っている未取り込みファイル数（次のingestで取り込まれる分）
    pending_files = glob.glob(os.path.join(base_dir, 'incoming', '*', '*.csv'))
    print(f"未取り込みファイル: {len(pending_files)}件"
          + ("（次の collector-ingest で取り込まれます）" if pending_files else ""))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='温湿度データコレクター')
    parser.add_argument(
        'command',
        choices=['ingest', 'daily', 'weekly-report', 'status'],
        help='ingest: 取り込み＋アラート判定（10分ごと） / '
             'daily: 日次集計＋閾値統計の更新（1日1回） / '
             'weekly-report: 週次レポート送信（週1回） / '
             'status: 各デバイスの受信状況を表示（手動確認用・Slack設定不要）'
    )
    parser.add_argument(
        '--base-dir',
        default='/mnt/sensor_data',
        help='NAS共有フォルダのマウント先（デフォルト: /mnt/sensor_data）'
    )
    parser.add_argument(
        '--no-slack',
        action='store_true',
        help='Slackに送信せず、送る内容をログに出すだけにする（動作確認用）'
    )
    parser.add_argument('--debug', action='store_true', help='デバッグログを有効化')
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if not os.path.isdir(args.base_dir):
        # loggingセットアップ前なのでprintで出す（ログ先自体がNAS上のため）
        print(
            f"エラー: NAS共有フォルダが見つかりません: {args.base_dir}\n"
            f"  マウントされているか確認してください: ls {args.base_dir}\n"
            f"  マウントし直す場合: sudo mount -a",
            file=sys.stderr,
        )
        raise SystemExit(1)

    # status は読み取り専用の手動確認コマンド。Slack設定（環境変数）が無くても
    # 動くように、SlackSenderの初期化より前に処理する
    if args.command == 'status':
        run_status(args.base_dir)
        return

    setup_logging(args.base_dir, args.debug)
    slack = SlackSender(no_slack=args.no_slack)

    try:
        if args.command == 'ingest':
            run_ingest(args.base_dir, slack)
        elif args.command == 'daily':
            run_daily(args.base_dir, slack)
        elif args.command == 'weekly-report':
            run_weekly_report(args.base_dir, slack)
    except Exception as e:
        logger.error(f"予期せぬエラーが発生しました: {e}")
        traceback.print_exc()
        raise SystemExit(1)


if __name__ == '__main__':
    main()
