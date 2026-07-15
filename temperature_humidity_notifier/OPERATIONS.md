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

# 温湿度監視システム 運用手順書

**対象読者**: パソコンの基本操作はできるが、Raspberry Pi や Linux は初めての方。
必要な操作はすべてこの手順書に書いてあります。わからない言葉が出てきたら、
まず巻末の「用語集」を見てください。

---

## 0. はじめに

### このシステムは何をしているか

研究室の4つの部屋に、温度と湿度を測る小さなコンピュータ（Raspberry Pi、以下「Pi」）が
1台ずつ置いてあります。測ったデータは、データ保管庫（NASという機械）に自動で集まります。
そして、次の3つの場合だけSlackに通知が届きます。

1. **週次レポート**（毎週月曜の朝）: 4部屋分の1週間のグラフが1枚届く
2. **温度急変アラート**: どこかの部屋の温度が急に変わったとき
3. **欠測アラート**: どこかの部屋のデータが2時間以上届かなくなったとき

### 安心してください

- この手順書のコマンドは、**書いてあるとおりに実行すれば壊れない**ように作ってあります
- 同じコマンドを2回実行してしまっても問題ありません
- 「実行したか覚えていない」場合は、もう一度実行して大丈夫です
- 逆に、**手順書に書いていないコマンドは実行しないでください**。
  
### この手順書の読み方

- **フェーズ1〜7** に分かれています。引き継いだ場合、最初から読む必要はありません。
  **各フェーズの冒頭にある「状態確認」を実行**すると、そのフェーズが終わっているかわかります。
  終わっていれば飛ばしてください
- `【 】` で囲まれた部分は、下の「設定値メモ」を見て**自分で置き換え**ます。
  例: 手順書に `ping 【NASのIP】` とあり、メモに NASのIP = 192.168.1.10 とあれば、
  実際に入力するのは `ping 192.168.1.10` です（【 】は入力しない）

### 設定値メモ（引き継ぎ時に記入・更新すること）

| 項目 | 値（記入欄） | 例 |
|---|---|---|
| 【NASのIP】 | ___________ | 192.168.1.10 |
| 【通知チャンネル名】 | ___________ | #sensor-notify |
| 【通知チャンネルID】 | ___________ | C0XXXXXXXXX |
| 【Piのユーザー名】 | ___________ | pi |
| 【リポジトリの場所】 | ___________ | /home/pi/Raspberrypi |
| デバイス名（部屋ごと） | ___ / ___ / ___ / ___ | 246 / 247 / 248 / 249 |
| コレクター役のPi | ___________ | 246のPi |
| 各PiのIPアドレス | ___ / ___ / ___ / ___ | 192.168.1.21〜24 |

**【リポジトリの場所】の注意**: 必ず `/home/` で始まる**Pi本体の中のパス**を記入してください。
`/mnt/sensor_data`（NASの中）は**不可**です（理由は3-4参照。実際に起きた間違いです）。

### 全体像（何がどう動いているか）

1. **センサーPi（4台）**: 10分ごとに部屋の温湿度を測定し、自分の中に記録したうえで、
   NASにデータファイルを置く
2. **NAS**: データの保管庫。各Piからは `/mnt/sensor_data` というフォルダとして見える
3. **コレクターPi（4台のうち1台が兼任）**: 10分ごとにNASの新着データを整理し、
   異常があればSlackに通知。週1回グラフを作ってSlackに投稿する
4. **Slack**: 人間（あなた）が見る場所

NASの `sensor_data` フォルダの中身:

| フォルダ | 役割 |
|---|---|
| `incoming/` | 各Piから届いたデータの受け口（整理後に自動で消える） |
| `db/` | データベース本体（全部屋の全データが入っている） |
| `config/` | アラート設定（thresholds.yaml） |
| `reports/` | 過去の週次グラフの保管場所 |
| `logs/` | コレクターの動作記録 |

---

# フェーズ0: 基本操作を覚える（5分・最初に1回だけ読む）

以降のすべてのフェーズで使う基本操作です。ここだけは飛ばさずに読んでください。

## 0-1. Piに接続する（SSH）

Piには画面がつながっていないので、あなたのパソコンから「SSH」という仕組みで接続して操作します。

1. Windowsなら「PowerShell」を起動する（スタートメニューで PowerShell と検索）。
   Macなら「ターミナル」を起動する
2. 次のように入力してEnterを押す:
   ```
   ssh 【Piのユーザー名】@【そのPiのIPアドレス】
   ```
   例: `ssh pi@192.168.1.21`
3. 初めて接続するPiでは `Are you sure you want to continue connecting?` と聞かれるので、
   `yes` と入力してEnter
4. パスワードを聞かれたら入力してEnter。
   **注意: パスワードは打っても画面に何も表示されません（●も出ない）。故障ではないので、
   そのまま打ち切ってEnterを押してください**
5. 接続に成功すると、行の先頭が `pi@raspberrypi:~ $` のような表示に変わります。
   この状態で入力したコマンドは、手元のパソコンではなく**Piの中で**実行されます
6. 作業が終わったら `exit` と入力してEnterで切断します

## 0-2. コマンドの実行と結果の見方

- この手順書で `$` から始まる行がコマンドです。**`$` は入力せず**、その後ろだけを入力してEnter
- コピー＆ペーストで大丈夫です。貼り付けは、PowerShellでは**右クリック**、
  Macでは Cmd+V です
- 複数行のコマンドの塊（あとで出てくる `EOF` を含む長いもの）は、
  **塊全体を一度に全部コピーして貼り付けて**ください。1行ずつでなくて大丈夫です
- コマンドを実行して何も表示されず次の `$` が出てきたら、それは**成功**です
  （Linuxは成功時に黙っていることが多い）。
  `command not found`（コマンドが見つからない）と出たら入力ミスの可能性が高いので、
  もう一度コピーし直してください

## 0-3. ファイルの編集（nano）

設定ファイルの書き換えには `nano` という画面内エディタを使います。

1. `nano ファイル名` で開く（手順書に書いてあるとおりに実行すればOK）
2. **矢印キー**で移動し、普通に文字を打って書き換える（マウスは使えません）
3. 保存: **Ctrl+O** を押し、ファイル名がそのまま表示されるので **Enter**
4. 終了: **Ctrl+X**
5. 間違えたら保存せずに Ctrl+X → `N` で、何も変えずにやり直せます

## 0-4. sudo とは

