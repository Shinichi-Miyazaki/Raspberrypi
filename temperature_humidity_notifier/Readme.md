# 温湿度モニタリングシステム

## 概要
Raspberry PiとDHT22温湿度センサーを使用して、環境の温度と湿度を定期的に監視しSlackに通知するシステムです。
測定データはCSVファイルに記録され、定期的にグラフ化されたレポートがSlackに送信されます。
温度や湿度が設定した閾値を超えると、自動的にアラート通知を送信します。

## 機能
- 温度と湿度の定期測定（デフォルト: 10分ごと）とCSV記録
- 閾値を超えた場合のSlackアラート通知（12時間以内の重複通知を抑制）
- 30分・1日ごとのグラフレポートをSlackに自動送信
- WiFi切断時の自動再接続（`reconnect_wifi.py` + systemdサービス）
- テストモード対応（実センサーなしで動作確認可能）
- センサーエラーや接続エラーの詳細ログ出力

## 必要な機材
- Raspberry Pi 3B+ または 4 推奨
- DHT22温湿度センサーモジュール
  - モジュール品には内部プルアップ抵抗が含まれていることが多いため、外部抵抗は不要な場合がほとんどです
  - 参考品例: [こちら](https://electronicwork.shop/items/61fc88ba47a5344c4730cb42)
- ジャンパーワイヤー（オス-メス） 3本

## 配線方法
DHT22センサーとRaspberry Piを以下のように接続します：

| センサーピン | Raspberry Pi |
|---|---|
| VCC（+） | 5V（Pin 2 または Pin 4） |
| DATA（out） | GPIO 4 / BCM4（Pin 7） |
| GND（-） | GND（Pin 6、9、14 など） |

## セットアップ手順

### 1. Raspberry Pi OSのセットアップ
Raspberry Pi OSが既にインストールされていることを前提としています。
まだの場合は [Raspberry Pi Imager](https://www.raspberrypi.com/software/) でセットアップしてください。

### 2. 必要なパッケージのインストール
```bash
sudo apt-get update
sudo apt-get install -y python3-pip python3-dev
sudo apt-get install -y build-essential libssl-dev libffi-dev
sudo apt-get install -y python3-matplotlib
```

### 3. 必要なPythonライブラリのインストール

> **注意（2025年以降のOS）**: Raspberry Pi OSのバージョンによっては、システム管理のPython環境へのpipインストールが制限されています。
> その場合は仮想環境を使うか、`--break-system-packages` オプションを付けてインストールしてください。

```bash
pip install adafruit-circuitpython-dht
pip install adafruit-blinka
pip install slack_sdk
pip install pandas matplotlib
pip install RPi.GPIO
```

> **補足**: `adafruit-blinka` が `board` モジュールを提供します。`pip install board` では正しくインストールされないため注意してください。

## Slack設定

### 1. Slackアプリの作成
1. [Slack API](https://api.slack.com/apps) にアクセスし「Create New App」をクリック
2. 「From scratch」を選択し、アプリ名とワークスペースを指定

### 2. 権限（スコープ）の設定
「OAuth & Permissions」→「Scopes」で以下を追加：
- `chat:write`（メッセージ送信用）
- `files:write`（ファイルアップロード用）

### 3. アプリのインストールとトークン取得
1. 「Install to Workspace」でワークスペースにインストール
2. 「Bot User OAuth Token」（`xoxb-` で始まる文字列）をコピー

### 4. チャンネルの作成とBot招待
1. 通知用チャンネルを作成（例: `#sensor-notify`）
2. チャンネルでBotを招待: `/invite @あなたのボット名`

## 設定パラメータ

### Slack接続情報（環境変数で設定）
Slack接続情報は**環境変数**で渡します。セキュリティ上、コードに直書きしないでください。

```bash
export SLACK_TOKEN="xoxb-xxxx-..."
export SLACK_CHANNEL="#sensor-notify"
```

### その他のパラメータ（コード冒頭で変更）
`temp_humid_notifier.py` の冒頭部分で変更できます：

| 変数名 | デフォルト | 説明 |
|---|---|---|
| `TEMP_MAX` | 23 | 温度の上限閾値 (°C) |
| `TEMP_MIN` | 17 | 温度の下限閾値 (°C) |
| `HUMIDITY_MAX` | 70 | 湿度の上限閾値 (%) |
| `HUMIDITY_MIN` | 40 | 湿度の下限閾値 (%) |
| `CHECK_INTERVAL` | 600 | センサー測定間隔 (秒) |
| `SHORT_REPORT_INTERVAL` | 30 | 短期レポート間隔 (分) |
| `LONG_REPORT_INTERVAL` | 1 | 長期レポート間隔 (日) |

## 使用方法

```bash
# 環境変数を設定してから起動
export SLACK_TOKEN="xoxb-xxxx-..."
export SLACK_CHANNEL="#sensor-notify"

# 通常起動（実センサー使用）
python3 temp_humid_notifier.py

# テストモード（センサーなしで動作確認）
python3 temp_humid_notifier.py --test-mode

# ログファイルの保存先を指定
python3 temp_humid_notifier.py --save-dir /home/pi/sensor_logs

# デバッグログを有効化
python3 temp_humid_notifier.py --debug
```

## WiFi自動再接続のセットアップ

定期的にWiFiが切断される場合は、`reconnect_wifi.py` をsystemdサービスとして常駐させることで自動復旧できます。

### 1. スクリプトを実行可能に設定
```bash
chmod +x reconnect_wifi.py
```

### 2. systemdサービスファイルを作成
```bash
sudo nano /etc/systemd/system/wifi-monitor.service
```

以下の内容を貼り付けてください（`/path/to/` は実際のパスに書き換えること）：

```ini
[Unit]
Description=WiFi Connection Monitor
After=network.target

[Service]
ExecStart=/usr/bin/python3 /path/to/reconnect_wifi.py
Restart=always
User=pi

[Install]
WantedBy=multi-user.target
```

`Ctrl+O` で保存、`Ctrl+X` で終了。

### 3. サービスを有効化・起動
```bash
sudo systemctl enable wifi-monitor.service
sudo systemctl start wifi-monitor.service
```

## トラブルシューティング

### センサー読み取りエラー
- センサーの配線を確認してください（特にDATAピンとGNDの接続）
- 別のGPIOピンを試す場合は `temp_humid_notifier.py` の `DHT_PIN = board.D4` を変更してください
- `sudo` でプログラムを実行するとGPIO権限の問題を解決できることがあります

### GPIOの初期化エラー「unable to set line XX to input」
`adafruit_circuitpython_dht` と `use_pulseio=False` の相性が悪いため、このオプションは指定していません。
それでもエラーが出る場合は、`gpio_reset.py` を実行してGPIOをリセットしてください：

```bash
python3 gpio_reset.py
```

### Slack接続エラー
- 環境変数が正しく設定されているか確認: `echo $SLACK_TOKEN`
- トークンに `chat:write` と `files:write` スコープがあるか確認
- BotがチャンネルにInviteされているか確認: `/invite @ボット名`
- 起動時のログにエラーコードと具体的な対処方法が出力されます

## 参考資料
- [SunFounder DHT11センサー解説](https://docs.sunfounder.com/projects/umsk/ja/latest/05_raspberry_pi/pi_lesson19_dht11.html)
- [Adafruit_DHTインストール記事 (Zenn)](https://zenn.dev/hasegawasatoshi/articles/f4708b23077cf7)

## ライセンス
このプロジェクトはMITライセンスの下で公開されています。

## 作者
Shinichi Miyazaki

> **注意**: DHT22センサーは測定の精度や信頼性にばらつきがある場合があります。重要な用途には、より高精度なセンサーの使用を検討してください。
