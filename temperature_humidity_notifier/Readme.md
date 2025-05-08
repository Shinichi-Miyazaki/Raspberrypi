# 温湿度モニタリングシステム  

## 概要
このプログラムはRaspberry PiとDHT22/DHT11温湿度センサーを使用して環境の温度と湿度を定期的に監視し、Slackに通知するシステムです。  
測定データはCSVファイルに記録され、定期的にグラフ化されたレポートがSlackに送信されます。  
温度や湿度が設定された閾値を超えると、自動的にアラート通知を送信します。

## 機能
- 温度と湿度の定期的な測定と記録  
- 設定された閾値を超えた場合のSlackアラート通知   
- 短期間（30分）と長期間（1日）のグラフレポート自動生成   
- テストモード対応（実際のセンサーがなくてもテスト可能）   
- エラーハンドリング機能

## 必要な機材
- Raspberry Pi（3B+または4を推奨）   
- DHT22またはDHT11温湿度センサー   
- ジャンパーワイヤー（オス-メス） 3本   
- 4.7kΩまたは10kΩ抵抗（DHT22の場合は必須）  
- ブレッドボード

## 配線方法
DHT22/DHT11センサーとRaspberry Piを以下のように接続します：

- VCC（+）：Raspberry PiのGPIO 5V（Pin 2またはPin 4）に接続   
- DATA（out）：Raspberry PiのGPIO 4（Pin 7 - BCM番号）に接続  
- 4.7kΩまたは10kΩの抵抗でプルアップ（VCCとDATAの間に接続）   
- GND（-）：Raspberry PiのGND（Pin 6、9、14、20、25、30、34、39のいずれか）に接続   
※ DHT11の場合はセンサーによっては内部プルアップ抵抗を持っているものもあるため、外部抵抗が不要な場合があります。

## セットアップ手順
1. Raspberry Pi OSのセットアップ
Raspberry Pi OSが既にインストールされていることを前提としています。  
まだの場合はRaspberry Pi Imagerを使用してセットアップしてください。

2. 必要なパッケージのインストール
以下のコマンドを実行して必要なパッケージをインストールします：

```
sudo apt-get update
sudo apt-get install -y python3-pip python3-dev
sudo apt-get install -y build-essential libssl-dev libffi-dev
sudo apt-get install -y python3-matplotlib  
```

3. 必要なPythonライブラリのインストール   
 
```
pip install adafruit-circuitpython-dht
pip install slack_sdk
pip install pandas matplotlib
```


## Slack設定
1. Slackアプリの作成
Slack APIにアクセスし、「Create New App」をクリック
「From scratch」を選択
アプリ名を入力し、使用するワークスペースを選択
2. 権限の設定
「OAuth & Permissions」セクションに移動
「Scopes」セクションで以下の権限を追加:
chat:write（メッセージの送信用）
files:write（ファイルのアップロード用）
3. アプリのインストールとトークン取得
「Install to Workspace」ボタンをクリックしてアプリをワークスペースにインストール
「Bot User OAuth Token」をコピー（xoxb- で始まるトークン）
4. チャンネルの作成と招待
Slackで通知用の新しいチャンネルを作成（例：#sensor-notify）
そのチャンネルにBotを招待する:
チャンネルで /invite @あなたのボット名 を実行
プログラムの設定
temp_humid_notifier.pyファイルを開き、以下のパラメータを編集します：

### 必須設定
SLACK_TOKEN = 'xoxb-your-token'  # SlackのBot User OAuth Token
SLACK_CHANNEL = '#sensor-notify'  # Slackの通知送信先チャンネル（またはチャンネルID）
SAVE_DIR = "/home/si/sensor_logs"  # ログファイルの保存先ディレクトリ

### センサーとピン設定
SENSOR = Adafruit_DHT.DHT22    # DHT11の場合は Adafruit_DHT.DHT11 に変更
PIN = 4                        # センサーを接続しているGPIOピン番号（BCM番号）

### しきい値設定
TEMP_MAX = 23                  # 温度の上限しきい値(°C)
TEMP_MIN = 17                  # 温度の下限しきい値(°C)
HUMIDITY_MAX = 70              # 湿度の上限しきい値(%)
HUMIDITY_MIN = 40              # 湿度の下限しきい値(%)

### 通知設定
CHECK_INTERVAL = 30            # センサー測定間隔 (秒)
SHORT_REPORT_INTERVAL = 30     # 短報告の間隔 (分)
LONG_REPORT_INTERVAL = 1       # 長報告の間隔 (日)

## 使用方法
### 通常モード（センサー使用）
センサーを接続した状態で以下のコマンドを実行します：
```
python3 temp_humid_notifier.py
```
もしくはTonyから実行

必要に応じて、保存先ディレクトリを指定することもできます：

### テストモード（センサーなし）
センサーがなくても動作をテストできます。コード内で以下のパラメータを設定します：

# テストモード設定
TEST_MODE = True               # テストモードを有効にする
TEST_DATA_VARIATION = True     # テストデータをランダムに変化させる
TEST_TEMP_BASE = 20.0          # テストモード時の基本温度
TEST_HUMID_BASE = 50.0         # テストモード時の基本湿度
TEST_GENERATE_ALERTS = True    # テスト用のアラートを生成する


## トラブルシューティング
### センサー読み取りエラー
センサーの配線を確認してください。特にDATAピンとプルアップ抵抗の接続  
別のGPIOピンを試す場合は、PINの値を変更してください  
sudoコマンドを使ってプログラムを実行すると、GPIO権限の問題を解決できる場合があります  

### Slack接続エラー
SLACK_TOKENが正しいことを確認  
トークンに必要な権限（chat:writeとfiles:write）があるか確認  
Botがチャンネルに招待されているか確認  

### ファイル送信エラー: channel_not_found
チャンネルIDを直接使用する（Slackの応答から取得したID）
ファイルパスが正しいことを確認し、ファイルが存在するかチェック
channelsパラメータはリスト形式で渡す（例: [channel_id]）

## 参考資料
ハードウェア・配線: SunFounder DHT11センサー解説（https://docs.sunfounder.com/projects/umsk/ja/latest/05_raspberry_pi/pi_lesson19_dht11.html）
インストール方法: ZennのAdafruit_DHTインストール記事（https://zenn.dev/hasegawasatoshi/articles/f4708b23077cf7）

## ライセンス
このプロジェクトはMITライセンスの下で公開されています。

## 作者
Shinichi Miyazaki

※注意: DHT22/DHT11センサーは測定の精度や信頼性にばらつきがある場合があります。重要な用途には、より高精度なセンサーの使用を検討してください。