コマンドの先頭の `sudo` は「管理者権限で実行する」という意味です。
システム設定を変えるコマンドに付いています。パスワードを聞かれたら
Piのパスワードを入力してください（これも画面には表示されません）。

---

# フェーズ1: Slackの準備

**このフェーズでやること**: 通知を受け取るSlackチャンネルと、通知を送るBot（ロボットアカウント）を用意する。
**所要時間**: 約15分。**作業場所**: 自分のパソコンのブラウザ。

### 状態確認
1. Slackに【通知チャンネル名】のチャンネルがあり、メンバー一覧にBotの名前がある → 完了している
2. Slackトークン（`xoxb-` で始まる長い文字列。Botの「鍵」にあたる）を管理者が保管している → 完了している

### 手順（管理者が行う。アルバイトの方は飛ばしてOK）
1. https://api.slack.com/apps を開き「Create New App」→「From scratch」→
   アプリ名（例: sensor-bot）を入力し、研究室のワークスペースを選択
2. 左メニュー「OAuth & Permissions」→「Scopes」→「Bot Token Scopes」で「Add an OAuth Scope」を押し、
   以下の2つを追加:
   - `chat:write`（メッセージ送信の許可）
   - `files:write`（グラフ画像送信の許可）
3. 同じページの上のほうにある「Install to Workspace」を押してインストールすると、
   「Bot User OAuth Token」（`xoxb-` で始まる）が表示されるので控える。
   **注意: このトークンは合鍵のようなもの。メールやチャットに貼らず、管理者が安全に保管する。
   もし漏れたら、同じ画面の「Regenerate」で作り直し、古いものを無効にする**
4. Slackで通知用チャンネルを1つ作り、そのチャンネルで `/invite @sensor-bot`（Botの名前）と
   発言してBotを招待する
5. チャンネルIDを調べる: チャンネル名をクリック →「チャンネル詳細」→ 一番下に
   `C0` で始まる文字列が表示される。これが【通知チャンネルID】

### フェーズ1完了条件
- [ ] チャンネルが1つだけあり、Botが参加している
- [ ] トークンとチャンネルIDが「設定値メモ」に記録されている

---

# フェーズ2: NAS（Synology）の準備

**このフェーズでやること**: データ保管庫（NAS）に、このシステム専用の保管場所と専用アカウントを作る。
**所要時間**: 約30分。**作業場所**: 自分のパソコンのブラウザ（DSM = NASの管理画面）。

### 状態確認
どれか1台のPiにSSH接続（フェーズ0参照）して実行:
```
$ ping -c 3 【NASのIP】
```
`3 received` のような応答があり、かつブラウザで `http://【NASのIP】:5000` を開いて
共有フォルダ `sensor_data` とユーザー `sensor-uploader` `sensor-collector` がある → 完了している

### 手順（DSM管理画面での操作。NASの管理者アカウントが必要）

**2-1. 共有フォルダの作成**（データの置き場所を作る）

1. DSMにログイン → コントロールパネル →「共有フォルダ」→「作成」
2. 名前: `sensor_data`。「ごみ箱を有効にする」はオン推奨。それ以外はそのまま「次へ」でOK

**2-2. スナップショットの有効化**（自動バックアップの保険）

1. パッケージセンターで「Snapshot Replication」を検索してインストール
2. Snapshot Replication を開く →「スナップショット」→ `sensor_data` を選択 →
   スケジュール「毎日」、保持数「30」で設定
3. これで、万一データを間違って消しても過去30日分の状態に戻せるようになります

**2-3. 専用ユーザーの作成（2つ）**

**注意: ここが安全上いちばん重要です。** この2ユーザーに `sensor_data` 以外のフォルダの
権限を与えないでください。こうしておくと、万一Piが乗っ取られても、
NASに入っている他のデータ（写真や書類）には手が届きません。

1. コントロールパネル →「ユーザーとグループ」→「作成」で以下の2つを作る:
   - `sensor-uploader`: センサーPiがデータを**置く**ためのユーザー
   - `sensor-collector`: コレクターPiがデータを**読み書きする**ためのユーザー
2. 作成ウィザードの途中、両ユーザーとも次のように設定する:
   - 「共有フォルダの権限」: `sensor_data` だけ「読取り/書込み」。
     **他のフォルダはすべて「アクセス不可」にチェック**
   - 「アプリケーションの権限」: 「SMB」だけ許可。**DSMを含む他はすべて「拒否」**
3. パスワードは2つとも長いもの（16文字以上）にして、管理者が保管する

**2-4. SMBサービスの確認**（PiからNASのフォルダが見えるようにする仕組み）

1. コントロールパネル →「ファイルサービス」→「SMB」タブ → 「SMBサービスを有効にする」がオンか確認
2. 「詳細設定」→ 最小SMBプロトコルを「SMB2」以上にする

**2-5. ファイアウォール（接続元の制限）**

「SMB（ファイル共有）にはPiの4台だけが接続できる」ようにする設定です。

**注意（締め出し防止）**: ここで作るのは「SMBの許可」と「SMBの拒否」の**2つの規則だけ**です。
画面の一番下にある「上記の規則に一致しない場合: **許可**」は**そのまま変えない**でください。
これを「拒否」にすると、DSMの管理画面自体に入れなくなることがあります。

1. コントロールパネル →「セキュリティ」→「ファイアウォール」タブを開く
2. 「ファイアウォールを有効にする」にチェックを入れ、「適用」
   （チェックを入れないと規則の作成ボタンが押せません）
3. 「ファイアウォールプロファイル」の「規則を編集」を押し、「作成」で **1つ目の規則（許可）** を作る:
   - ポート: 「内蔵アプリケーションのリストから選択」→ 一覧から
     「Windowsファイルサーバー（SMB）」にチェック（見つからない場合は
     「カスタム」→ プロトコルTCP・ポート445 でも同じ意味です）
   - 送信元IP: 「特定のIP」→「単一ホスト」でPiのIPを1つ入力。
     PiのIPが連番なら「範囲」でまとめて指定できます（例: 192.168.1.21 〜 192.168.1.24）。
     単一ホストで作る場合は、この規則をPiの台数分（4つ）作ります
   - アクション: 「許可」
4. 続けて「作成」で **2つ目の規則（拒否）** を作る:
   - ポート: 1つ目と同じ「Windowsファイルサーバー（SMB）」
   - 送信元IP: 「すべて」
   - アクション: 「拒否」
5. 規則の一覧で、**「許可」の規則が「拒否」より上**にあることを確認する
   （規則は上から順に判定されるため、順番が逆だとPiもつながらなくなります。
   ドラッグで並べ替えられます）
