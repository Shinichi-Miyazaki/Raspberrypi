# Raspberry Pi + DHT22で作る温湿度監視システム【Slack通知付き】

## はじめに

「研究室やサーバールームの温湿度を24時間管理したいけど、人が常駐するのは難しい…」

そんな悩みを、Raspberry Pi（小型コンピューター）とDHT22（温湿度センサー）を組み合わせて解決しました。このシステムは、温湿度を10分おきに自動測定し、異常があればSlack（チャットツール）にアラートを送ってくれます。

この記事では、配線からプログラムの起動まで、できるだけわかりやすく解説します。

---

## このシステムでできること

- **定期測定**: 10分ごとに温度・湿度を自動測定してCSVに記録
- **アラート通知**: 設定した上限・下限を超えたらSlackに即座に通知（同じアラートは12時間は再送しない）
- **グラフレポート**: 30分後・1日ごとに温湿度の推移グラフをSlackに自動送信
- **WiFi自動復旧**: ネットワークが切れても自動で再接続を試みる
- **テストモード**: センサーなしでも動作確認できる（開発・デバッグ用）

Slackへの通知イメージ：

```
警告: 温度上昇 25.3°C (上限: 23°C) 以後12時間は警告を出しません。
```

---

## 必要なもの

### ハードウェア

| 品目 | 説明 |
|------|------|
| Raspberry Pi | 3B+または4を推奨 |
| DHT22温湿度センサー（モジュール品） | モジュール品はプルアップ抵抗が内蔵されているため配線が簡単 |
| ジャンパーワイヤー（オス-メス） | 3本 |
| microSDカード | Raspberry Pi OS書き込み済み |

> **モジュール品とは？**
> センサー単体ではなく、基板に抵抗やコネクタが付いた状態で販売されているもの。「DHT22 モジュール」で検索すると見つかります。初心者にはこちらがおすすめです。

### ソフトウェア（無料）

- Raspberry Pi OS（Raspberry Pi の公式OS）
- Python 3
- Slackアカウント（無料プランで使用可能）

---

## 配線方法

DHT22センサーをRaspberry Piに次のように接続します。

```
DHT22センサー           Raspberry Pi
─────────────           ─────────────
VCC（+）     ──────────  5V（2番ピンまたは4番ピン）
DATA（out）  ──────────  GPIO 4（7番ピン）
GND（-）     ──────────  GND（6番、9番、14番など）
```

Raspberry Piのピン配置は「Raspberry Pi GPIO ピン配置」で画像検索すると確認しやすいです。

> **注意**: DATAピンをGPIO 4（BCM番号4、物理番号7番ピン）に接続することを前提としています。別のピンを使う場合はプログラムの設定変更が必要です。

---

## セットアップ手順

### 1. Raspberry Pi OSのセットアップ

