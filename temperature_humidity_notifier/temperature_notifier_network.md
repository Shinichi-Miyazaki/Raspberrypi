---
title: ""
geometry: "top=20mm, bottom=20mm, left=20mm, right=20mm"
fontsize: 10pt
linestretch: 1.0
mainfont: "Yu Gothic Medium"
documentclass: article
header-includes:
  - \usepackage{etoolbox}
  - \usepackage{booktabs}
  - \usepackage{longtable}
  - \setlength{\LTleft}{0pt}
  - \setlength{\LTright}{\fill}
  - \renewcommand{\rule}[2]{\noindent\makebox[\linewidth]{\hrulefill}}
  - '\XeTeXlinebreaklocale "ja"'
  - \XeTeXlinebreakskip = 0pt plus 1pt
---
## 5. Raspberry Pi Zero（ヘッドレス準備）

### 5.1 重要な前提

* **画面・キーボードは使いません**
* microSD の設定がすべてです

---

## 6. microSDカード作成（Windows）

### 6.1 Raspberry Pi Imager をインストール

* 公式サイトからダウンロード
* インストールして起動

---

### 6.2 書き込み設定

#### OS選択

* `Raspberry Pi OS Lite (32-bit)`

#### ストレージ

* microSDカード

---

### 6.3 ⚙️（歯車マーク）の設定【最重要】

以下を **必ず設定** してください

* Hostname：

  ```
  pi-zero-01
  ```

* SSH：

  * ✅ 有効にする
  * パスワード認証

* ユーザー名：

  ```
  th-meter
  ```
  * （Temperature Humidity Meter の略）

* パスワード：

  ```
  （指定されたものを入力）
  ```

* Wi-Fi 設定：

  * SSID：**GL.iNet の Wi-Fi名**（`GL-SFT1200-xxx` など）
  * Password：GL.iNet のパスワード（本体裏面）
  * Country：JP

---

### 6.4 書き込み

* 「書き込む」をクリック
* 完了まで待つ

---

## 7. Raspberry Pi 起動

1. microSD を Raspberry Pi Zero に挿す
2. 電源を接続
3. **3分待つ（触らない）**

---

## 8. SSH 接続（Tera Term）

### 8.1 Tera Term 起動

* Windows で Tera Term を起動

---

### 8.2 接続設定

* ホスト：

  ```
  pi-zero-01.local
  ```

* 接続方式：SSH

* ユーザー名：`th-meter`

* パスワード：設定したもの

---

### 8.3 成功例

以下の表示が出たら成功

```
th-meter@pi-zero-01:~ $
```

---

## 9. 温湿度計の作成

### 9.1 配線（ハードウェア）

⚠ **注意**: 配線作業は必ず **Raspberry Pi の電源を抜いた状態** で行ってください。

DHT22センサーとRaspberry Pi Zeroをジャンパーワイヤーで接続します。

| センサー側 | Raspberry Pi Zero 側 | ピン番号（物理） |
| :--- | :--- | :--- |
| **VCC (+)** | 5V Power | Pin 2 または 4 |
| **DATA (Out)** | GPIO 4 | Pin 7 |
| **GND (-)** | Ground | Pin 6, 9, 14 等 |

* **確認**: 配線が正しいか、もう一度確認してから電源を入れてください。

---

### 9.2 必要なソフトウェアのインストール

Tera Term で Raspberry Pi に接続し、以下のコマンドを **1行ずつコピー＆ペースト** して実行してください。

```bash
# システムの更新
sudo apt-get update

# 必要なシステムパッケージのインストール
sudo apt-get install -y python3-pip python3-dev build-essential libssl-dev libffi-dev python3-matplotlib

# Pythonライブラリのインストール
# ※ 最近のOS仕様に対応するため --break-system-packages を使用します
sudo pip3 install adafruit-circuitpython-dht slack_sdk pandas matplotlib board RPi.GPIO --break-system-packages
```

---

### 9.3 プログラムの配置

1. 管理者から配布された以下の2つのファイルを、Raspberry Pi のホームディレクトリ（`/home/th-meter/`）に配置してください。
   * `temp_humid_notifier.py` （メインプログラム）
   * `reconnect_wifi.py` （Wi-Fi再接続用）

   ※ Tera Term の「ファイル」→「SSH SCP...」機能を使ってファイルを転送できます。

---

### 9.4 Slack設定（Bot作成）

※ すでにトークンが発行されている場合は、この節を飛ばして **9.5** へ進んでください。