6. 「OK」→「適用」で保存。直後に、コレクターPiで `ls /mnt/sensor_data`、
   自分のパソコンでDSM画面の再読み込みをして、両方問題ないことを確認する

補足:
- この設定は「Piが乗っ取られた場合の保険」を強くする追加の防御です。
  どうしてもうまくいかない場合は**いったん飛ばして先に進んでも動作に支障はありません**
  （専用ユーザーの権限制限とスナップショットが主な防御です）。後日改めて設定してください
- 万一DSMに入れなくなった場合は、NAS本体のRESETボタンを約4秒（ビープ音1回）押すと
  ネットワーク設定とファイアウォールが初期化され、入れるようになります（保存データは消えません）

最後に、ルーターの管理画面で、NASと各PiのIPアドレスを「固定」（DHCP固定割当）にしておく。
固定しないと、ある日IPが変わってファイアウォールに弾かれ、全部つながらなくなることがあります。

### フェーズ2完了条件
- [ ] 共有フォルダ `sensor_data` がある
- [ ] スナップショットが毎日実行される設定になっている
- [ ] `sensor-uploader` / `sensor-collector` が sensor_data 以外にアクセスできない
- [ ] PiからNASにpingが通る

---

# フェーズ3: センサーPiの移行（4台それぞれで行う）

**このフェーズでやること**: 各Piで旧プログラムを止め、新プログラムに入れ替え、NASにつなぐ。
**所要時間**: 1台あたり約30分。1台で成功すれば残り3台は同じ作業の繰り返しです。
**作業場所**: 各PiにSSH接続して行う（フェーズ0参照）。

### 状態確認
対象のPiにSSH接続して実行:
```
$ systemctl status sensor-client --no-pager
```
- 緑色で `active (running)` と出る → このPiは**完了している**。次のPiへ
- `Unit sensor-client.service could not be found.` と出る → このフェーズを実施する

### 手順

**3-1. 旧システムの停止**（新旧が同時に動くとセンサーの取り合いになるため、先に止める）

旧プログラムが動いているか確認:
```
$ ps aux | grep temp_humid | grep -v grep
```
- 何も表示されない → 動いていないので 3-2 へ
- 1行以上表示された → その行の**左から2番目の数字**（プロセス番号）を控える（例では `460`）

**重要**: 旧プログラムは `myapp.service` のような**関係なさそうな名前**のサービスから
自動起動されていることがあります。名前で探すと取り逃すため、**動いているプロセスが
どのサービスに属しているか**を直接調べて、それを無効化します（`kill` だけだと再起動で復活します）。

```
$ systemctl status 【控えたプロセス番号】
```
表示の先頭に出るユニット名（`● 〇〇.service`）が犯人です。それを恒久停止する:
```
$ sudo systemctl disable --now 〇〇.service
```
- ユニット名が `sensor-client.service` だった場合は、それは新プログラムなので止めない
- cgroup が `session-x.scope` や `user@1000.service` 配下だった場合は、手動起動（Thonny等）なので
  `sudo kill 【プロセス番号】` で止める

止めたあと、本当に消えたか確認する（1行も出なければOK）:
```
$ ps aux | grep temp_humid | grep -v grep
```

**3-2. 不足ソフトの確認とインストール**（旧システムのソフトは使い回すので、追加は最小限）

まず、何が足りないか確認する:
```
$ python3 -c "import adafruit_dht" 2>/dev/null && echo "センサーライブラリOK" || echo "センサーライブラリ 要インストール"
$ dpkg -s cifs-utils > /dev/null 2>&1 && echo "cifs-utils OK" || echo "cifs-utils 要インストール"
```
「要インストール」と表示されたものだけ、対応するコマンドを実行する:
```
$ sudo apt-get install -y cifs-utils
$ pip install adafruit-circuitpython-dht --break-system-packages
```
両方「OK」なら何もインストールしなくてよい。

**3-3. NASをマウントする**（NASの保管場所を、Piのフォルダとして見えるようにする）

(1) NASに接続するためのパスワードファイルを作る。
次の塊を**全部まとめて**コピーして貼り付け、Enter:
```
$ sudo tee /etc/cifs-sensor-credentials > /dev/null << 'EOF'
username=sensor-uploader
password=ここにパスワードを書く
EOF
```
(2) 今作ったファイルを開いて、パスワードを本物に書き換える
（sensor-uploaderのパスワードは管理者に聞く。nanoの使い方はフェーズ0参照）:
```
$ sudo nano /etc/cifs-sensor-credentials
$ sudo chmod 600 /etc/cifs-sensor-credentials
```
`chmod 600` は「このファイルを他人が読めないようにする」という意味です。

**注意: コレクター役のPi（設定値メモ参照）だけは、`username=sensor-collector` と書き、
sensor-collector のパスワードを入れてください。**

(3) 起動時に自動でNASにつながるように設定する。
1行目を実行 → 2行目の長い1行を実行 → nanoで【 】を書き換え:
```
$ sudo mkdir -p /mnt/sensor_data
$ grep -q sensor_data /etc/fstab || echo "//【NASのIP】/sensor_data /mnt/sensor_data cifs credentials=/etc/cifs-sensor-credentials,vers=3.0,uid=【Piのユーザー名】,iocharset=utf8,nobrl,nofail,_netdev 0 0" | sudo tee -a /etc/fstab
$ sudo nano /etc/fstab
```
nanoで開いたら、一番下の行に今追加した設定があるので、【NASのIP】と【Piのユーザー名】が
実際の値になっているか確認・修正して保存する。

**`nobrl` について**: これはCIFS（NAS共有）上でのバイト範囲ロックを無効化するオプションです。
コレクター役のPiは、この上のSQLiteデータベース（`db/sensor_data.sqlite3`）に書き込みます。
CIFSはこのロックに対応しておらず（マウント表示の `nounix`）、`nobrl` が無いと
コレクターが `database is locked` で必ず失敗します。DBに書き込むのはコレクター1台だけの
設計なので、ロック無効化による危険はありません。センサー専用のPiには影響しないので、
**全Piで付けておいて問題ありません**（実際に起きた不具合の対策です）。

