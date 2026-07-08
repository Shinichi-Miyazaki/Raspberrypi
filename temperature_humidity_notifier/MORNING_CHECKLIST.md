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

# 明日朝の作業チェックリスト（2026-07-09 用・一時メモ）

OPERATIONS.md の補足メモです。作業完了後は削除して構いません。
コマンドはそのままコピペできる形（`$` なし）で書いています。

---

## 作業1: リポジトリを /mnt/sensor_data に置いてしまったPiの特定と修正

【リポジトリの場所】はPi本体のローカル（例: `/home/pi/Raspberrypi`）が正しい。
NAS上（`/mnt/sensor_data/...`）だとNASマウントが外れた瞬間にプログラムが動かなくなるため修正する。

### 1-1. 確認（4台すべてのPiで実行）

```
grep -H ExecStart /etc/systemd/system/sensor-client.service /etc/systemd/system/collector-*.service 2>/dev/null
```

- `python3 /mnt/sensor_data/...` になっている行があるPi → **修正対象**
- `python3 /home/.../temp_humid_notifier.py` になっていれば → そのPiはOK
- 注意: `--nas-target /mnt/sensor_data/incoming` の部分は**正しい設定**なので触らない

念のためコードの実体がどこにあるかも確認:

```
ls ~/Raspberrypi/temperature_humidity_notifier/ 2>/dev/null && echo "ローカルにあり"
ls /mnt/sensor_data | grep -v -E "^(incoming|config|db|logs|reports|deploy)$"
```

2行目で何か表示されたら、それがNAS上に誤って置いたフォルダの候補
（`incoming` `config` `db` `logs` `reports` `deploy` の6つは正規のフォルダなので残す）。

### 1-2. 修正（対象のPiのみで実行）

**用語の整理（混同しやすいので最初に確認）**:

| 書き方 | 意味 | 確認方法 |
|---|---|---|
| `~` | ログイン中ユーザーのホーム（= `/home/ユーザー名`） | `echo ~` |
| 【Piのユーザー名】 | SSHログインに使う名前（例: pi） | `whoami` |
| デバイス名（246等） | 部屋の識別名。`--device-name` にだけ使う | サービスファイル内を参照 |

つまり `~/Raspberrypi` は `/home/【Piのユーザー名】/Raspberrypi` と同じ場所
（OPERATIONS.mdの推奨値どおり）。【Piのユーザー名】に部屋番号やホスト名を入れないこと。

(1) ローカルにコードを配置（NASのdeployからコピー）:

```
mkdir -p ~/Raspberrypi/temperature_humidity_notifier
cp /mnt/sensor_data/deploy/temp_humid_notifier.py ~/Raspberrypi/temperature_humidity_notifier/
```

コレクター役のPiは追加で:

```
mkdir -p ~/Raspberrypi/temperature_humidity_notifier/collector
cp /mnt/sensor_data/deploy/collector.py ~/Raspberrypi/temperature_humidity_notifier/collector/
cp /mnt/sensor_data/deploy/thresholds.example.yaml ~/Raspberrypi/temperature_humidity_notifier/collector/
```

(2) サービスファイルのパスを書き換え:

まず、このPi用の正しいExecStart行を画面に表示させる（コピペで実行するだけ）:

```
echo "ExecStart=/usr/bin/python3 /home/$(whoami)/Raspberrypi/temperature_humidity_notifier/temp_humid_notifier.py \\"
```

`$(whoami)` の部分が実際のユーザー名に展開されて表示されるので、
**表示された行をそのままコピー**しておき、nanoで開いてExecStartの1行目と差し替える:

```
sudo nano /etc/systemd/system/sensor-client.service
```

**続きの行の `--nas-target /mnt/sensor_data/incoming` はそのまま残す**
（`--device-name 246` などの部屋番号もそのまま。変えるのはExecStartの1行目だけ）。

コレクター役のPiは3ファイルも同様に直す。まず正しい3行を表示させる:

```
for cmd in ingest daily weekly-report; do echo "ExecStart=/usr/bin/python3 /home/$(whoami)/Raspberrypi/temperature_humidity_notifier/collector/collector.py $cmd --base-dir /mnt/sensor_data"; done
```

表示された3行を上から順に、対応するファイルのExecStart行と差し替える
（1行目→ingest、2行目→daily、3行目→weekly）:

```
sudo nano /etc/systemd/system/collector-ingest.service
sudo nano /etc/systemd/system/collector-daily.service
sudo nano /etc/systemd/system/collector-weekly.service
```

(3) 反映と動作確認:

```
sudo systemctl daemon-reload
sudo systemctl restart sensor-client
systemctl status sensor-client --no-pager
journalctl -u sensor-client -n 10 --no-pager
```

ログに「温度: …」が出ればOK。

### 1-3. NAS上の誤配置フォルダの削除（全Pi修正後に、どれか1台から1回だけ）

