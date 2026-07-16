# 温湿度モニタリングシステム（複数デバイス・NAS集約版）

## 概要
複数台のRaspberry Pi + DHT22温湿度センサーで各部屋の環境を監視するシステムです。
データはSynology NAS上のSQLiteデータベースに一元化され、Slackへの通知は
「毎日の前日サマリ」「週1回の統合グラフ」「範囲逸脱アラート」「欠測アラート」に絞られています。

**セットアップ・日常運用の手順は [OPERATIONS.md](OPERATIONS.md) を参照してください。**
本ファイルは仕組みの説明と開発者向け情報をまとめたものです。

## システム構成

データの流れ:

1. **センサーPi（4台）**: 10分ごとに測定し、ローカルCSVに追記（送信バッファ兼予備）。
   未送信分をNASの `incoming/<デバイス名>/` へ送信する。Slackトークンを持たない。
   読み取り失敗時は同じサイクル内で15秒間隔・最大5回まで自動再試行する
   （DHT22は一時的な失敗が多く、10分後の次サイクルまで待つと欠測になるため）。
   動作確認用に `--once`（1回だけ測定・送信して終了）フラグがある
2. **NAS（Synology）**: `sensor_data` 共有フォルダにデータを一元保管。
   各PiからはSMBマウント（`/mnt/sensor_data`）で見える
3. **コレクターPi（4台のうち1台が兼任）**: 10分ごとに incoming を SQLite に取り込み、
   範囲逸脱アラート・欠測アラートを判定してSlack通知。
   日次で集計＋前日サマリのSlack投稿、
   週次でグラフ生成→Slack投稿を行う。
   手動確認用の `status` サブコマンド（各デバイスの最終受信時刻・件数を表示、
   Slack設定不要）がある

NAS上の `sensor_data/` の構成:

| パス | 内容 |
|---|---|
| `incoming/<デバイス名>/` | 各Piからのデータ受け口（取り込み後に削除） |
| `db/sensor_data.sqlite3` | 全デバイス共通のデータベース |
| `config/thresholds.yaml` | 許容範囲・アラート設定 |
| `reports/weekly/YYYY-MM/` | 週次グラフのアーカイブ |
| `logs/collector.log` | コレクターの動作ログ |

### 通知の種類
| 通知 | タイミング | 内容 |
|---|---|---|
| 日次レポート | 毎日（早朝） | 前日の各デバイスの温度・湿度のmin/max/avgをまとめたテキスト。前日データが無いデバイスは「データなし（要確認）」と明記して欠測に気づけるようにする |
| 週次レポート | 週1回（月曜朝） | 全デバイスの温度・湿度を1枚の画像に並べたグラフ（スモールマルチプル。設置場所ごとに平常レンジが異なるため、重ね書きせずデバイスごとに独立したY軸で表示） |
| 範囲逸脱アラート | 検知時（10分粒度） | 温度または湿度が「許容範囲」の同じ側に**2回連続**で外れたとき。インキュベータの開けっ放しなど継続的な逸脱を捉える。2連続を条件にすることで単発ノイズや短時間のドア開閉では鳴らない。許容範囲（temp_range / humid_range）は部屋ごとに手動設定、未設定の項目は判定しない |
| 欠測アラート | 検知時（1日1回まで） | あるデバイスのデータが2時間以上届かないとき（Pi停止・センサー故障・NAS未達をまとめて検出） |

### アラートの調整（許容範囲の設定）
`config/thresholds.yaml` の `temp_range` / `humid_range` を編集します（詳細はファイル内コメント参照）。
`[下限, 上限]` の形式で部屋ごとに設定し、この範囲を同じ側に2回連続で外れると発報します。
誤報が多ければ範囲を広げ、見逃しがあれば狭めます。範囲を設定しない項目は判定されません
（統計の助走期間のような待ち時間は無く、設定した直後から有効になります）。

### セキュリティ設計
- 全Piは **sensor_data フォルダ限定の専用アカウント** でNASにSMBマウントする
  （センサーPiは `sensor-uploader`、コレクターPiは `sensor-collector`）。
  Piが乗っ取られても、届く範囲は sensor_data フォルダだけに限定される
- センサーPiはSlackトークンを持たない（通知はすべてコレクター経由）
- ※要件上はSSH鍵によるSFTP転送が候補だったが、Synology側の鍵設定の難易度が高く、
  コレクターのSQLiteアクセスにはマウントが必須なこともあり、全Piを
  「専用アカウント（他フォルダはアクセス禁止）＋NASファイアウォールでIP制限＋SMB3＋
  スナップショット」のマウント方式に統一した。
  なおセンサークライアントは `--nas-target user@host:/path` 形式を渡せばSFTP送信にも対応している