(4) 実際につないでみる:
```
$ sudo systemctl daemon-reload
$ sudo mount -a
$ touch /mnt/sensor_data/test_$(hostname) && ls /mnt/sensor_data && rm /mnt/sensor_data/test_$(hostname)
```
最後のコマンドは「テストファイルを書いて、一覧を見て、消す」という接続テストです。
エラーが出ずにフォルダの一覧が表示されれば成功。
`Permission denied` や `could not resolve address` などが出たら、
(2)のパスワードや(3)のIPアドレスの書き間違いを疑ってください。

(5) データの受け口フォルダ `incoming` があることを確認する（無ければ作る）。
**重要**: 各Piは NAS の `/mnt/sensor_data/incoming` にデータを送ります。この `incoming` フォルダは
**あらかじめNAS上に存在している必要**があり、**無い場合は「送信先フォルダが見つかりません」という
マウント切れとまったく同じエラー**が出てセンサーのデータが送れません（紛らわしいので要注意）。
NAS全体で1つあれば十分なので、最初にセットアップするPiで一度だけ作成します。
2台目以降は既にあるはずなので、下のコマンドで「あり」と出れば作成不要です:
```
$ ls -ld /mnt/sensor_data/incoming 2>/dev/null && echo "→ incoming あり（作成不要）" || mkdir /mnt/sensor_data/incoming
$ ls -ld /mnt/sensor_data/incoming
```
最後に `drwx...` で始まる行が表示されれば成功です。
`mkdir` が `Permission denied` で失敗する場合は、NAS側（Synologyなどの管理画面）で
`sensor_data` 共有の直下に `incoming` フォルダを作り、sensor-uploader に書き込み権限を
与えてください。

**3-4. 新しいコードの配置**

**【リポジトリの場所】について（ここで決める）**
このあと何度も出てくる 【リポジトリの場所】 は、**このPi自身の中の、コードを置くフォルダ**です。
以降のすべての箇所で**まったく同じパス**を使ってください。

- **推奨値**: `/home/【Piのユーザー名】/Raspberrypi`
  （例: ユーザー名が `th-meter1` なら `/home/th-meter1/Raspberrypi`）
  この場合、実行するプログラム本体のフルパスは
  `/home/【Piのユーザー名】/Raspberrypi/temperature_humidity_notifier/temp_humid_notifier.py` になります。
- **NG例**: `/mnt/sensor_data/...`（NASの中）に置かないこと。
  NASはデータの**送り先**であって、コードの置き場所ではありません。
  NAS上にコードを置くと、NASのマウントが一時的に外れただけでプログラムが起動できなくなります
  （`status=203/EXEC` や `No such file or directory` で落ちる）。コードは必ずPi本体の中に置きます。
- 迷ったら、実際の値は `whoami`（ユーザー名の確認）で出た名前を 【Piのユーザー名】 に当てはめて決めます。

このPiに入れるファイルは1つだけです: `temp_humid_notifier.py`（新版）。
入手方法は、やりやすいものを1つ選ぶ:

- **方法A: NAS経由（おすすめ・3-3が終わっていれば使える）**
  管理者が自分のパソコンのブラウザからDSMのFile Station（NASのweb画面）で
  `sensor_data` フォルダに `deploy` フォルダを作り、ファイルをアップロードしておく
  （DSMには管理者アカウントでログインする。sensor-uploader等はDSMに入れない）。
  Piでは次を実行してコピーする:
  ```
  $ mkdir -p 【リポジトリの場所】/temperature_humidity_notifier
  $ cp /mnt/sensor_data/deploy/temp_humid_notifier.py 【リポジトリの場所】/temperature_humidity_notifier/
  ```
- **方法B: 自分のパソコンから転送（scp）**
  ファイルが自分のパソコンにある場合、**パソコン側の** PowerShell/ターミナルで:
  ```
  scp temp_humid_notifier.py 【Piのユーザー名】@【PiのIP】:【リポジトリの場所】/temperature_humidity_notifier/
  ```
- **方法C: メールで受け取った場合**
  添付ファイルを自分のパソコンに保存してから、方法Bで転送する
- **方法D: git（Piがインターネットにつながり、以前からgitで管理している場合のみ）**
  ```
  $ cd 【リポジトリの場所】 && git pull
  ```

**3-5. サービスとして登録**（Piの電源を入れたら自動で動き出すようにする）

(1) 次の塊を**全部まとめて**コピーして貼り付け、Enter:
```
$ sudo tee /etc/systemd/system/sensor-client.service > /dev/null << 'EOF'
[Unit]
Description=Temperature/Humidity sensor client
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=【Piのユーザー名】
# lgpio は起動時に通知用ファイル(.lgd-nfy-N)をカレントディレクトリに作る。
# 未指定だと作業ディレクトリが / になり書き込めず FileNotFoundError で落ちるため、
# 書き込み可能なホームディレクトリを明示する
WorkingDirectory=/home/【Piのユーザー名】
ExecStart=/usr/bin/python3 【リポジトリの場所】/temperature_humidity_notifier/temp_humid_notifier.py \
    --device-name 246 \
    --nas-target /mnt/sensor_data/incoming \
    --save-dir /home/【Piのユーザー名】/sensor_logs
Restart=on-failure
RestartSec=60

[Install]
WantedBy=multi-user.target
EOF
```
(2) nanoで開いて、【 】の2か所と `--device-name 246` の部屋番号を書き換える。
**注意: `--device-name` はこのPiの部屋の名前にする（部屋ごとに違う値）。**
```
$ sudo nano /etc/systemd/system/sensor-client.service
```
書き換えたら、間違いがないか次のコマンドで確認する:
```
$ grep -A 3 ExecStart /etc/systemd/system/sensor-client.service
```
確認するポイントは2つ:

- 1行目のプログラムのパスが `/home/` で始まっている
  （`/mnt/sensor_data` で始まっていたら【リポジトリの場所】の間違い。nanoで開き直して修正する）
- `--nas-target /mnt/sensor_data/incoming` の行はこのままが**正しい**（こちらは変えない。
  「コードはPiの中、データの送り先はNAS」という役割分担です）

(3) 有効化して起動:
```
$ sudo systemctl daemon-reload
$ sudo systemctl enable --now sensor-client
```

**3-6. 動作確認**
```
$ systemctl status sensor-client --no-pager
```
`Active: active (running)` と表示されればOK。続いて動作記録（ログ）を見る:
```
$ journalctl -u sensor-client -n 20 --no-pager
```
次のような行が出ていれば成功です:
```
温度: 21.3°C, 湿度: 52.1%
NASへ12960行を送信しました: 246_20260707_100000_123456.csv
```
初回は「NASへ○○○○行を送信しました」と**大きな数字**が出ますが、これは正常です
（Piに溜まっていた過去のデータをまとめてNASに引っ越ししているため）。