先に必ず中身を目視確認してから消す:

```
ls /mnt/sensor_data
ls /mnt/sensor_data/【誤って置いたフォルダ名】
rm -rf /mnt/sensor_data/【誤って置いたフォルダ名】
```

**`incoming` `config` `db` `logs` `reports` `deploy` は絶対に消さない**（データ・DB・設定の本体）。

---

## 作業2: センサー読み取りリトライ版の配布（4台すべてのPiで）

開発機で2ファイルを更新済み:

- `temp_humid_notifier.py`: 読み取り失敗時に10分待たず15秒間隔で最大5回再試行。
  `--once`（1回だけ測定して終了する確認モード）を追加。起動ログにバージョン表示
- `collector/collector.py`: `status` サブコマンド（各部屋の最終受信時刻・件数の表示）を追加

これを全Piに配布して反映する。

(1) 開発機（このWindows PC）からNASのdeployフォルダへ新版を置く。
Synologyのweb画面（File Station）経由でアップロードする:

1. ブラウザで DSM（`http://【NASのIP】:5000`）に**管理者アカウント**でログイン
   （sensor-uploader / sensor-collector はDSMに入れない設定なので使えない）
2. File Station を開き、`sensor_data` → `deploy` フォルダに移動
3. 開発機の次の2ファイルをドラッグ＆ドロップでアップロード（上書きを選ぶ）:
   - `C:\Users\Shinichi\PycharmProjects\Raspberrypi\temperature_humidity_notifier\temp_humid_notifier.py`
   - `C:\Users\Shinichi\PycharmProjects\Raspberrypi\temperature_humidity_notifier\collector\collector.py`

(2) 各Piで新版をコピーしてサービス再起動（4台それぞれで実行）:

```
cp /mnt/sensor_data/deploy/temp_humid_notifier.py ~/Raspberrypi/temperature_humidity_notifier/
sudo systemctl restart sensor-client
journalctl -u sensor-client -n 10 --no-pager
```

起動ログに「センサー監視を開始します (version 2026-07-09)」と出ていれば新版が動いている。
読み取りに失敗した場合は「読み取りに失敗しました（1/5回目）。15秒後に再試行します」と出る。

コレクター役のPiは collector.py も更新する:

```
cp /mnt/sensor_data/deploy/collector.py ~/Raspberrypi/temperature_humidity_notifier/collector/
```

**注意**: 作業1でリポジトリの場所を直すPiは、**先に作業1を終わらせてから**この配布を行うこと
（順番が逆だと、直す前の古い場所に上書きして無駄になる）。

## 作業3: コレクター設定の続き（コレクター役のPiで）

### 3-1. 現状確認（どこまで終わっているか）

```
python3 -c "import yaml, matplotlib, slack_sdk; print('ライブラリ OK')"
ls -l ~/Raspberrypi/temperature_humidity_notifier/collector/collector.py
ls -l /mnt/sensor_data/config/thresholds.yaml
sudo ls -l /etc/sensor-collector.env
systemctl list-timers --no-pager | grep collector
```

| 失敗した行 | 再開する場所（OPERATIONS.md） |
|---|---|
| ライブラリ | 4-1（pip install） |
| collector.py | 4-2（コード配置。上の1-2(1)と同じ） |
| thresholds.yaml | 4-2 後半（configの用意） |
| sensor-collector.env | 4-3（Slack接続情報） |
| timers が3行出ない | 4-4（定期実行の登録） |

**注意**: `/etc/sensor-collector.env` の SLACK_TOKEN は**再発行した新しいトークン**を使うこと
（旧トークンはコード直書きで漏えいしたため無効化・再発行が必要）。

### 3-2. 最終確認（フェーズ5相当）

```
sudo systemctl start collector-ingest
tail -20 /mnt/sensor_data/logs/collector.log
```

「取り込み完了: …」が出ればOK。続けて全部屋の受信状況を一覧で確認:

```
python3 ~/Raspberrypi/temperature_humidity_notifier/collector/collector.py status
```

4部屋すべてに最終データの時刻が表示され、「未取り込みファイル: 0件」ならデータの流れは正常。

```
sudo systemctl start collector-weekly
```

1分ほどでSlackにグラフが届けば完了（初日はグラフがスカスカで正常）。

### 完了条件

- [ ] 4台すべてで ExecStart のパスがローカル（`/home/...`）になっている
- [ ] NAS直下が `incoming` `config` `db` `logs` `reports` `deploy` だけになっている
      （`reports` は週次レポート初回実行後に自動生成されるため、この時点で無くても正常）
- [ ] 4台すべてでリトライ版に更新し、`systemctl status sensor-client` が active (running)
- [ ] `systemctl list-timers | grep collector` で3行表示される
- [ ] 手動実行でSlackに週次グラフが届いた
