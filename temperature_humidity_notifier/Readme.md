# 温湿度モニタリングシステム

Raspberry Pi と DHT22 センサーで室内の温度・湿度を定期的に監視し、Slack に通知するシステムです。

**できること:**
- 10分ごとにセンサーを読み取り、データを CSV に記録
- 温湿度が閾値を超えたら即座に Slack へアラート送信（12時間以内の重複通知を抑制）
- 30分・1日ごとにグラフ画像と CSV を Slack に自動送信
- WiFi が切断されたら自動で再接続
- 実センサー不要のテストモードで動作確認が可能

---

## 目次

1. [必要なもの](#1-必要なもの)
2. [配線方法](#2-配線方法)
3. [Raspberry Pi のセットアップ](#3-raspberry-pi-のセットアップ)
4. [Slack アプリの設定](#4-slack-アプリの設定)
5. [環境変数の設定](#5-環境変数の設定)
6. [設定パラメータの変更](#6-設定パラメータの変更)
7. [起動方法](#7-起動方法)
8. [systemd サービス化（常駐起動）](#8-systemd-サービス化常駐起動)
9. [ファイル構成](#9-ファイル構成)
10. [トラブルシューティング](#10-トラブルシューティング)

---

## 1. 必要なもの

### ハードウェア

| 機材 | 備考 |
|---|---|
| Raspberry Pi 3B+ または 4 | 他のモデルでも動作する可能性はあります |
| DHT22 温湿度センサーモジュール | モジュール品（基板付き）推奨。外部プルアップ抵抗が不要なため |
| ジャンパーワイヤー（オス-メス）3本 | センサーと Pi を接続するのに使います |

> **センサーについて**: DHT22 は単体の素子ではなく、基板に取り付けられた「モジュール品」を購入してください。モジュール品にはプルアップ抵抗が内蔵されており、3本のワイヤーを差すだけで動作します。

### ソフトウェア

- Raspberry Pi OS（64bit 推奨）
- Python 3.9 以上

---

## 2. 配線方法

DHT22 センサーモジュールの端子と Raspberry Pi のピンを以下のように接続します。

```
DHT22 モジュール          Raspberry Pi（物理ピン番号）
─────────────            ──────────────────────────
VCC（+）      ────────── Pin 2（5V）
DATA（out）   ────────── Pin 7（GPIO4 / BCM4）
GND（-）      ────────── Pin 6（GND）
```

Raspberry Pi のピン配置（左上から見た図）:

```
 [USB側]
  3V3(1) (2)5V    ← Pin 2 に VCC を接続
  SDA(3) (4)5V
  SCL(5) (6)GND   ← Pin 6 に GND を接続
GPIO4(7) (8)TXD   ← Pin 7 に DATA を接続
  GND(9) (10)RXD
 ...
```

> **注意**: 配線を間違えるとセンサーや Pi が壊れることがあります。特に VCC と GND の逆接に注意してください。電源を入れる前にもう一度確認することをおすすめします。

---

## 3. Raspberry Pi のセットアップ

### 3-1. システムパッケージのインストール

```bash
sudo apt-get update
sudo apt-get install -y python3-pip python3-dev python3-venv
sudo apt-get install -y build-essential libssl-dev libffi-dev
```

### 3-2. 仮想環境の作成（推奨）

Raspberry Pi OS 2023 以降では、システム管理の Python 環境への `pip` インストールが制限されています。
仮想環境を使うことで、この制限を回避できます。

```bash
# プロジェクトのディレクトリに移動
cd /home/pi/temperature_humidity_notifier

# 仮想環境を作成（venv というフォルダが作られます）
python3 -m venv venv

# 仮想環境を有効化（このターミナルを閉じるまで有効）
source venv/bin/activate

# 有効化できているか確認（(venv) と表示されればOK）
which python3
# → /home/pi/temperature_humidity_notifier/venv/bin/python3
```

> 仮想環境を使わない場合は `--break-system-packages` オプションを付けることで
> システム環境にインストールできますが、推奨しません。

### 3-3. Python ライブラリのインストール

仮想環境を有効化した状態で実行します。

```bash
pip install adafruit-circuitpython-dht   # DHT22 センサー用ドライバ
pip install adafruit-blinka              # board モジュールの提供元（pip install board ではない）
pip install slack_sdk                    # Slack SDK
pip install pandas matplotlib            # データ処理とグラフ作成
pip install RPi.GPIO                     # GPIO 制御
pip install python-dotenv                # .env ファイルの読み込み（任意）
```

> **`board` モジュールについて**: `pip install board` では動作しません。
> `adafruit-blinka` のインストールによって `board` が使えるようになります。

### 3-4. GPIO グループへの追加（権限エラーが出る場合）

```bash
sudo usermod -aG gpio pi
# 変更を反映するために一度ログアウトして再ログインしてください
```

---

## 4. Slack アプリの設定

### 4-1. Slack アプリの作成

1. [Slack API](https://api.slack.com/apps) にアクセスし「**Create New App**」をクリック
2. 「**From scratch**」を選択
3. App Name（例: `sensor-notifier`）と使用するワークスペースを指定して「Create App」

### 4-2. Bot の権限（スコープ）を設定

左メニューの「**OAuth & Permissions**」→「**Scopes**」→「**Bot Token Scopes**」で以下を追加:

| スコープ | 用途 |
|---|---|
| `chat:write` | メッセージ・アラートの送信 |
| `files:write` | グラフ画像・CSV ファイルの送信 |

### 4-3. アプリをワークスペースにインストール

1. 左メニューの「**OAuth & Permissions**」→「**Install to Workspace**」をクリック
2. 権限を確認して「許可する」
3. 表示された「**Bot User OAuth Token**」（`xoxb-` で始まる文字列）をコピーして保管

### 4-4. 通知チャンネルの作成と Bot の招待

1. Slack で通知用チャンネルを作成（例: `#sensor-notify`）
2. そのチャンネルを開き、メッセージ入力欄に以下を入力して Bot を招待:

```
/invite @あなたのボット名
```

---

## 5. 環境変数の設定

Slack のトークンとチャンネル名はセキュリティ上、コードに直書きせず環境変数で渡します。

### 方法 A: `.env` ファイルを使う（推奨・Thonny 利用者向け）

プロジェクトディレクトリに `.env` というファイルを作成します:

```bash
nano /home/pi/temperature_humidity_notifier/.env
```

以下の内容を書いて保存（`Ctrl+O` → `Ctrl+X`）:

```
SLACK_TOKEN=xoxb-xxxx-xxxx-xxxx
SLACK_CHANNEL=#sensor-notify
```

> `.env` ファイルは起動時に自動で読み込まれます。
> Git に含めないように `.gitignore` に追加することをおすすめします。

### 方法 B: ターミナルで `export` する

```bash
export SLACK_TOKEN="xoxb-xxxx-xxxx-xxxx"
export SLACK_CHANNEL="#sensor-notify"
```

> この方法はターミナルを閉じると設定が消えます。
> 毎回手動で入力するか、`~/.bashrc` に追記してください。

### 方法 C: `~/.bashrc` に追記して恒久的に設定する

```bash
echo 'export SLACK_TOKEN="xoxb-xxxx-xxxx-xxxx"' >> ~/.bashrc
echo 'export SLACK_CHANNEL="#sensor-notify"' >> ~/.bashrc
source ~/.bashrc
```

### 設定の確認

```bash
echo $SLACK_TOKEN    # xoxb-... と表示されればOK
echo $SLACK_CHANNEL  # #sensor-notify と表示されればOK
```

---

## 6. 設定パラメータの変更

閾値や測定間隔などは `config.py` の dataclass で一元管理しています。
変更したい項目に応じて、以下の該当箇所を編集してください。

```python
# config.py

@dataclass
class ThresholdConfig:
    temp_max: float = 23.0       # 温度の上限閾値（°C）。これを超えるとアラート
    temp_min: float = 17.0       # 温度の下限閾値（°C）。これを下回るとアラート
    humidity_max: float = 70.0   # 湿度の上限閾値（%）
    humidity_min: float = 40.0   # 湿度の下限閾値（%）
    alert_cooldown_sec: int = 43200  # 同じアラートを再送するまでの待機時間（秒）。デフォルト12時間

@dataclass
class ScheduleConfig:
    check_interval_sec: int = 600        # センサー測定間隔（秒）。デフォルト10分
    short_report_interval_min: int = 30  # 短期レポートを送るタイミング（起動後○分）
    long_report_interval_days: int = 1   # 長期レポートの間隔（日）

@dataclass
class NetworkConfig:
    router_ip: str = '192.168.10.1'  # ← お使いのルーターのIPに合わせて変更
```

**設定例**: 温度の上限を 25°C に変更したい場合:

```python
# config.py の ThresholdConfig を以下のように変更
temp_max: float = 25.0
```

---

## 7. 起動方法

### 通常起動

```bash
# 仮想環境を有効化してから起動
source venv/bin/activate
python3 temp_humid_notifier.py
```

起動すると以下のような出力が表示されます:

```
2026-02-25 12:00:00 - INFO - 起動時のネットワーク状態を確認しています...
2026-02-25 12:00:01 - INFO - Slack認証成功: sensor-bot
2026-02-25 12:00:02 - INFO - DHT22センサーを初期化しました
2026-02-25 12:00:02 - INFO - センサー監視を開始します
2026-02-25 12:10:00 - INFO - [2026-02-25 12:10:00] 温度: 21.5°C, 湿度: 55.2%
```

### テストモード（センサーなしで動作確認）

センサーを接続していなくても、ダミーデータで Slack 通知の動作確認ができます:

```bash
python3 temp_humid_notifier.py --test-mode
```

10% の確率でアラートが発生するダミーデータが生成されるので、
通知が届くかどうかをすぐに確認できます。

### ログの保存先を変更して起動

```bash
python3 temp_humid_notifier.py --save-dir /home/pi/sensor_logs
```

CSV ファイル、グラフ画像、ログファイルがすべて指定フォルダに保存されます。

### デバッグログを有効にして起動

通常は表示されない詳細なログ（センサーの一時的な読み取り失敗など）が表示されます:

```bash
python3 temp_humid_notifier.py --debug
```

### 停止方法

ターミナルで実行中の場合は `Ctrl+C` で停止します。
GPIO のクリーンアップは自動で行われます。

---

## 8. systemd サービス化（常駐起動）

Raspberry Pi の起動時に自動でプログラムを起動し、クラッシュしても自動再起動させます。

### 8-1. メインプログラムのサービス化

#### サービスファイルを作成

```bash
sudo nano /etc/systemd/system/temp-humid-notifier.service
```

以下を貼り付けて保存（`/home/pi/` のパスは実際の場所に合わせて変更）:

```ini
[Unit]
Description=Temperature & Humidity Notifier
# ネットワークが使えるようになってから起動する
After=network-online.target
Wants=network-online.target

[Service]
# 環境変数を直接指定（.envファイルを使う場合は EnvironmentFile を使う方法もある）
Environment="SLACK_TOKEN=xoxb-xxxx-xxxx-xxxx"
Environment="SLACK_CHANNEL=#sensor-notify"
ExecStart=/home/pi/temperature_humidity_notifier/venv/bin/python3 \
          /home/pi/temperature_humidity_notifier/temp_humid_notifier.py \
          --save-dir /home/pi/sensor_logs
WorkingDirectory=/home/pi/temperature_humidity_notifier
Restart=on-failure
RestartSec=10
User=pi

[Install]
WantedBy=multi-user.target
```

#### サービスを有効化・起動

```bash
# systemd にサービスを認識させる
sudo systemctl daemon-reload

# OS 起動時に自動起動するよう登録
sudo systemctl enable temp-humid-notifier.service

# 今すぐ起動
sudo systemctl start temp-humid-notifier.service

# 動作状態を確認
sudo systemctl status temp-humid-notifier.service
```

#### ログの確認

```bash
# リアルタイムでログを表示（Ctrl+C で終了）
sudo journalctl -u temp-humid-notifier.service -f

# 過去のログを最新50行だけ表示
sudo journalctl -u temp-humid-notifier.service -n 50
```

### 8-2. WiFi 自動再接続サービスのセットアップ

WiFi が切断されやすい環境では、`reconnect_wifi.py` を別のサービスとして常駐させます。

```bash
sudo nano /etc/systemd/system/wifi-monitor.service
```

```ini
[Unit]
Description=WiFi Connection Monitor
After=network.target

[Service]
ExecStart=/home/pi/temperature_humidity_notifier/venv/bin/python3 \
          /home/pi/temperature_humidity_notifier/reconnect_wifi.py
Restart=always
User=pi

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable wifi-monitor.service
sudo systemctl start wifi-monitor.service
```

---

## 9. ファイル構成

```
temperature_humidity_notifier/
│
├── temp_humid_notifier.py  # メインスクリプト（制御フローのみ）
│
├── config.py               # 全設定パラメータ（閾値・間隔など）
├── sensor.py               # DHT22 センサー読み取りクラス
├── network.py              # ネットワーク診断・自動復旧クラス
├── notifier.py             # Slack 通知・アラート管理クラス
├── reporter.py             # グラフ生成・レポート送信
│
├── reconnect_wifi.py       # WiFi 接続確認・再接続ユーティリティ
├── gpio_reset.py           # GPIO 強制リセットスクリプト
│
├── .env                    # 環境変数ファイル（自分で作成・Git に含めない）
└── Readme.md               # このファイル
```

設定を変更したいときの対応表:

| やりたいこと | 変更するファイル |
|---|---|
| 温湿度の閾値を変えたい | `config.py` の `ThresholdConfig` |
| 測定間隔・レポート間隔を変えたい | `config.py` の `ScheduleConfig` |
| ルーターの IP アドレスを変えたい | `config.py` の `NetworkConfig` |
| Slack トークン・チャンネルを変えたい | `.env` ファイル（コードに書かない） |
| センサーのピンを変えたい | `config.py` の `SensorConfig` |

---

## 10. トラブルシューティング

### センサーの読み取りに失敗する

**症状**: `DHT 取得失敗` というログが頻繁に出る。

DHT22 は仕様上、10〜15% 程度の確率で読み取りに失敗します（設計上の限界）。
数回の失敗は正常なので、ログが出続けても慌てなくて大丈夫です。

**それでも読み取れない場合**:

1. 配線を確認する（特に DATA ピンと GND の接続）
2. 別の GND ピンを試す
3. GPIO をリセットしてから再起動する:

```bash
python3 gpio_reset.py
python3 temp_humid_notifier.py
```

4. `sudo` で実行してみる（GPIO 権限の問題の可能性）:

```bash
sudo python3 temp_humid_notifier.py
```

---

### 「already in use」「unable to set line to input」エラーが出る

**原因**: 以前の実行が正常に終了せず、GPIO が占有されたままになっています。
Thonny で「Stop」ボタンを押さずにウィンドウを閉じたときなどに発生します。

**対処**:

```bash
# 動いているプロセスを確認する
ps aux | grep temp_humid_notifier

# PID を確認して強制終了（12345 の部分は実際の PID に変える）
sudo kill 12345

# GPIO をリセット
python3 gpio_reset.py
```

---

### 「既にプロセスが動いています」と表示されて起動しない

多重起動防止の仕組みが働いています。以下の順番で確認してください。

```bash
# 1. PIDファイルを確認
cat /tmp/temp_humid_notifier.pid

# 2. そのプロセスが本当に動いているか確認（何も表示されなければ既に終了済み）
ps aux | grep 表示されたPID

# 3. PIDファイルを削除してから再起動
rm /tmp/temp_humid_notifier.pid
python3 temp_humid_notifier.py
```

---

### Slack にメッセージが届かない

起動時のログに詳細なエラーコードと対処法が出力されます。
まずログを確認してください。

```bash
# ログファイルを確認
tail -50 temp_humid_notifier.log
```

代表的なエラーと対処法:

| エラーコード | 原因 | 対処法 |
|---|---|---|
| `invalid_auth` | トークンが無効 | `echo $SLACK_TOKEN` で確認。再発行が必要な場合は Slack API から再取得 |
| `channel_not_found` | チャンネル名が間違っている | `echo $SLACK_CHANNEL` で確認。`#` を忘れずに |
| `not_in_channel` | Bot がチャンネルに参加していない | チャンネルで `/invite @ボット名` を実行 |
| `missing_scope` | Bot の権限が不足 | Slack API の「OAuth & Permissions」で `chat:write` と `files:write` を追加して再インストール |

---

### WiFi がよく切れる

`reconnect_wifi.py` を systemd サービスとして常駐させてください（[8-2 参照](#8-2-wifi-自動再接続サービスのセットアップ)）。

それでも切れる場合は、WiFi の電力管理を無効化する設定が効果的なことがあります:

```bash
# 現在の電力管理状態を確認
iwconfig wlan0 | grep 'Power Management'

# 電力管理を無効化（再起動すると元に戻ります）
sudo iwconfig wlan0 power off
```

恒久的に無効化するには:

```bash
sudo nano /etc/rc.local
# exit 0 の前に以下を追記
iwconfig wlan0 power off
```

---

## 参考資料

- [Raspberry Pi GPIO ピン配置](https://pinout.xyz/)
- [SunFounder DHT11 センサー解説](https://docs.sunfounder.com/projects/umsk/ja/latest/05_raspberry_pi/pi_lesson19_dht11.html)
- [Adafruit CircuitPython DHT ライブラリ](https://github.com/adafruit/Adafruit_CircuitPython_DHT)
- [Slack API ドキュメント](https://api.slack.com/docs)

---

## ライセンス

MIT License

## 作者

Shinichi Miyazaki

---

> **注意**: DHT22 センサーは測定精度に ±0.5°C / ±2〜5% 程度のばらつきがあります。
> 研究用途など高精度が必要な場合は、SHT31 などより高精度なセンサーの使用を検討してください。