最後にNAS側にも届いているか確認:
```
$ ls /mnt/sensor_data/incoming/
```
自分のデバイス名（例: 246）のフォルダがあればOK。

### フェーズ3完了条件（4台すべてで）
- [ ] 旧プログラムが止まっている（`ps aux | grep temp_humid | grep -v grep` で何も出ない）
- [ ] `systemctl status sensor-client` が active (running)
- [ ] ログに「温度: …」と「NASへ…送信しました」が出ている
- [ ] Piを再起動（`sudo reboot`）して2〜3分待ち、再びSSH接続して上の2つを確認しても同じ

---

# フェーズ4: コレクターPiの設定（1台だけ）

**このフェーズでやること**: 4台のうち1台（コレクター役）に、データ整理とSlack通知の係を追加する。
**所要時間**: 約30分。**前提**: そのPiでフェーズ3が完了していること
（NASマウントは3-3で `sensor-collector` として設定済みのはず）。

### 状態確認
コレクター役のPiにSSH接続して実行:
```
$ systemctl list-timers --no-pager | grep collector
```
`collector-ingest` `collector-daily` `collector-weekly` の3行が表示される → 完了している

### 手順

**4-1. 不足ソフトの確認とインストール**

旧システムでグラフ生成やSlack送信をしていたPiなら、ほとんど入っています。確認:
```
$ python3 -c "import yaml"       2>/dev/null && echo "yaml OK"       || echo "yaml 要インストール"
$ python3 -c "import matplotlib" 2>/dev/null && echo "matplotlib OK" || echo "matplotlib 要インストール"
$ python3 -c "import slack_sdk"  2>/dev/null && echo "slack_sdk OK"  || echo "slack_sdk 要インストール"
```
「要インストール」と出たものだけ入れる:
```
$ pip install pyyaml --break-system-packages
$ pip install matplotlib --break-system-packages
$ pip install slack_sdk --break-system-packages
```

**4-2. コレクターのコードと設定ファイルを配置**

このPiに追加で入れるファイルは2つ（入手方法はフェーズ3の3-4と同じ。NAS経由がおすすめ）:

- `collector.py` → 置き場所: `【リポジトリの場所】/temperature_humidity_notifier/collector/`
- `thresholds.example.yaml` → 同上

```
$ mkdir -p 【リポジトリの場所】/temperature_humidity_notifier/collector
$ cp /mnt/sensor_data/deploy/collector.py 【リポジトリの場所】/temperature_humidity_notifier/collector/
$ cp /mnt/sensor_data/deploy/thresholds.example.yaml 【リポジトリの場所】/temperature_humidity_notifier/collector/
```
（NAS経由の場合の例。scp等で置いた場合はこの2行は不要）

アラート設定ファイルをNAS上に用意する（すでにあれば何も起きない安全なコマンド）:
```
$ mkdir -p /mnt/sensor_data/config
$ [ -f /mnt/sensor_data/config/thresholds.yaml ] || cp 【リポジトリの場所】/temperature_humidity_notifier/collector/thresholds.example.yaml /mnt/sensor_data/config/thresholds.yaml
```

**4-3. Slackの接続情報を置く**

(1) 次の塊を全部まとめて貼り付けてEnter:
```
$ sudo tee /etc/sensor-collector.env > /dev/null << 'EOF'
SLACK_TOKEN=xoxb-ここにトークンを書く
SLACK_CHANNEL_ID=ここに通知チャンネルIDを書く
EOF
```
(2) nanoで開いて本物の値に書き換え、他人が読めないようにする:
```
$ sudo nano /etc/sensor-collector.env
$ sudo chmod 600 /etc/sensor-collector.env
```

書き換えるときの注意（間違えやすいポイント）:

- `SLACK_CHANNEL_ID` に書くのは**チャンネル名（#sensor-notify など）ではなく**、
  `C0` で始まるチャンネルID（フェーズ1の手順5で調べたもの）。
  名前を書くと `channel_not_found` エラーで送信に失敗します
- `SLACK_TOKEN` は**現在有効な**トークン（`xoxb-` で始まる）を書く。
  漏えい等で再発行（Regenerate）した場合、**古いトークンは絶対に使わない**
  （古いものを書くと `invalid_auth` エラーになります）
- Botが通知チャンネルに**招待済み**であること（フェーズ1の手順4）。
  トークンとIDが正しくても、未招待だと `not_in_channel` エラーで送信に失敗します
- `=` の前後にスペースを入れない（`SLACK_TOKEN = xoxb-...` はNG、`SLACK_TOKEN=xoxb-...` が正しい）

**4-4. 定期実行の登録**

コレクターは「10分ごとの整理」「毎晩の集計＋前日サマリ通知」「毎週月曜のレポート」の3つの時間割で動きます。
次の長い塊を、**上から順に1塊ずつ**コピーして貼り付けてください（全部で6塊）。