- **NASスナップショット**: Pi侵害時でも既存データが消せないようにする保険（設定はOPERATIONS.md）
- データは全期間保持（削除・ローテーションなし）。10分間隔×4台で10年でも200万行強で、SQLiteで十分扱える

## ファイル構成

| ファイル | 動く場所 | 役割 |
|---|---|---|
| `temp_humid_notifier.py` | センサーPi（全台） | 測定→ローカルCSV→NAS（マウント先）へ送信 |
| `collector/collector.py` | コレクターPi（1台） | 取り込み・アラート判定・日次集計・週次レポート |
| `collector/thresholds.example.yaml` | →NASにコピー | 許容範囲・アラート設定の雛形 |
| `gpio_reset.py` | センサーPi | GPIOが解放されないときの復旧用 |
| `OPERATIONS.md` | - | セットアップ・運用手順書（初心者向け） |

旧バージョン（単一デバイス・Slack直接通知版）は `../Legacy/temp_humid_notifier.py` にあります。

## 必要な機材（1デバイスあたり）
- Raspberry Pi（3B+または4を推奨）
- DHT22またはDHT11温湿度センサー
- ジャンパーワイヤー（オス-メス）3本
- 4.7kΩまたは10kΩ抵抗（DHT22の場合は必須。ただしモジュール品は内蔵していることが多い）

## 配線方法
DHT22/DHT11センサーとRaspberry Piを以下のように接続します：

- VCC（+）：Raspberry PiのGPIO 5V（Pin 2またはPin 4）に接続
- DATA（out）：Raspberry PiのGPIO 4（Pin 7 - BCM番号）に接続
- GND（-）：Raspberry PiのGND（Pin 6、9、14、20、25、30、34、39のいずれか）に接続

※ モジュール品のDHT22は内部プルアップ抵抗を持つため外部抵抗は不要なことが多い。

## 開発者向け情報

### 依存ライブラリ
- センサーPi: `adafruit-circuitpython-dht`（Slack・グラフ関連は不要になった）
- コレクターPi: `pyyaml` `matplotlib` `slack_sdk`

### 手元での動作確認（実機・NAS不要）
コレクターはハードウェア非依存なので、開発機で一気通貫の確認ができます。

```bash
# センサークライアント: テストモード＋ローカルフォルダ送信
python3 temp_humid_notifier.py --test-mode --device-name test246 \
    --save-dir /tmp/client_data --nas-target /tmp/fake_nas/incoming

# コレクター: --no-slack でSlackに送らずログ出力のみ
python3 collector/collector.py ingest        --base-dir /tmp/fake_nas --no-slack
python3 collector/collector.py daily         --base-dir /tmp/fake_nas --no-slack
python3 collector/collector.py weekly-report --base-dir /tmp/fake_nas --no-slack
```

アラート発火を手軽に試すには `config/thresholds.yaml` の `temp_range` を一時的に
今の室温を外す狭い範囲（例: `[0, 1]`）にします（どんな測定値でも範囲外になる）。
2連続で外れれば発報するので、ingestを2回実行すると確認できます。確認後は必ず戻すこと。

### 設計上の注意
- **SQLiteに書き込むのはコレクターの単一プロセスだけにすること。**
  ネットワーク共有上のSQLiteは複数プロセスからの同時書き込みで破損することがある。
  センサーPiはCSVファイルを置くだけで、DBには触らない設計になっている
- グラフ内の文字は英語のみ（日本語フォントの無い環境での文字化け防止）
- DHT22センサーは `use_pulseio=False` を指定しない（adafruit_circuitpython_dhtと相性が悪い）
- GPIOの初期化・クリーンアップは必ず行う（漏れると「unable to set line to input」エラーになる）

## トラブルシューティング
運用中のトラブル対応は [OPERATIONS.md](OPERATIONS.md) の「フェーズ7: トラブル対応」を参照。

### GPIOの初期化エラー（開発時）
adafruit_circuitpython_dhtでは `use_pulseio=False` の設定が相性が悪い。
そのため指定していないが、異常終了するとGPIOが解放されず
「unable to set line XX to input」エラーが起こることがある。
`sudo python3 gpio_reset.py` で復旧できる。

### Wifiの接続が切れる問題
`reconnect_wifi.py`（Legacy側）をsystemdサービスとして常駐させることで対応済み。
設定方法はOPERATIONS.mdのセンサーPi設定を参照。

## 参考資料
- ハードウェア・配線: SunFounder DHT11センサー解説（https://docs.sunfounder.com/projects/umsk/ja/latest/05_raspberry_pi/pi_lesson19_dht11.html）
- インストール方法: ZennのAdafruit_DHTインストール記事（https://zenn.dev/hasegawasatoshi/articles/f4708b23077cf7）

## ライセンス
このプロジェクトはMITライセンスの下で公開されています。

## 作者
Shinichi Miyazaki