1. **Slack App の作成**
   * [Slack API](https://api.slack.com/apps) にアクセスし、「Create New App」→「From scratch」を選択。
   * App Name: `SensorBot`（任意）、Workspaceを選択。

2. **権限の設定**
   * 左メニュー「OAuth & Permissions」へ移動。
   * 「Scopes」→「Bot Token Scopes」に以下を追加：
     * `chat:write`
     * `files:write`

3. **インストールとトークン取得**
   * 「Install to Workspace」をクリック。
   * **Bot User OAuth Token** (`xoxb-` で始まる文字列) をコピーして控える。

4. **チャンネル設定**
   * Slackで通知用チャンネル（例: `#sensor-notify`）を作成。
   * そのチャンネルで `/invite @SensorBot` （設定したアプリ名）を実行してBotを招待する。

---

### 9.5 プログラムの設定

`temp_humid_notifier.py` を編集して、設定を書き込みます。

```bash
nano temp_humid_notifier.py
```

以下の部分を探して、書き換えてください。

```python
# 必須設定
SLACK_TOKEN = 'xoxb-your-token-here'  # 取得したトークンに書き換え
SLACK_CHANNEL = '#sensor-notify'      # 作成したチャンネル名
SAVE_DIR = "/home/th-meter/sensor_logs" # ログ保存先（ユーザー名に合わせて変更）

# センサー設定（DHT22を使用）
SENSOR = Adafruit_DHT.DHT22
PIN = 4
```

* 編集完了後、`Ctrl + O` → `Enter` で保存し、`Ctrl + X` で終了します。

---

### 9.6 動作テスト

センサーが正しく動くかテストします。

```bash
python3 temp_humid_notifier.py
```

* エラーが出ずに実行され（または待機状態になり）、Slackに通知が来れば成功です。
* `Ctrl + C` で停止します。

---

### 9.7 Wi-Fi再接続対策（自動化）

Wi-Fiが切れた際に自動で再接続する設定を行います。

1. **スクリプトを実行可能にする**

   ```bash
   chmod +x reconnect_wifi.py
   ```

2. **自動起動サービスを作成**

   ```bash
   sudo nano /etc/systemd/system/wifi-monitor.service
   ```

   以下の内容を貼り付けます（ユーザー名が `th-meter` であることに注意）。

   ```ini
   [Unit]
   Description=WiFi Connection Monitor
   After=network.target

   [Service]
   ExecStart=/usr/bin/python3 /home/th-meter/reconnect_wifi.py
   Restart=always
   User=th-meter

   [Install]
   WantedBy=multi-user.target
   ```

   * `Ctrl + O` → `Enter` で保存、`Ctrl + X` で終了。

3. **サービスの有効化と起動**

   ```bash
   sudo systemctl enable wifi-monitor.service
   sudo systemctl start wifi-monitor.service
   ```

---

## 10. トラブル時のルール

* 勝手に設定を変えない
* 再起動を繰り返さない
* slackで宮崎に連絡

---

## 11. チェックリスト（完了確認）

以下の項目がすべて完了していることを確認してください。

* [ ] 第一会議室で Wi-Fi（GL.iNet経由）が使える
* [ ] GL.iNet がアクセスポイントモードになっている（ルーターモードではない）
* [ ] Raspberry Pi に Tera Term で SSH 接続できる
* [ ] 温湿度センサーの配線が完了している
* [ ] 温湿度計プログラムが正常に動作し、Slackに通知が届く
* [ ] Wi-Fi自動再接続サービスが有効化されている

---

## 12. よくある失敗と対策（Pitfalls）

### 🛑 失敗1：GL.iNetの設定画面（192.168.8.1）に入れなくなった
* **原因**: アクセスポイントモードに切り替えると、管理画面のIPアドレス（192.168.8.1）が無効になるため
* **これは正常です**: 設定変更後にアクセスできなくなるのは仕様です
* **対策**: 設定を変更したい場合は、本体のリセットボタンを10秒以上長押しして工場出荷状態に戻してください

### 🛑 失敗2：Raspberry Pi に SSH 接続できない（`pi-zero-01.local` につながらない）
* **原因**: Wi-FiのSSIDまたはパスワードの入力ミス（大文字・小文字、全角・半角の違いなど）
* **対策**: microSDカードをPCに挿し直し、Raspberry Pi Imager で最初から書き込み直してください（設定ファイルの個別修正はできません）

### 🛑 失敗3：GL.iNetのSSIDが居室のWi-Fiと違う
* **これは仕様です**: GL.iNetは独自のSSID（`GL-SFT1200-xxx`）を出します。アクセスポイントモードにしても自動的に居室と同じ名前にはなりません
* **対策**: そのまま使用して問題ありません。どうしても居室と同じSSIDにしたい場合は、アクセスポイントモードに変更する**前**に、管理画面のWi-Fi設定でSSIDとパスワードを居室と同じものに変更してください

### 🛑 失敗4：温湿度センサーの値が読み取れない、またはエラーが表示される
* **原因**: 配線ミス（GPIOピン番号の間違い）、または接触不良
* **対策**: 
  1. Raspberry Pi の電源を切る
  2. 配線を確認する（特に `GPIO 4` = Pin 7、`5V` = Pin 2 or 4、`GND` = Pin 6 etc.）
  3. ジャンパーワイヤーがしっかり挿さっているか確認
  4. 電源を入れ直す

### 🛑 失敗5：Slackに通知が届かない
* **原因①**: Botアプリをチャンネルに招待していない
  * **対策**: 通知先チャンネルで `/invite @SensorBot` を実行してください
* **原因②**: トークンの権限が不足している
  * **対策**: Slack APIの管理画面で、Bot Token Scopesに `chat:write` と `files:write` が追加されているか確認してください

---

## 13. 困ったときの検索・AI活用

自分で解決しようとして詰まった場合、以下のキーワードやプロンプトを参考にしてください。

### 🔍 検索キーワード
* `GL-SFT1200 アクセスポイントモード 設定`
* `Raspberry Pi Zero Headless Setup`
* `Tera Term SSH 接続できない`

### 🤖 ChatGPTへの質問プロンプト例

**状況：SSH接続ができないとき**
> Raspberry Pi Zero W をヘッドレスでセットアップしました。OSはRaspberry Pi OS Liteです。
> PCと同じWi-Fi（GL.iNet経由）に接続しているはずですが、Tera Termで `pi-zero-01.local` に接続しようとするとタイムアウトします。
> 確認すべきポイントを初心者向けに教えてください。

**状況：GL.iNetの設定が不安なとき**
> GL.iNet GL-SFT1200 (Opal) を使用しています。
> 既存のルーターから有線LANを引いて、Wi-Fiを拡張したいです（二重ルーターにしたくない）。
> 「アクセスポイントモード」と「Extenderモード」の違いと、どちらを選ぶべきか教えてください。

---

## 補足

このマニュアルは
**「ネットワークが分からなくても、事故らない」**ことを最優先しています。

不明点が出た時点で、必ず相談してください。