10分ごとの整理（その1）:
```
$ sudo tee /etc/systemd/system/collector-ingest.service > /dev/null << 'EOF'
[Unit]
Description=Sensor data collector - ingest and alerts
[Service]
Type=oneshot
User=【Piのユーザー名】
EnvironmentFile=/etc/sensor-collector.env
ExecStart=/usr/bin/python3 【リポジトリの場所】/temperature_humidity_notifier/collector/collector.py ingest --base-dir /mnt/sensor_data
EOF
```
10分ごとの整理（その2・時間割）:
```
$ sudo tee /etc/systemd/system/collector-ingest.timer > /dev/null << 'EOF'
[Unit]
Description=Run collector ingest every 10 minutes
[Timer]
OnCalendar=*:00/10
Persistent=true
[Install]
WantedBy=timers.target
EOF
```
毎晩の集計（その1）:
```
$ sudo tee /etc/systemd/system/collector-daily.service > /dev/null << 'EOF'
[Unit]
Description=Sensor data collector - daily summary
[Service]
Type=oneshot
User=【Piのユーザー名】
EnvironmentFile=/etc/sensor-collector.env
ExecStart=/usr/bin/python3 【リポジトリの場所】/temperature_humidity_notifier/collector/collector.py daily --base-dir /mnt/sensor_data
EOF
```
毎晩の集計（その2・時間割）:
```
$ sudo tee /etc/systemd/system/collector-daily.timer > /dev/null << 'EOF'
[Unit]
Description=Run collector daily at 03:30
[Timer]
OnCalendar=*-*-* 03:30:00
Persistent=true
[Install]
WantedBy=timers.target
EOF
```
週次レポート（その1）:
```
$ sudo tee /etc/systemd/system/collector-weekly.service > /dev/null << 'EOF'
[Unit]
Description=Sensor data collector - weekly report
[Service]
Type=oneshot
User=【Piのユーザー名】
EnvironmentFile=/etc/sensor-collector.env
ExecStart=/usr/bin/python3 【リポジトリの場所】/temperature_humidity_notifier/collector/collector.py weekly-report --base-dir /mnt/sensor_data
EOF
```
週次レポート（その2・時間割）:
```
$ sudo tee /etc/systemd/system/collector-weekly.timer > /dev/null << 'EOF'
[Unit]
Description=Run collector weekly report on Monday 08:00
[Timer]
OnCalendar=Mon *-*-* 08:00:00
Persistent=true
[Install]
WantedBy=timers.target
EOF
```
次に、3つのファイルの【 】をnanoで書き換える（それぞれ2か所）:
```
$ sudo nano /etc/systemd/system/collector-ingest.service
$ sudo nano /etc/systemd/system/collector-daily.service
$ sudo nano /etc/systemd/system/collector-weekly.service
```
書き換えたら、3ファイルまとめて確認する:
```
$ grep ExecStart /etc/systemd/system/collector-*.service
```
3行とも、collector.py のパスが `/home/` で始まっていればOK
（`/mnt/sensor_data` で始まっていたら【リポジトリの場所】の間違いなので修正する）。
行末の `--base-dir /mnt/sensor_data` はこのままが**正しい**（変えない）。

最後に時間割を有効化:
```
$ sudo systemctl daemon-reload
$ sudo systemctl enable --now collector-ingest.timer collector-daily.timer collector-weekly.timer
```

### フェーズ4完了条件
- [ ] `systemctl list-timers --no-pager | grep collector` で3行表示される
- [ ] `ls -l /etc/sensor-collector.env /etc/cifs-sensor-credentials` の各行の先頭が
      `-rw-------` になっている（他人が読めない状態）

---

# フェーズ5: 全体の動作確認

**このフェーズでやること**: システム全体が正しくつながったかを確かめる。
**作業場所**: すべてコレクターPi上。

**5-1. データが流れているか**
```
$ ls /mnt/sensor_data/incoming/
```
4つのデバイス名フォルダが見えるはず。次に、整理を手動で1回動かす:
```
$ sudo systemctl start collector-ingest
$ tail -20 /mnt/sensor_data/logs/collector.log
```
ログに「取り込み完了: …」と出て、もう一度 `ls /mnt/sensor_data/incoming/246/` などを見ると
CSVファイルが消えていれば正常（データベースに移動した、という意味）。

全部屋の状況を1コマンドでまとめて見ることもできます（いつでも実行してよい安全なコマンド）:
```
$ python3 【リポジトリの場所】/temperature_humidity_notifier/collector/collector.py status
```
部屋ごとに「最終データの時刻・何分前か・最新の温湿度・累計行数」が表示されます。
2時間以上データが届いていない部屋には「要確認」と表示されます。

**5-2. 週次レポートを手動で送ってみる**
```
$ sudo systemctl start collector-weekly
```
1分ほどでSlackの通知チャンネルにグラフ画像が届けば成功。
（運用初日はデータが少なくグラフがスカスカですが、それで正常です）

**5-3. アラートのテスト（任意）**

アラートの感度を一時的に最大にして、本当に通知が来るか試します。
```
$ nano /mnt/sensor_data/config/thresholds.yaml
```
`defaults:` の下の `k: 3.0` を `k: 0.0` に書き換えて保存
→ 10分〜20分待つ（センサーPiのそばで温度を変える＝手で温める・息を吹きかけると確実）
→ Slackに温度急変アラートが届くことを確認
→ **必ず同じ手順で `k: 3.0` に戻して保存する（戻し忘れるとアラートが鳴りっぱなしになる）**

**5-4. 運用開始日を記録**

運用開始から1週間は「ベースライン期間」としてアラートは鳴りません
（各部屋の「普段の変動幅」をシステムが学習する準備期間です）。
開始日をここに記録: ____年____月____日

### フェーズ5完了条件
- [ ] 4デバイス分のデータがNASに届き、取り込まれている
- [ ] 手動実行で週次グラフがSlackに届いた
- [ ] アラートテストをした場合、k の値を 3.0 に戻した

---

# フェーズ6: 日常運用（あなたのメイン業務）

## 毎週月曜（5分）

1. Slackの通知チャンネルに**週次レポートのグラフが届いているか**確認する
   - 届いていない → フェーズ7の「週次レポートが届かない」へ
2. グラフに**4部屋すべてが載っているか**確認する
   - 「〇〇: 今週のデータなし（要確認）」と書かれていたら →
     フェーズ7の「特定の部屋のデータが止まった」へ
3. グラフの形をざっと眺めて、極端な異常がないか見る
   - 例: 数日間まったく変化のない真横の直線（センサーの固着が疑わしい）

## アラートが届いたとき

- **温度急変アラート**: その部屋に行って、次を確認する
  - エアコンが止まっていないか・設定が変わっていないか
  - ドアや窓が開けっぱなしになっていないか
  - 確認して問題なければ様子見でOK。設備の故障なら管理者へ連絡
- **欠測アラート**（データが届いていません、という通知）:
  フェーズ7の「特定の部屋のデータが止まった」の手順を実行

## 月1回（5分）

1. ブラウザで DSM（`http://【NASのIP】:5000`）にログインし、
   ストレージの空き容量が20%以上あるか確認
2. Snapshot Replication を開き、スナップショットが最近も取れているか確認

## 通知チャンネルやトークンを変更したいとき

Slackの設定を持っているのは**コレクターPiの `/etc/sensor-collector.env` の1ファイルだけ**です。
センサーPi（残り3台）はSlackの情報を一切持っていないので、何もしなくてよいです。

1. **先に**新しいチャンネルにBotを招待する: 新チャンネルで `/invite @Botの名前` と発言する
   （これを忘れると、設定が正しくても `not_in_channel` エラーで送信に失敗します）
2. 新チャンネルのIDを調べる: チャンネル名をクリック →「チャンネル詳細」→ 一番下の
   `C0` で始まる文字列（フェーズ1の手順5と同じ）