まだOSをインストールしていない場合は、[Raspberry Pi Imager](https://www.raspberrypi.com/software/) を使ってmicroSDカードに書き込みます。書き込み後にRaspberry Piに挿してSSHまたはモニターで接続してください。

### 2. システムパッケージのインストール

ターミナル（コマンド入力画面）を開いて、以下のコマンドを順番に実行します。

```bash
sudo apt-get update
sudo apt-get install -y python3-pip python3-dev
sudo apt-get install -y build-essential libssl-dev libffi-dev
sudo apt-get install -y python3-matplotlib
```

> **`sudo` とは？**
> 管理者権限でコマンドを実行するための接頭語です。パスワードを聞かれたらRaspberry Piのログインパスワードを入力してください。

### 3. Pythonライブラリのインストール

```bash
pip install adafruit-circuitpython-dht
pip install adafruit-blinka
pip install slack_sdk
pip install pandas matplotlib
pip install RPi.GPIO
```

> **注意**: `board` モジュールは `adafruit-blinka` の中に含まれています。`pip install board` とは打たないでください（別物がインストールされます）。

> **2025年以降のRaspberry Pi OSについて**
> バージョンによっては `pip install` を実行したときに以下のようなエラーが出る場合があります：
>
> ```
> error: externally-managed-environment
> ```
>
> これはシステムのPython環境を保護するための制限です。解決策は2つあります。
>
> **推奨: 仮想環境（venv）を使う**
> システムへの影響がなく、最も安全な方法です。
> ```bash
> python3 -m venv ~/sensor-env
> source ~/sensor-env/bin/activate
> pip install adafruit-circuitpython-dht adafruit-blinka slack_sdk pandas matplotlib RPi.GPIO
> # 以後、スクリプト起動前に毎回 source ~/sensor-env/bin/activate が必要
> ```
>
> **代替: `--break-system-packages` オプションを使う**
> 手軽ですが、システム全体のPython環境にパッケージをインストールするため、OSの他の機能に影響する可能性があります。Raspberry Piを実験用途にのみ使っている場合に限って選んでください。
> ```bash
> pip install adafruit-circuitpython-dht --break-system-packages
> # 残りのパッケージも同様に --break-system-packages を付けて実行
> ```

### 4. プログラムのダウンロード

```bash
git clone https://github.com/あなたのアカウント/Raspberrypi.git
cd Raspberrypi/temperature_humidity_notifier
```

---

## Slack Botのセットアップ

温湿度アラートを受け取るSlack Botを作成します。初めての方でも5〜10分でできます。

### 1. Slackアプリを作成する

1. [Slack API](https://api.slack.com/apps) にアクセスしてログイン
2. 「Create New App」をクリック
3. 「From scratch」を選択
4. アプリ名（例: `sensor-bot`）とワークスペースを選んで「Create App」

### 2. 権限（スコープ）を設定する

左メニューの「OAuth & Permissions」を開き、「Scopes」セクションにある「Add an OAuth Scope」で以下の2つを追加します：

- `chat:write`（メッセージ送信の権限）
- `files:write`（グラフ画像などのファイル送信の権限）

### 3. ワークスペースにインストールしてトークンを取得する

「Install to Workspace」ボタンを押して許可します。インストール後に表示される「Bot User OAuth Token」（`xoxb-` で始まる長い文字列）をコピーしておきます。これが後で使う `SLACK_TOKEN` です。

### 4. 通知用チャンネルを作成してBotを招待する

1. Slackで通知を受け取るチャンネルを作成します（例: `#sensor-notify`）
2. そのチャンネルを開き、メッセージ入力欄に以下を入力して送信：
   ```
   /invite @sensor-bot
   ```
   （`sensor-bot` は手順1で付けたアプリ名）

---

## プログラムの設定と起動

### 環境変数の設定

Slackのトークンやチャンネル名はコードに直接書かず、**`.env` ファイル**で管理します。`.env` ファイルはGitの管理対象外にするため、誤ってGitHubに公開してしまうリスクがありません。

### `.env` ファイルを作成する

スクリプトと同じディレクトリに `.env` というファイルを作成して、以下の内容を書き込みます：

```
SLACK_TOKEN=xoxb-xxxx-xxxx-xxxx
SLACK_CHANNEL=#sensor-notify
```

> `"` （ダブルクォート）は不要です。そのまま値だけ書いてください。

### `python-dotenv` をインストールする

`.env` ファイルを自動で読み込むために `python-dotenv` ライブラリをインストールします：

```bash
pip install python-dotenv
```

これでスクリプト起動時に `.env` の内容が自動で読み込まれます。`export` コマンドを毎回打つ必要はありません。

> **`python-dotenv` が入っていなくても動く設計にしています**
> インストールし忘れた場合でも、従来通り `export SLACK_TOKEN="..."` で環境変数を渡せばスクリプトは動作します。

### `.env` ファイルを Git に上げないようにする

`.gitignore` にすでに `.env` を追加済みです。念のため確認しておきましょう：

```bash
cat .gitignore   # .env の行があればOK
git status       # .env が「追跡対象外」と表示されればOK
```

> **トークンの取り扱いには注意してください**
> Slack Bot Tokenは、ワークスペースへの書き込み権限を持つ「鍵」です。以下の点に気をつけましょう：
>
> - **コードに直書きしない**: `SLACK_TOKEN = "xoxb-..."` とソースコードに書くと、GitHubに公開したときに漏れます
> - **`.env` を絶対にコミットしない**: `git add .` で誤って含めてしまわないよう `.gitignore` の設定を必ず確認してください
> - **万が一漏れたら即再発行**: [Slack API](https://api.slack.com/apps) の「OAuth & Permissions」で「Reinstall App」するとトークンが無効化・再発行されます

### 起動する

```bash
# 通常起動（実際のセンサーを使用）
python3 temp_humid_notifier.py

# テストモード（センサーなしで動作確認）
python3 temp_humid_notifier.py --test-mode

# ログファイルの保存先を指定する場合
python3 temp_humid_notifier.py --save-dir /home/pi/sensor_logs
```

起動すると次のようなログが流れ始めます：

```
2026-02-25 12:00:00 - INFO - DHT22センサーを初期化しました
2026-02-25 12:00:01 - INFO - Slack認証成功: sensor-bot
2026-02-25 12:00:02 - INFO - センサー監視を開始します
2026-02-25 12:10:00 - INFO - [2026-02-25 12:10:00] 温度: 21.3°C, 湿度: 55.2%
```

---

## システムの仕組み（概要）

プログラムが起動すると、以下の処理が繰り返されます：

```
┌───────────────────────────────────┐
│ 10分ごとに温湿度を測定            │
│         ↓                         │
│ CSVファイルに記録                  │
│         ↓                         │
│ 閾値を超えていたら？               │
│   YES → Slackにアラートを送信      │
│   NO  → 何もしない                │
│         ↓                         │
│ 30分後：短期レポートをSlackへ      │
│ 1日後 ：日次レポートをSlackへ      │
└───────────────────────────────────┘
```

### 閾値の設定

`temp_humid_notifier.py` の冒頭でアラートの閾値を変更できます：

```python
TEMP_MAX = 23      # 温度の上限 (°C)
TEMP_MIN = 17      # 温度の下限 (°C)
HUMIDITY_MAX = 70  # 湿度の上限 (%)
HUMIDITY_MIN = 40  # 湿度の下限 (%)
```

たとえば夏場に合わせて `TEMP_MAX = 28` に変更するといった調整が可能です。

### グラフレポートの見方

30分後・1日ごとに、温湿度の推移グラフがSlackに届きます。グラフには以下の線が含まれています：

| 線の色・種類 | 意味 |
|---|---|
| 赤の実線 | 温度の推移 |
| 青の実線 | 湿度の推移 |
| オレンジの破線 | 上限閾値 |
| 青の破線 | 下限閾値 |

閾値ラインがあることで「いつ、どのくらい外れたか」が一目でわかります。

---

## WiFi自動再接続のセットアップ（オプション）

Raspberry Piはときどきネットワークが切れることがあります。`reconnect_wifi.py` をバックグラウンドで常時動かしておくと、切断を自動で検知して再接続してくれます。

### systemdサービスとして登録する

systemd（サービス管理の仕組み）に登録すると、Raspberry Piの起動時に自動でスクリプトが立ち上がります。

```bash
# サービスファイルを作成
sudo nano /etc/systemd/system/wifi-monitor.service
```

以下の内容を貼り付けてください（`/path/to/` は実際のファイルパスに変更）：

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

`Ctrl+O` で保存 → `Ctrl+X` で終了。

```bash
# サービスを有効化して起動
sudo systemctl enable wifi-monitor.service
sudo systemctl start wifi-monitor.service

# 動作確認
sudo systemctl status wifi-monitor.service
```

---

## トラブルシューティング

### センサーが読み取れない

```
センサーからのデータ取得に失敗しました。再試行します...
```

このエラーが出る場合：

1. **配線を確認**: DATAピンがGPIO 4（7番ピン）に正しく接続されているか
2. **権限の問題**: `sudo python3 temp_humid_notifier.py` で実行してみる
3. **GPIOのリセット**: 以下のコマンドでGPIOを初期化する
   ```bash
   python3 gpio_reset.py
   ```

DHT22は一定の確率で読み取りに失敗しますが、プログラムが自動でリトライするため、たまに出る程度なら問題ありません。

### Slackに通知が届かない

| エラーメッセージ | 原因と対処 |
|---|---|
| `SLACK_TOKEN が設定されていません` | `export SLACK_TOKEN=...` が実行されているか確認 |
| `invalid_auth` | トークンが間違っている。Slack APIで再発行 |
| `channel_not_found` | チャンネル名が違う。`#` を含めて正確に設定 |
| `not_in_channel` | BotがチャンネルにInviteされていない。`/invite @ボット名` で招待 |
| `missing_scope` | トークンの権限不足。`chat:write` と `files:write` を追加してトークンを再発行 |

### 再起動後に環境変数が消える

`export` で設定した環境変数は、ターミナルを閉じると消えてしまいます。永続化するには `~/.bashrc` に追記します：

```bash
echo 'export SLACK_TOKEN="xoxb-xxxx-xxxx"' >> ~/.bashrc
echo 'export SLACK_CHANNEL="#sensor-notify"' >> ~/.bashrc
source ~/.bashrc
```

---

## まとめ

今回構築したシステムのポイントをまとめます：

- **Raspberry Pi + DHT22** で温湿度を10分おきに自動測定・記録
- **Slack Bot** 経由でアラートとグラフレポートを自動送信
- **WiFi自動復旧** でネットワーク障害にも対応
- **テストモード** でセンサーなしでも動作確認可能

一度セットアップしてしまえば、あとはほぼ自動で動き続けます。研究室の環境管理や、留守中の自宅の温湿度チェックなどにもそのまま応用できます。

---

## 参考資料

- [Raspberry Pi 公式サイト](https://www.raspberrypi.com/)
- [Adafruit CircuitPython DHT ライブラリ](https://github.com/adafruit/Adafruit_CircuitPython_DHT)
- [Slack API ドキュメント](https://api.slack.com/)
- [SunFounder DHT11センサー解説（日本語）](https://docs.sunfounder.com/projects/umsk/ja/latest/05_raspberry_pi/pi_lesson19_dht11.html)
