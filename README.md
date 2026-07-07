# Scripts for Raspberry pi imaging system

These scripts are used for the imaging system using Raspberry pi camera.  

## Description
![An in-depth paragraph about your project and overview of use.](imgs/Raspi.png)  

Result
![RaspiResult](imgs/RaspiResult.png)

## Getting Started
### Dependencies
Scripts work on following environments.  
- Raspberry pi 4B (2, 4, 8gb RAM)
- Raspberry pi zero WH (preview does not work)

### Develop Raspberry pi system
Please refer [MakeLegoSystem.md](elegans/MakeLegoSystem.md)

### Installing
Currently, there is no installation.  
Just download the scripts and run it.  

### Executing program

## Help

### GPIO / DHT22センサー トラブルシューティング手順

#### 症状1: プログラムがGPIO初期化のところで止まり、それ以降動かない

**原因**: 前回の異常終了でGPIO4が「使用中」のままロックされている。

**手順**:
1. 別のターミナルで多重起動していないか確認する
   ```bash
   ps aux | grep temp_humid_notifier
   ```
2. PIDファイルを確認し、古いプロセスを終了させる
   ```bash
   cat /tmp/temp_humid_notifier.pid
   sudo kill <上記のPID>
   ```
3. GPIOリセットスクリプトを実行する
   ```bash
   cd temperature_humidity_notifier
   sudo python3 gpio_reset.py
   ```
4. リセット後にプログラムを再起動する（systemd運用の場合）
   ```bash
   sudo systemctl restart sensor-client
   ```
   手動で起動する場合は `--nas-target` の指定が必須（temperature_humidity_notifier/OPERATIONS.md 参照）
5. それでも解決しない場合は Raspberry Pi を再起動する（最終手段）
   ```bash
   sudo reboot
   ```

---

#### 症状2: `unable to set line to input` エラーが出る

**原因**: GPIO4が別プロセスによってすでに確保されている。

**手順**:
1. GPIO4 を使っているプロセスを調べる
   ```bash
   sudo fuser /dev/gpiomem
   lsof /dev/gpiomem
   ```
2. 競合プロセスを特定して終了させる
   ```bash
   sudo kill <PID>
   ```
3. 念のためGPIOリセットスクリプトを実行する
   ```bash
   sudo python3 temperature_humidity_notifier/gpio_reset.py
   ```
4. プログラムを再起動する

---

#### 症状3: センサーが繰り返し `None` を返し続ける（数値が取れない）

**原因**: DHT22の一時的な読み取りエラー（よく起こる）か、配線の問題。

**手順**:
1. ログでエラーの詳細を確認する
   ```bash
   journalctl -u sensor-client -n 50 --no-pager
   ```
2. ログに `タイムアウト` と表示される場合 → 症状1の手順に従う
3. ログに `RuntimeError` が表示される場合 → 一時的なノイズのことが多いので5〜10分待って様子を見る
4. ログに `重大エラー` が表示される場合 → センサーの物理的な配線を確認する
   - DHT22の DATA ピンが GPIO4（物理ピン7）に接続されているか
   - 3.3V と GND の接続が正しいか
   - DATA ピンに 4.7kΩ のプルアップ抵抗が付いているか

---

#### 症状4: `センサー読み取りが N 秒でタイムアウトしました` とログに出る

**原因**: GPIOがハードウェアレベルでフリーズしている。プログラム自体はタイムアウト機能により継続動作するが、センサーが復旧しない場合は手動対処が必要。

**手順**:
1. プログラムを Ctrl+C で止める
2. GPIOリセットスクリプトを実行する
   ```bash
   sudo python3 temperature_humidity_notifier/gpio_reset.py
   ```
3. pigpiod が使われている場合はサービスを再起動する
   ```bash
   sudo systemctl restart pigpiod
   ```
4. プログラムを再起動する
   ```bash
   sudo systemctl restart sensor-client
   ```

---

#### よく使う確認コマンド

```bash
# GPIO4の状態確認
ls /sys/class/gpio/gpio4/ 2>/dev/null && echo "GPIO4使用中" || echo "GPIO4未使用"

# /dev/gpiomem へのアクセス権限確認
ls -la /dev/gpiomem

# pigpiod の動作確認
sudo systemctl status pigpiod

# ログの末尾を確認（何で止まっているか調べる）
journalctl -u sensor-client -n 50 --no-pager
tail -50 temperature_humidity_notifier/temp_humid_notifier.log
```

## Authors

Shinichi Miyazaki (https://github.com/Shinichi-Miyazaki)  

## Version History

* 0.1
    * Initial Release

## License

This project is licensed under the MIT License - see the LICENSE.md file for details

## Acknowledgments