3. コレクターPiにSSH接続して設定ファイルを書き換える:
   ```
   $ sudo nano /etc/sensor-collector.env
   ```
   `SLACK_CHANNEL_ID=` の値を新しいIDに書き換えて保存する。
   トークンを再発行した場合も同じファイルの `SLACK_TOKEN=` を書き換えるだけです
4. **再起動やコマンドの再登録は不要**です（この設定ファイルは、コレクターが動くたびに
   毎回読み直される仕組みのため、次の実行から自動で新しい宛先になります）。
   すぐに確かめたい場合は手動で1回送ってみる:
   ```
   $ sudo systemctl start collector-weekly
   ```
   1分ほどで新チャンネルにグラフが届けば成功
5. 冒頭の「設定値メモ」の【通知チャンネル名】【通知チャンネルID】も書き直しておく

## アラートの感度調整（誤報が多い・見逃しがあるとき）

コレクターPiで:
```
$ nano /mnt/sensor_data/config/thresholds.yaml
```
該当する部屋の `k` の数字を変える:

- 誤報が多い（何もないのに鳴る）→ k を大きくする。例: 3.0 → 4.0
- 見逃しがある（異常だったのに鳴らなかった）→ k を小さくする。例: 3.0 → 2.5

変更したら「いつ・どの部屋・いくつからいくつへ」をメモに残すこと。

---

# フェーズ7: トラブル対応

**原則: ここに書いていないことはやらない。** 特に `rm`（削除）を含むコマンドは実行しない。
手順を実行しても直らなければ、無理をせず「エスカレーション基準」に従って管理者へ連絡する。

## 特定の部屋のデータが止まった（欠測アラート／グラフに出ない）

その部屋のPiにSSH接続して、上から順に実行する:
```
$ systemctl status sensor-client --no-pager
$ journalctl -u sensor-client -n 50 --no-pager
$ sudo systemctl restart sensor-client
$ journalctl -u sensor-client -n 20 --no-pager
```
（(1)状態を見る →(2)ログを見る →(3)再起動する →(4)復活したか見る、という流れです。
再起動だけで直ることがかなり多いです）

ログの内容ごとの対処:

- 「センサー読み取りエラー」が続く → センサーの配線を目で確認（コネクタの抜け・緩み）。
  差し直しても直らなければ管理者へ（センサー故障の可能性）
- 「送信先フォルダが見つかりません」「ローカルコピーに失敗」→ NASとの接続が切れている:
  ```
  $ ping -c 3 【NASのIP】
  $ sudo mount -a
  $ ls /mnt/sensor_data
  ```
  pingが通らないときはネットワークの問題（ルーター・LANケーブル・NASの電源を確認）
- 「No such file or directory: '.lgd-nfy...'」（起動直後にimport段階で落ちる）→
  サービス定義に `WorkingDirectory` が無く、作業ディレクトリが / で書き込めないのが原因。
  `sudo systemctl edit --full sensor-client` で `[Service]` に
  `WorkingDirectory=/home/【Piのユーザー名】` を追加し、
  `sudo systemctl daemon-reload && sudo systemctl restart sensor-client` を実行する
- 「unable to set line to input」→ センサー用の端子が固まっているので、リセットする:
  ```
  $ sudo systemctl stop sensor-client
  $ sudo python3 【リポジトリの場所】/temperature_humidity_notifier/gpio_reset.py
  $ sudo systemctl start sensor-client
  ```
- そもそもSSHがつながらない → Piの電源アダプタを抜き、10秒待って差し直す（最終手段。
  これは安全な操作で、データは失われません）

原因を詳しく調べたいときは、10分待たずにその場で1回だけ測定を試せます:
```
$ sudo systemctl stop sensor-client
$ python3 【リポジトリの場所】/temperature_humidity_notifier/temp_humid_notifier.py --once --device-name 【この部屋のデバイス名】 --nas-target /mnt/sensor_data/incoming --save-dir /home/【Piのユーザー名】/sensor_logs
$ sudo systemctl start sensor-client
```
「温度: …」と「NASへ…送信しました」が出れば、センサーもNAS接続も正常です。
**最後の start（サービスを元に戻す）を忘れないこと。**

**安心情報**: NASと切れていた間のデータはPi本体に貯まり続けていて、
接続が直ると自動でまとめて送信されます。多少止まってもデータは失われません。

## サービスが起動しない（status=203/EXEC・No such file or directory）

`systemctl status` の表示に `status=203/EXEC` や、プログラム本体の
`No such file or directory` が出るときは、**コードの置き場所とサービス設定のパスが
食い違っている**のが原因です。典型例は「【リポジトリの場所】を誤ってNASの中
（`/mnt/sensor_data/...`）にしてしまった」ケースです。次の手順で直します。

(1) サービスがどこのコードを見ているか確認する:
```
$ grep ExecStart /etc/systemd/system/sensor-client.service /etc/systemd/system/collector-*.service 2>/dev/null
```
プログラムのパスが `/mnt/sensor_data` で始まる行があれば誤配置です（コレクター役以外のPiでは
collector-* のファイルは無いのが正常で、その分のエラー表示は無視してよい）。

(2) コードをPi本体（正しい【リポジトリの場所】）に置き直す:
```
$ mkdir -p 【リポジトリの場所】/temperature_humidity_notifier
$ cp /mnt/sensor_data/deploy/temp_humid_notifier.py 【リポジトリの場所】/temperature_humidity_notifier/
```
コレクター役のPiは追加で:
```
$ mkdir -p 【リポジトリの場所】/temperature_humidity_notifier/collector
$ cp /mnt/sensor_data/deploy/collector.py 【リポジトリの場所】/temperature_humidity_notifier/collector/
```

(3) サービス設定のパスを直す（該当するファイルだけをnanoで開き、ExecStart の
プログラムのパスを `/home/...` に書き換える。**`--nas-target` や `--base-dir` の
`/mnt/sensor_data` は正しい設定なので変えない**）:
```
$ sudo nano /etc/systemd/system/sensor-client.service
```

(4) 反映して動作確認:
```
$ sudo systemctl daemon-reload
$ sudo systemctl restart sensor-client
$ systemctl status sensor-client --no-pager
```
`active (running)` になればOK。コレクター役のPiで collector-* も直した場合は
`sudo systemctl start collector-ingest` を実行し、
`tail -5 /mnt/sensor_data/logs/collector.log` にエラーがないことを確認する。

(5) 全Piを直し終えたら、NAS上に誤って置いたコードのフォルダを片付ける。
**削除の前に必ず管理者に確認**し、正規の5フォルダ
（`incoming` `db` `config` `reports` `logs`）と配布用の `deploy` は消さないこと。

## サービスが起動しない（既にプロセスが動いています／status=217/USER）

`journalctl -u sensor-client` に次が出てループしている場合の対処。

- **「既にプロセスが動いています (PID: ...)」** → 旧プログラムが別サービス（`myapp.service` など
  無関係な名前のことが多い）から二重起動され、ロックを握っています。`kill` だけでは再起動で
  復活するので、犯人のサービスを特定して無効化します（3-1 と同じ手順）:
  ```
  $ ps aux | grep temp_humid | grep -v grep
  $ systemctl status 【表示されたプロセス番号】
  $ sudo systemctl disable --now 【先頭に出たユニット名】.service
  $ sudo systemctl restart sensor-client
  ```
- **「status=217/USER」「Failed to determine user credentials」** → サービスの `User=` が
  実在しないユーザー名（綴り違い）になっています。`whoami` で正しい名前を確認し、
  `sudo systemctl edit --full sensor-client` で `User=` `WorkingDirectory=` `--save-dir` を
  すべて同じ名前に揃えます（`/home/thmeter1` と `/home/th-meter1` のような食い違いが原因）。

## コレクターが `database is locked` で失敗する

`collector.log` や `journalctl -u collector-ingest` に `database is locked` が出る場合、
NAS（CIFS）上のSQLiteロックが原因です。マウントに `nobrl` が付いているか確認します:
```
$ mount | grep sensor_data
```
出力に `nobrl` が**無ければ**、fstab に追加して入れ直します（コレクターPiで実行）:
```
$ sudo sed -i 's/,nobrl//g; s/iocharset=utf8/iocharset=utf8,nobrl/' /etc/fstab
$ grep sensor_data /etc/fstab
$ sudo reboot
```
再起動後 `mount | grep sensor_data` に `nobrl` が出ることを確認し、
`sudo systemctl start collector-ingest` → `tail -5 /mnt/sensor_data/logs/collector.log` で
「取り込み処理完了」が出れば復旧です（詳しい理由は 3-3 の「`nobrl` について」参照）。

## 週次レポートが届かない

コレクターPiにSSH接続して、上から順に:
```
$ systemctl list-timers --no-pager | grep collector
$ ls /mnt/sensor_data
$ tail -50 /mnt/sensor_data/logs/collector.log
$ sudo systemctl start collector-weekly
```
（(1)時間割が生きているか →(2)NASが見えているか →(3)ログにエラーがないか →(4)手動で再送）

- (2)で「そのようなファイルやディレクトリはありません」等 → `sudo mount -a` を実行して
  もう一度 `ls /mnt/sensor_data`。直らなければNASの電源・ネットワークを確認
- (3)に「Slackファイル送信に失敗」→ 同じ行のエラー名で原因がわかる（下の表を参照）

| ログ中のエラー名 | 原因 | 対処 |
|---|---|---|
| `not_in_channel` | Botがチャンネルに未招待 | チャンネルで `/invite @Botの名前` を実行 |
| `channel_not_found` | チャンネルIDの書き間違い（名前を書いた等） | フェーズ6「通知チャンネルやトークンを変更したいとき」の手順でIDを書き直す |
| `invalid_auth` / `token_revoked` | トークンが無効・失効（古いトークンを書いた等） | 管理者へ連絡（トークンを再発行し、同手順で書き換える） |

## Slackに何も届かなくなった（全部屋一斉）

原因は「コレクターPiの停止」「NASの停止」「Slackトークンの失効」のどれかです。
「週次レポートが届かない」の(1)〜(4)で切り分けて、直らなければ管理者へ。

## エスカレーション基準（すぐ管理者に連絡すべき状況）

1. 上記の手順を実行しても30分以内に復旧しない
2. センサーやPi本体の**物理的な故障**が疑われる（焦げた匂い、LEDが点かない等）
3. NAS（DSM）にログインできない、またはNASの空き容量が10%を切っている
4. **身に覚えのないファイルやユーザーがNASにある**
   （セキュリティ問題の可能性。**何も触らず**即連絡）
5. パスワードやトークンを紛失した、または漏れた疑いがある

連絡先: ＿＿＿＿＿＿＿＿＿＿（管理者名・連絡方法を記入）

---

# 用語集

| 用語 | 意味 |
|---|---|
| Raspberry Pi（Pi） | 手のひらサイズの小型コンピュータ。各部屋で温湿度を測っている |
| NAS | ネットワークにつながったデータ保管庫。この研究室ではSynology社製 |
| SSH | 別のコンピュータにネットワーク越しにログインして操作する仕組み。`ssh ユーザー名@IPアドレス` で接続する |
| IPアドレス | ネットワーク上の住所にあたる数字（例: 192.168.1.21） |
| SMB / マウント | NASのフォルダをPiの1フォルダのように見せる仕組み。全Piは `/mnt/sensor_data` を通じてNASを読み書きしている |
| fstab | Piの起動時に自動でマウントするための設定ファイル（/etc/fstab） |
| scp | SSHを使ってパソコンとPiの間でファイルをコピーするコマンド |
| nano | ターミナルの中で動くメモ帳。Ctrl+Oで保存、Ctrl+Xで終了 |
| sudo | コマンドを管理者権限で実行するためのおまじない |
| systemd / サービス | プログラムを常時動かし、Piの起動時に自動で立ち上げる仕組み。`systemctl` コマンドで操作する |
| タイマー | systemdの機能で、決まった時刻・間隔でプログラムを実行する時間割 |
| ログ | プログラムの動作記録。トラブル時はまずログを見る（`journalctl` コマンドや collector.log） |
| SQLite | 1つのファイルでできている簡易データベース。全部屋の測定データは NASの `db/sensor_data.sqlite3` に入っている |
| CSV | カンマ区切りのテキストデータファイル。Excelでも開ける |
| コレクター | データの取り込み・アラート判定・週次レポートを行うプログラム（collector.py）。コレクター役のPiで動く |
| ベースライン期間 | 運用開始から1週間、アラートを出さずに「その部屋の普段の変動幅」を学習する期間 |
| k（閾値係数） | アラートの敏感さを決める数字。大きいほど鈍感（誤報が減る）、小さいほど敏感（見逃しが減る） |
| DSM | Synology NASの管理画面。ブラウザで `http://【NASのIP】:5000` を開く |
| スナップショット | NASのその時点の状態を丸ごと記録する機能。間違って消したデータを復元できる |
